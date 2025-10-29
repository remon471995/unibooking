# core/views.py
import io
import base64
import csv
import re
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal
from datetime import date, datetime, timedelta # تم إضافة date

# Django ORM / DB funcs
from django.db.models import (
    OuterRef, Subquery, Sum, Count, Q, DecimalField, F, Value as V, Max
)
from django.db.models.functions import Coalesce, TruncDate, ExtractMonth, TruncMonth

# Django shortcuts & utils
from django.views.decorators.http import require_POST, require_http_methods
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden # تم إضافة HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test # تم إضافة user_passes_test
from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import format_html
from django.forms import inlineformset_factory # تم تعديل الاستيراد ليكون صريحاً
import django.forms as forms # تم إضافة الاستيراد لـ forms
from django.core.paginator import Paginator
from django.conf import settings
from django.db import transaction
from django.shortcuts import render, get_object_or_404
# from core.models import Department # مستورد لاحقاً
from django.db.models import Value, CharField, DateField # تم إضافة DateField

# Excel
try:
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True # تم إضافة متغير للتحقق
except Exception:
    Workbook = None
    OPENPYXL_AVAILABLE = False # تم إضافة متغير للتحقق
    def get_column_letter(i): return "A"

# PDF (WeasyPrint)
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

# External libs
import qrcode
from qrcode.image.pil import PilImage

# Models & Forms
from .models import (
    UniBookingCard, HotelBooking, FlightBooking, OtherBooking,
    Payment, FlightPayment, OtherPayment, Room, Notification,
    Department # تم نقل الاستيراد هنا
)
# Note: Card alias was removed, using UniBookingCard directly
from .forms import (
    UniBookingCardForm, HotelBookingForm, PaymentForm, # <- PaymentForm موجود
    FlightBookingForm, FlightPaymentForm, RoomForm,    # <- RoomForm موجود
    OtherBookingForm, OtherPaymentForm,
)


User = get_user_model()

# ===================== Helpers عامة =====================

D0 = Decimal("0.00")

def _sumdec(expr):
    return Coalesce(Sum(expr), D0, output_field=DecimalField(max_digits=14, decimal_places=2))

def _count(expr="id"):
    return Coalesce(Count(expr), 0)

def _build_qr_data_url(text: str) -> str | None: # تم تعديل النوع
    try:
        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(text)
        qr.make(fit=True)
        img: PilImage = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
    except Exception:
        return None # Return None on failure


def _render_pdf_from_template(template_name: str, context: dict, request) -> bytes | None: # تم تعديل النوع ليكون اختياري
    if not WEASYPRINT_AVAILABLE:
        messages.error(request, "مكتبة WeasyPrint غير مثبتة لإنشاء PDF.")
        return None
    try:
        html_string = get_template(template_name).render(context)
        base_url = request.build_absolute_uri('/')
        return HTML(string=html_string, base_url=base_url).write_pdf()
    except Exception as e:
        messages.error(request, f"حدث خطأ أثناء إنشاء PDF: {e}")
        # Log error e
        return None


def _cards_base_qs(request):
    # Added permission check: Superusers see all, others see their own
    if request.user.is_superuser:
        return UniBookingCard.objects.all()
    else:
        return UniBookingCard.objects.filter(created_by=request.user)


def _latest_emp_subquery(model, fk_name):
    # Assuming the payment models have 'employee_name' field
    if hasattr(model, 'employee_name'):
         return Subquery(
             model.objects.filter(**{fk_name: OuterRef('pk')})
             .order_by('-created_at').values('employee_name')[:1]
         )
    return V(None, output_field=CharField()) # Return None if field doesn't exist


# تاريخ محاسبي موحّد لكل الحجوزات
def _with_acc_date(qs):
    # acc_date = accounting_date -> booking_date -> TruncDate(created_at)
    # Ensure fields exist before using them
    has_acc_date = hasattr(qs.model, 'accounting_date')
    has_book_date = hasattr(qs.model, 'booking_date')
    has_created_at = hasattr(qs.model, 'created_at')

    if has_acc_date and has_book_date and has_created_at:
        return qs.annotate(acc_date=Coalesce('accounting_date', 'booking_date', TruncDate('created_at')))
    elif has_book_date and has_created_at:
        return qs.annotate(acc_date=Coalesce('booking_date', TruncDate('created_at')))
    elif has_created_at:
         return qs.annotate(acc_date=TruncDate('created_at'))
    else:
         # Fallback if no date field is found (should not happen ideally)
         return qs.annotate(acc_date=V(None, output_field=DateField()))


def _date_filter_using_acc(qs, date_from, date_to):
    qs = _with_acc_date(qs)
    if date_from:
        qs = qs.filter(acc_date__gte=date_from)
    if date_to:
        qs = qs.filter(acc_date__lte=date_to) # Use lte for inclusive end date
    return qs

# --- Normalization functions --- (Keep as they are)
def _norm_airline(name: str) -> str:
    raw = (name or '').strip()
    key = ' '.join(raw.replace('_', ' ').lower().split())
    iata = raw.upper()
    if len(iata) == 2 and iata.isalnum():
        iata_map = {
            'KU': 'Kuwait Airways', 'EK': 'Emirates', 'EY': 'Etihad Airways',
            'QR': 'Qatar Airways', 'SV': 'Saudia', 'MS': 'EGYPTAIR', 'FZ': 'flydubai',
            'WY': 'Oman Air', 'RJ': 'Royal Jordanian', 'GF': 'Gulf Air', 'J9': 'Jazeera Airways',
        }
        return iata_map.get(iata, iata)
    name_map = {
        'kuwait airways': 'Kuwait Airways', 'emirates': 'Emirates',
        'emirates airlines': 'Emirates', 'etihad airways': 'Etihad Airways',
        'qatar airways': 'Qatar Airways', 'egyptair': 'EGYPTAIR', 'saudia': 'Saudia',
        'flydubai': 'flydubai', 'oman air': 'Oman Air', 'royal jordanian': 'Royal Jordanian',
        'gulf air': 'Gulf Air', 'jazeera airways': 'Jazeera Airways', '-': '-', '': '-',
    }
    return name_map.get(key, raw.title() if raw else '-')

def _norm_supplier(name: str) -> str:
    raw = (name or '').strip()
    key = ' '.join(raw.replace('_', ' ').lower().split())
    sup_map = {
        'smile': 'Smile', 'smil': 'Smile', 'tbo': 'TBO', 't b o': 'TBO',
        'amadeus': 'Amadeus', 'amaedus': 'Amadeus', 'amadeus gds': 'Amadeus',
        'sabre': 'Sabre', 'galileo': 'Galileo', 'apollo': 'Apollo',
        '': '-', '-': '-', 'none': '-',
    }
    return sup_map.get(key, raw.title() if raw else '-')

# ===================== Permissions Check for Ledger =====================
# دالة التحقق من الصلاحيات لدفتر الأستاذ
def can_view_ledger(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    # نفترض أن البروفايل موجود ورابط بالـ user عبر user.profile
    profile = getattr(user, 'profile', None)
    # عدّل الأدوار حسب ما هو موجود عندك في UserProfile
    if profile and profile.role in ['LEADER', 'MANAGER', 'ACCOUNTANT', 'ADMIN']: # تم إضافة ADMIN كمثال
        return True
    return False

# ===================== Notifications =====================
@login_required
def notifications_list(request):
    status = (request.GET.get("status") or "unread").strip() # Default unread
    page_num = int(request.GET.get("page") or 1)

    # Permissions scope
    if request.user.is_superuser:
        base = Q(to_superusers=True) | Q(to_user=request.user)
    else:
        base = Q(to_user=request.user)

    qs = Notification.objects.filter(base).order_by('-created_at')

    # Filter by status
    if status == "unread":
        qs = qs.filter(is_read=False)
    elif status == "read":
        qs = qs.filter(is_read=True)
    # else status == 'all' -> no filter

    # Counts for filters
    counts = {
        "total": Notification.objects.filter(base).count(),
        "unread": Notification.objects.filter(base, is_read=False).count(),
        "read": Notification.objects.filter(base, is_read=True).count(),
    }

    paginator = Paginator(qs, 20) # 20 per page
    page_obj = paginator.get_page(page_num)

    return render(request, 'core/notifications.html', {
        'page_obj': page_obj,
        'rows': list(page_obj.object_list), # Pass the list directly
        'status': status,
        'counts': counts,
    })

@login_required
@require_POST # Make it POST only for safety
def notification_mark_read(request, pk):
    n = get_object_or_404(Notification, pk=pk)
    # Check permissions
    if request.user.is_superuser or n.to_user_id == request.user.id:
        if not n.is_read: # Only update if not already read
            n.is_read = True
            n.read_at = timezone.now() # Record read time
            n.save(update_fields=['is_read', 'read_at'])
            messages.success(request, "تم تمييز التنبيه كمقروء.")
        # Redirect anyway, even if already read
        return redirect(n.target_url or 'notifications_list')
    else:
        messages.error(request, "غير مصرح لك بتعديل هذا التنبيه.")
        return redirect('notifications_list')


# ===================== Dashboard / Cards =====================
@login_required
def dashboard(request):
    qs = _cards_base_qs(request) # Use the helper for permission scope
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(customer_name__icontains=q) |
            Q(ub_code__icontains=q) | # Use icontains for more flexibility
            Q(mobile__icontains=q)
        )
    paginator = Paginator(qs.order_by("-created_at"), 12) # 12 cards per page
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "core/dashboard.html", {"cards": page_obj, "q": q})


@login_required
def card_create(request):
    if request.method == 'POST':
        form = UniBookingCardForm(request.POST) # Use the correct form name
        if form.is_valid():
            card = form.save(commit=False)
            card.created_by = request.user
            card.save()
            messages.success(request, f"تم إنشاء كارت العميل {card.customer_name} بنجاح.")
            # Redirect to card detail using the assumed get_absolute_url or name
            try:
                 # Assumes Card model has get_absolute_url or url name is 'card_detail'
                 return redirect(card.get_absolute_url())
            except AttributeError:
                 return redirect('card_detail', pk=card.pk)
        else:
            errs = [f"{f}: {', '.join(e)}" for f, e in form.errors.items()]
            messages.error(request, format_html("تحقق من المدخلات: {}", "; ".join(errs)))
    else:
        form = UniBookingCardForm()
    return render(request, 'core/card_form.html', {'form': form})


@login_required
def card_detail(request, pk):
    # Use _cards_base_qs to ensure user can only view cards they own (unless superuser)
    card = get_object_or_404(_cards_base_qs(request).select_related('created_by'), pk=pk)

    # Fetch related bookings efficiently
    hotel_bookings = card.hotel_bookings.order_by('-created_at') # Use related_name
    flight_bookings = card.flight_bookings.order_by('-created_at') # Use related_name
    other_bookings = card.other_bookings.order_by('-created_at') # Use related_name

    # Calculate totals using aggregation for potentially better performance
    totals_agg = card.hotel_bookings.aggregate(
        h_sell=Coalesce(Sum('sell'), D0), h_net=Coalesce(Sum('net'), D0),
        h_paid=Coalesce(Sum('payments__paid_amount'), D0) # Assumes related_name='payments' on Payment
    )
    totals_agg.update(card.flight_bookings.aggregate(
        f_sell=Coalesce(Sum('sell_price'), D0), f_net=Coalesce(Sum('net_price'), D0),
        f_paid=Coalesce(Sum('payments__paid_amount'), D0) # Assumes related_name='payments' on FlightPayment
    ))
    totals_agg.update(card.other_bookings.aggregate(
        o_sell=Coalesce(Sum('sell_price'), D0), o_net=Coalesce(Sum('net_price'), D0),
        o_paid=Coalesce(Sum('payments__paid_amount'), D0) # Assumes related_name='payments' on OtherPayment
    ))

    total_sell = totals_agg['h_sell'] + totals_agg['f_sell'] + totals_agg['o_sell']
    total_net = totals_agg['h_net'] + totals_agg['f_net'] + totals_agg['o_net']
    total_paid = totals_agg['h_paid'] + totals_agg['f_paid'] + totals_agg['o_paid']
    total_profit = total_sell - total_net
    total_remaining = total_sell - total_paid

    totals = {
        'total_sell': total_sell,
        'total_net': total_net,
        'total_profit': total_profit,
        'total_paid': total_paid,
        'total_remaining': total_remaining,
    }

    return render(request, "core/card_detail.html", {
        "card": card,
        "hotel_bookings": hotel_bookings,
        "flight_bookings": flight_bookings,
        "other_bookings": other_bookings,
        "totals": totals,
    })

# ===================== Cards Bulk Export/Delete =====================
@login_required
def cards_bulk_export(request):
    ids = request.GET.getlist('ids[]') or request.GET.getlist('ids')
    qs = _cards_base_qs(request) # Apply base permissions
    if ids:
        qs = qs.filter(id__in=ids)

    # Annotate counts efficiently
    qs = qs.annotate(
        hotels_count=Count('hotel_bookings', distinct=True), # Use related_name
        flights_count=Count('flight_bookings', distinct=True), # Use related_name
        others_count=Count('other_bookings', distinct=True), # Use related_name
    )

    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="cards_export.csv"'
    writer = csv.writer(resp)
    writer.writerow([
        'ID','UB Code','Customer','Mobile','Nationality','Country',
        'Hotels','Flights','Others','Created At' # Added Others count
    ])
    for c in qs:
        writer.writerow([
            c.id, c.ub_code, c.customer_name, c.mobile or '',
            c.nationality or '', c.country or '',
            c.hotels_count, c.flights_count, c.others_count, # Added Others count
            c.created_at.isoformat() if c.created_at else ''
        ])
    return resp

@login_required
@require_POST # Ensure POST method
def cards_bulk_delete(request):
    ids = request.POST.getlist('ids[]') or request.POST.getlist('ids')
    if not ids:
        return JsonResponse({'ok': False, 'error': 'No IDs provided'}, status=400)

    # Apply base permissions before deleting
    qs = _cards_base_qs(request).filter(id__in=ids)
    count = qs.count()
    if not count:
        return JsonResponse({'ok': False, 'error': 'No cards found matching IDs or permission denied'}, status=404)

    try:
        with transaction.atomic(): # Ensure atomicity
             deleted_count, _ = qs.delete()
        messages.success(request, f"تم حذف {deleted_count} كارت بنجاح.") # Add success message
        return JsonResponse({'ok': True, 'deleted': deleted_count})
    except Exception as e:
        # Log error e
        messages.error(request, f"حدث خطأ أثناء الحذف: {e}")
        return JsonResponse({'ok': False, 'error': 'Deletion failed'}, status=500)


# ===================== Hotel =====================
@login_required
def hotel_create(request, card_pk):
    card = get_object_or_404(UniBookingCard, pk=card_pk)
    # Apply permission check
    if not request.user.is_superuser and card.created_by != request.user:
        messages.error(request, "غير مسموح بإضافة حجز فندق على كارت ليس ملكك.")
        return redirect('dashboard')

    # Use the specific RoomForm here
    # Make sure Room model is imported
    RoomFormSet = inlineformset_factory(
        HotelBooking, Room, form=RoomForm, # 👈 تم التصحيح هنا
        extra=1, min_num=1, validate_min=True, # Ensure at least one room
        max_num=5, can_delete=True, # Allow deleting extra forms
    )

    if request.method == 'POST':
        form = HotelBookingForm(request.POST)
        room_formset = RoomFormSet(request.POST, prefix='rooms') # Don't forget prefix
        if form.is_valid() and room_formset.is_valid():
            try:
                with transaction.atomic():
                    hb = form.save(commit=False)
                    hb.card = card
                    # Ensure employee_name is set
                    hb.employee_name = request.user.get_full_name() or request.user.username
                    # Calculate nights if dates are valid
                    if hb.checkin and hb.checkout and hb.checkout > hb.checkin:
                        hb.nights = (hb.checkout - hb.checkin).days
                    else:
                         # Handle invalid date range if needed, form validation might cover this
                         pass
                    hb.save() # Save booking first to get an ID

                    # Save rooms related to the booking
                    room_formset.instance = hb
                    room_formset.save()

                messages.success(request, f"تم حفظ حجز الفندق. فوّتشر: {hb.voucher_code}")
                # Redirect to payment page for this booking
                return redirect('hotel_payment', booking_pk=hb.pk)
            except Exception as e:
                 messages.error(request, f"حدث خطأ أثناء الحفظ: {e}")
                 # Log error e
        else:
            if not form.is_valid():
                messages.error(request, "يرجى التحقق من بيانات الحجز الأساسية.")
            if not room_formset.is_valid():
                # Provide more specific errors if possible
                room_errors = room_formset.total_error_count()
                messages.error(request, f"يرجى التحقق من بيانات أسماء النزلاء ({room_errors} خطأ).")
    else:
        form = HotelBookingForm(initial={'booking_date': timezone.localdate()}) # Default booking date
        room_formset = RoomFormSet(prefix='rooms') # Use prefix

    return render(request, 'core/hotel_form.html', {
        'card': card, 'form': form, 'room_formset': room_formset
    })

@login_required
def hotel_voucher(request, booking_pk):
    # Apply permission check? Maybe only owner/superuser can view voucher?
    booking = get_object_or_404(HotelBooking.objects.select_related('card'), pk=booking_pk)
    # Check permission (e.g., if card owner or superuser)
    if not request.user.is_superuser and booking.card.created_by != request.user:
         messages.error(request, "غير مصرح لك بعرض هذا الفاوتشر.")
         return redirect('card_detail', pk=booking.card.pk)

    qr_data_url = _build_qr_data_url(
        request.build_absolute_uri(reverse('hotel_voucher', args=[booking.pk]))
    )
    rooms = booking.rooms.all() # Fetch related rooms
    return render(request, 'core/voucher.html', { # Ensure template name is correct
        'booking': booking,
        'today': timezone.localdate(),
        'nights': booking.nights, # Assuming nights is calculated on save
        'qr_data_url': qr_data_url,
        'rooms': rooms,
    })

@login_required
def hotel_voucher_pdf(request, booking_pk):
    # Apply permission check
    booking = get_object_or_404(HotelBooking.objects.select_related('card'), pk=booking_pk)
    if not request.user.is_superuser and booking.card.created_by != request.user:
         messages.error(request, "غير مصرح لك بطباعة هذا الفاوتشر.")
         return redirect('card_detail', pk=booking.card.pk)

    qr_data_url = _build_qr_data_url(
        request.build_absolute_uri(reverse('hotel_voucher', args=[booking.pk]))
    )
    rooms = booking.rooms.all()
    context = {
        'booking': booking,
        'today': timezone.localdate(),
        'nights': booking.nights,
        'qr_data_url': qr_data_url,
        'rooms': rooms,
    }
    # Use the correct PDF template name
    pdf_bytes = _render_pdf_from_template('core/voucher_pdf.html', context, request)
    if pdf_bytes is None:
        # Error message is already added by _render_pdf_from_template
        return redirect('hotel_voucher', booking_pk=booking.pk) # Redirect back

    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    # Make inline for preview, attachment for download
    resp['Content-Disposition'] = f'inline; filename="Voucher_{booking.voucher_code}.pdf"'
    # resp['Content-Disposition'] = f'attachment; filename="Voucher_{booking.voucher_code}.pdf"'
    return resp


# ===================== إدارة دفع الفنادق (مثال محدث) =====================
@login_required
def hotel_payment(request, booking_pk):
    booking = get_object_or_404(HotelBooking.objects.select_related('card'), pk=booking_pk)
    # Apply permission check (e.g., owner or superuser)
    if not request.user.is_superuser and booking.card.created_by != request.user:
         messages.error(request, "غير مصرح لك بإدارة دفعات هذا الحجز.")
         return redirect('card_detail', pk=booking.card.pk)

    payments = booking.payments.order_by("-created_at") # Use related_name
    has_existing = payments.exists()

    # Calculate totals accurately using aggregation
    payment_totals = payments.aggregate(total=Coalesce(Sum("paid_amount"), D0))
    total_paid = payment_totals['total']
    total_sell = booking.sell or D0
    total_net  = booking.net or D0
    remaining  = total_sell - total_paid
    profit     = total_sell - total_net

    if request.method == "POST":
        # Use PaymentForm as it's correctly imported now
        form = PaymentForm(request.POST, request.FILES, booking=booking, has_existing_payments=has_existing)
        if form.is_valid():
            cd = form.cleaned_data
            paid_amount = cd.get("paid_amount") or D0

            # --- Validation specific to payment logic ---
            sell_price_from_form = cd.get("sell_price") if not has_existing else total_sell
            net_price_from_form = cd.get("net_price") if not has_existing else total_net

            # Prevent negative payments
            if paid_amount < 0:
                form.add_error("paid_amount", "المبلغ المدفوع يجب أن يكون صفراً أو قيمة موجبة.")

            # File requirements for first payment
            if not has_existing:
                if not cd.get("invoice_file"):
                     form.add_error("invoice_file", "ملف الفاتورة مطلوب عند أول دفعة.")
                # voucher_original check might depend on PaymentForm fields
                if not cd.get("voucher_original"):
                     form.add_error("voucher_original", "الفاوتشر الأصلي مطلوب عند أول دفعة.")


            # Requirements based on method
            method = cd.get("method")
            if method == "link" and not cd.get("payment_link"):
                form.add_error("payment_link", "رابط السداد مطلوب لطريقة الدفع (Link).")
            if method in ("bank", "cash") and not cd.get("bank_file"):
                form.add_error("bank_file", "مطلوب رفع إيصال للـ Bank/Cash.")

            # Installment date requirement for partial first payment
            if not has_existing and paid_amount < sell_price_from_form:
                if not cd.get("installment_date"):
                    form.add_error("installment_date", "مطلوب تحديد آخر ميعاد للسداد عند أول دفعة غير كاملة.")

            # --- If errors exist after manual validation, re-render ---
            if form.errors:
                messages.error(request, "صحح الأخطاء ثم حاول مرة أخرى.")
                # Re-render with existing context
                context = {
                    "booking": booking, "form": form, "payments": payments,
                    "remaining": remaining, "total_paid": total_paid,
                    "total_sell": total_sell, "total_net": total_net,
                    "profit": profit, "has_existing": has_existing,
                }
                return render(request, "core/hotel_payment.html", context)

            # --- Save Payment and update Booking if first payment ---
            try:
                with transaction.atomic():
                    p = form.save(commit=False)
                    # Link payment to the correct booking FK
                    p.booking_hotel = booking
                    p.employee_name = request.user.get_full_name() or request.user.username

                    if not has_existing:
                         # Update booking net/sell only once on first payment
                         booking.net = net_price_from_form
                         booking.sell = sell_price_from_form
                         # Set agreed due date if installment
                         if paid_amount < sell_price_from_form:
                             booking.agreed_last_due = cd.get("installment_date")
                         else:
                              booking.agreed_last_due = None
                         booking.save(update_fields=['net', 'sell', 'agreed_last_due'])
                    # Set installment date on the payment object itself if applicable
                    p.installment_date = cd.get("installment_date") if (not has_existing and paid_amount < sell_price_from_form) else None

                    # Set net/sell prices on payment for historical record (optional but good practice)
                    p.net_price = net_price_from_form
                    p.sell_price = sell_price_from_form

                    p.save() # Save the payment object

                messages.success(request, "✅ تم حفظ بيانات الدفع بنجاح.")
                return redirect("hotel_payment", booking_pk=booking.pk)
            except Exception as e:
                 messages.error(request, f"حدث خطأ أثناء الحفظ: {e}")
                 # Log error e
                 # Re-render form with error
                 context = {
                     "booking": booking, "form": form, "payments": payments,
                     "remaining": remaining, "total_paid": total_paid,
                     "total_sell": total_sell, "total_net": total_net,
                     "profit": profit, "has_existing": has_existing,
                 }
                 return render(request, "core/hotel_payment.html", context)

        else: # Form is invalid
            messages.error(request, "⚠️ يوجد خطأ في البيانات المدخلة.")
    else: # GET request
        # Initial amount suggestion
        initial_amount = remaining if remaining > 0 else None
        # Use PaymentForm
        form = PaymentForm(booking=booking, has_existing_payments=has_existing, initial={'paid_amount': initial_amount})

    # Prepare context for rendering GET or invalid POST
    context = {
        "booking": booking, "form": form, "payments": payments,
        "remaining": remaining, "total_paid": total_paid,
        "total_sell": total_sell, "total_net": total_net,
        "profit": profit, "has_existing": has_existing,
    }
    return render(request, "core/hotel_payment.html", context)


# ===================== Flight =====================
@login_required
def flight_create(request, card_pk):
    card = get_object_or_404(UniBookingCard, pk=card_pk)
    if not request.user.is_superuser and card.created_by != request.user:
        messages.error(request, "غير مسموح بإنشاء حجز طيران في كارت ليس ملكك.")
        return redirect('dashboard')

    if request.method == "POST":
        form = FlightBookingForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                booking = form.save(commit=False)
                booking.card = card
                booking.employee_name = request.user.get_full_name() or request.user.username
                booking.save()
                messages.success(request, f"تم حفظ حجز الطيران PNR: {booking.pnr}")
                return redirect("flight_payment", booking_pk=booking.pk)
            except Exception as e:
                 messages.error(request, f"حدث خطأ أثناء الحفظ: {e}")
                 # Log e
        else:
             messages.error(request, "يرجى التحقق من بيانات الحجز.")
    else:
        form = FlightBookingForm(initial={'booking_date': timezone.localdate()}) # Default date
    return render(request, "core/flight_form.html", {"form": form, "card": card})

@login_required
def flight_voucher(request, booking_pk):
    # Apply permission check
    b = get_object_or_404(FlightBooking.objects.select_related('card'), pk=booking_pk)
    if not request.user.is_superuser and b.card.created_by != request.user:
         messages.error(request, "غير مصرح لك بعرض هذا الفاوتشر.")
         return redirect('card_detail', pk=b.card.pk)

    qr = _build_qr_data_url(request.build_absolute_uri(reverse("flight_voucher", args=[b.pk])))
    return render(request, "core/flight_voucher.html", { # Ensure template name is correct
        "b": b, "today": timezone.localdate(), "qr_data_url": qr,
    })

@login_required
def flight_voucher_pdf(request, booking_pk):
    # Apply permission check
    b = get_object_or_404(FlightBooking.objects.select_related('card'), pk=booking_pk)
    if not request.user.is_superuser and b.card.created_by != request.user:
         messages.error(request, "غير مصرح لك بطباعة هذا الفاوتشر.")
         return redirect('card_detail', pk=b.card.pk)

    qr = _build_qr_data_url(request.build_absolute_uri(reverse('flight_voucher', args=[b.pk])))
    context = {'b': b, 'today': timezone.localdate(), 'qr_data_url': qr}
    # Use the correct PDF template name
    pdf_bytes = _render_pdf_from_template('core/flight_voucher_pdf.html', context, request)
    if pdf_bytes is None:
        return redirect('flight_voucher', booking_pk=b.pk) # Redirect back

    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Flight_{b.pnr or b.voucher_code}.pdf"' # Use PNR or code
    return resp

@login_required
def flight_payment(request, booking_pk):
    booking = get_object_or_404(FlightBooking.objects.select_related('card'), pk=booking_pk)
    # Apply permission check
    if not request.user.is_superuser and booking.card.created_by != request.user:
         messages.error(request, "غير مصرح لك بإدارة دفعات هذا الحجز.")
         return redirect('card_detail', pk=booking.card.pk)

    payments = booking.payments.order_by("-created_at") # Use related_name
    has_existing = payments.exists()

    payment_totals = payments.aggregate(total=Coalesce(Sum("paid_amount"), D0))
    total_paid = payment_totals['total']
    total_sell = booking.sell_price or D0 # Note: sell_price
    total_net  = booking.net_price or D0  # Note: net_price
    remaining  = total_sell - total_paid
    profit     = total_sell - total_net

    if request.method == "POST":
        form = FlightPaymentForm(request.POST, request.FILES, booking=booking, has_existing_payments=has_existing)
        if form.is_valid():
            # --- Validation & Saving Logic (Similar to hotel_payment) ---
            cd = form.cleaned_data
            paid_amount = cd.get("paid_amount") or D0
            sell_price_from_form = cd.get("sell_price") if not has_existing else total_sell
            net_price_from_form = cd.get("net_price") if not has_existing else total_net

            if paid_amount < 0: form.add_error("paid_amount", "المبلغ المدفوع يجب أن يكون صفراً أو قيمة موجبة.")
            # Add other validations similar to hotel_payment if needed...
            # (e.g., file requirements, method check, installment date)
            if not has_existing:
                if not cd.get("invoice_file"):
                     form.add_error("invoice_file", "ملف الفاتورة مطلوب.")
                if not cd.get("voucher_original"):
                     form.add_error("voucher_original", "الفاوتشر الأصلي مطلوب.")
            if cd.get("method") == "link" and not cd.get("payment_link"):
                 form.add_error("payment_link", "الرابط مطلوب.")
            if cd.get("method") in ("bank", "cash") and not cd.get("bank_file"):
                 form.add_error("bank_file", "الإيصال مطلوب.")
            if not has_existing and paid_amount < sell_price_from_form and not cd.get("installment_date"):
                 form.add_error("installment_date", "تاريخ القسط مطلوب.")


            if form.errors:
                 messages.error(request, "صحح الأخطاء ثم حاول مرة أخرى.")
                 context = { # Prepare context again
                     "booking": booking, "form": form, "payments": payments,
                     "total_net": total_net, "total_sell": total_sell,
                     "total_paid": total_paid, "remaining": remaining,
                     "profit": profit, "has_existing": has_existing,
                 }
                 return render(request, "core/flight_payment.html", context)

             try:
                with transaction.atomic():
                    p = form.save(commit=False)
                    p.booking_flight = booking # Link to flight booking
                    p.employee_name = request.user.get_full_name() or request.user.username

                    if not has_existing:
                         booking.net_price = net_price_from_form
                         booking.sell_price = sell_price_from_form
                         if paid_amount < sell_price_from_form:
                             booking.agreed_last_due = cd.get("installment_date")
                         else:
                              booking.agreed_last_due = None
                         booking.save(update_fields=['net_price', 'sell_price', 'agreed_last_due'])

                    p.installment_date = cd.get("installment_date") if (not has_existing and paid_amount < sell_price_from_form) else None
                    # Set prices on payment?
                    p.net_price = net_price_from_form
                    p.sell_price = sell_price_from_form
                    p.save()

                messages.success(request, "✅ تم حفظ بيانات الدفع بنجاح.")
                return redirect("flight_payment", booking_pk=booking.pk)
             except Exception as e:
                 messages.error(request, f"حدث خطأ أثناء الحفظ: {e}")
                 # Log e, re-render form
                 context = { # Prepare context again
                     "booking": booking, "form": form, "payments": payments,
                     "total_net": total_net, "total_sell": total_sell,
                     "total_paid": total_paid, "remaining": remaining,
                     "profit": profit, "has_existing": has_existing,
                 }
                 return render(request, "core/flight_payment.html", context)

        else: # Form invalid
            messages.error(request, "⚠️ يوجد خطأ في البيانات المدخلة.")
    else: # GET request
        initial_amount = remaining if remaining > 0 else None
        form = FlightPaymentForm(booking=booking, has_existing_payments=has_existing, initial={'paid_amount': initial_amount})

    context = {
        "booking": booking, "form": form, "payments": payments,
        "total_net": total_net, "total_sell": total_sell,
        "total_paid": total_paid, "remaining": remaining,
        "profit": profit, "has_existing": has_existing,
    }
    return render(request, "core/flight_payment.html", context)


# ===================== Other =====================
@login_required
def other_create(request, card_pk):
    card = get_object_or_404(UniBookingCard, pk=card_pk)

    # Apply permission check
    if not request.user.is_superuser and card.created_by != request.user:
        messages.error(request, "غير مسموح بإضافة خدمة/حجز على كارت ليس ملكك.")
        return redirect('dashboard')

    if request.method == "POST":
        form = OtherBookingForm(request.POST, request.FILES) # Include FILES if needed
        if form.is_valid():
            try:
                other = form.save(commit=False)
                other.card = card
                other.employee_name = request.user.get_full_name() or request.user.username
                other.save()
                messages.success(request, f"تم حفظ الخدمة: {other.get_service_type_display()}")
                # Redirect to its payment page
                return redirect("other_payment", pk=other.pk)
            except Exception as e:
                 messages.error(request, f"حدث خطأ أثناء الحفظ: {e}")
                 # Log e
        else:
            messages.error(request, "من فضلك املأ الحقول الإلزامية بشكل صحيح.")
    else:
        form = OtherBookingForm(initial={'booking_date': timezone.localdate()}) # Default date

    return render(request, "core/other_form.html", {"form": form, "card": card})


@login_required
def other_payment(request, pk): # Renamed arg to pk to match URL conf
    booking = get_object_or_404(OtherBooking.objects.select_related('card'), pk=pk)
    # Apply permission check
    if not request.user.is_superuser and booking.card.created_by != request.user:
         messages.error(request, "غير مصرح لك بإدارة دفعات هذا الحجز.")
         return redirect('card_detail', pk=booking.card.pk)

    payments = booking.payments.order_by("-created_at") # Use related_name
    has_existing = payments.exists()

    payment_totals = payments.aggregate(total=Coalesce(Sum("paid_amount"), D0))
    total_paid = payment_totals['total']
    total_sell = booking.sell_price or D0 # Note: sell_price
    total_net  = booking.net_price or D0  # Note: net_price
    remaining  = total_sell - total_paid
    profit     = total_sell - total_net

    if request.method == "POST":
        form = OtherPaymentForm(request.POST, request.FILES, booking=booking, has_existing_payments=has_existing)
        if form.is_valid():
            # --- Validation & Saving Logic (Similar to hotel_payment) ---
            cd = form.cleaned_data
            paid_amount = cd.get("paid_amount") or D0
            sell_price_from_form = cd.get("sell_price") if not has_existing else total_sell
            net_price_from_form = cd.get("net_price") if not has_existing else total_net

            if paid_amount < 0: form.add_error("paid_amount", "المبلغ المدفوع يجب أن يكون صفراً أو قيمة موجبة.")
            # Add other validations similar to hotel_payment if needed...
            if not has_existing:
                if not cd.get("invoice_file"):
                     form.add_error("invoice_file", "ملف الفاتورة مطلوب.")
                if not cd.get("voucher_original"):
                     form.add_error("voucher_original", "الفاوتشر الأصلي مطلوب.")
            if cd.get("method") == "link" and not cd.get("payment_link"):
                 form.add_error("payment_link", "الرابط مطلوب.")
            if cd.get("method") in ("bank", "cash") and not cd.get("bank_file"):
                 form.add_error("bank_file", "الإيصال مطلوب.")
            if not has_existing and paid_amount < sell_price_from_form and not cd.get("installment_date"):
                 form.add_error("installment_date", "تاريخ القسط مطلوب.")

            if form.errors:
                 messages.error(request, "صحح الأخطاء ثم حاول مرة أخرى.")
                 context = { # Prepare context again
                     "booking": booking, "form": form, "payments": payments,
                     "total_net": total_net, "total_sell": total_sell,
                     "total_paid": total_paid, "remaining": remaining,
                     "profit": profit, "has_existing": has_existing,
                 }
                 return render(request, "core/other_payment.html", context)

             try:
                with transaction.atomic():
                    p = form.save(commit=False)
                    p.booking_other = booking # Link to other booking
                    p.employee_name = request.user.get_full_name() or request.user.username

                    if not has_existing:
                         booking.net_price = net_price_from_form
                         booking.sell_price = sell_price_from_form
                         if paid_amount < sell_price_from_form:
                             booking.agreed_last_due = cd.get("installment_date")
                         else:
                              booking.agreed_last_due = None
                         booking.save(update_fields=['net_price', 'sell_price', 'agreed_last_due'])

                    p.installment_date = cd.get("installment_date") if (not has_existing and paid_amount < sell_price_from_form) else None
                    # Set prices on payment?
                    p.net_price = net_price_from_form
                    p.sell_price = sell_price_from_form
                    p.save()

                messages.success(request, "✅ تم حفظ بيانات الدفع بنجاح.")
                return redirect("other_payment", pk=booking.pk) # Use pk here
             except Exception as e:
                 messages.error(request, f"حدث خطأ أثناء الحفظ: {e}")
                 # Log e, re-render form
                 context = { # Prepare context again
                     "booking": booking, "form": form, "payments": payments,
                     "total_net": total_net, "total_sell": total_sell,
                     "total_paid": total_paid, "remaining": remaining,
                     "profit": profit, "has_existing": has_existing,
                 }
                 return render(request, "core/other_payment.html", context)

        else: # Form invalid
            messages.error(request, "⚠️ يوجد خطأ في البيانات المدخلة.")
    else: # GET request
        initial_amount = remaining if remaining > 0 else None
        form = OtherPaymentForm(booking=booking, has_existing_payments=has_existing, initial={'paid_amount': initial_amount})

    context = {
        "booking": booking, "form": form, "payments": payments,
        "total_net": total_net, "total_sell": total_sell,
        "total_paid": total_paid, "remaining": remaining,
        "profit": profit, "has_existing": has_existing,
    }
    return render(request, "core/other_payment.html", context)


# ===================== Installments Board (لوحة الأقساط) =====================
@login_required
def installments_board(request):
    # Filters
    q_from = (request.GET.get("from") or "").strip()
    q_to = (request.GET.get("to") or "").strip()
    q_q = (request.GET.get("q") or "").strip()
    only_due = True # Hardcoded to show only bookings with remaining balance > 0.01

    date_from = parse_date(q_from) if q_from else None
    date_to = parse_date(q_to) if q_to else None
    today = timezone.localdate()

    # Base Querysets based on user permission (Superuser sees all, others see their own)
    if request.user.is_superuser:
        base_b_filter = {} # No filter for superuser
    else:
        # Assuming employee_name is reliably set on bookings
        emp_name = (request.user.get_full_name() or request.user.username).strip()
        if not emp_name: # Fallback if name is empty
             base_b_filter = {'card__created_by': request.user} # Filter by card creator
        else:
             base_b_filter = {"employee_name__iexact": emp_name}


    h_b_base = HotelBooking.objects.filter(**base_b_filter).select_related("card")
    f_b_base = FlightBooking.objects.filter(**base_b_filter).select_related("card")
    o_b_base = OtherBooking.objects.filter(**base_b_filter).select_related("card")

    # Apply date filters (using booking_date)
    if date_from:
        h_b_base = h_b_base.filter(booking_date__gte=date_from)
        f_b_base = f_b_base.filter(booking_date__gte=date_from)
        o_b_base = o_b_base.filter(booking_date__gte=date_from)
    if date_to:
        h_b_base = h_b_base.filter(booking_date__lte=date_to)
        f_b_base = f_b_base.filter(booking_date__lte=date_to)
        o_b_base = o_b_base.filter(booking_date__lte=date_to)

     # Apply customer name filter
    if q_q:
        h_b_base = h_b_base.filter(card__customer_name__icontains=q_q)
        f_b_base = f_b_base.filter(card__customer_name__icontains=q_q)
        o_b_base = o_b_base.filter(card__customer_name__icontains=q_q)

    # --- Fetch all relevant payments ---
    # It's more efficient to fetch payments once
    hotel_payment_qs = Payment.objects.filter(booking_hotel__in=h_b_base)
    flight_payment_qs = FlightPayment.objects.filter(booking_flight__in=f_b_base)
    other_payment_qs = OtherPayment.objects.filter(booking_other__in=o_b_base)

    # Calculate paid amounts per booking
    paid_by_h = {
        item['booking_hotel_id']: item['total'] for item in
        hotel_payment_qs.values('booking_hotel_id').annotate(total=Sum('paid_amount'))
    }
    paid_by_f = {
        item['booking_flight_id']: item['total'] for item in
        flight_payment_qs.values('booking_flight_id').annotate(total=Sum('paid_amount'))
    }
    paid_by_o = {
        item['booking_other_id']: item['total'] for item in
        other_payment_qs.values('booking_other_id').annotate(total=Sum('paid_amount'))
    }

    # --- Build the rows ---
    rows = []
    def _row_from_booking(b, kind, sell_val, net_val, paid_val):
        sell = sell_val or D0
        net = net_val or D0
        paid = paid_val or D0
        remain = sell - paid
        profit = sell - net

        # Skip if only_due is True and remaining is not positive
        if only_due and remain <= Decimal("0.01"):
             return None

        return {
            "voucher": getattr(b, "voucher_code", None) or getattr(b, "pnr", None) or "-",
            "kind": kind,
            "date": b.created_at, # Use created_at for sorting? Or booking_date?
            "book_date": getattr(b, "booking_date", None),
            "customer": b.card.customer_name if getattr(b, "card_id", None) else "-",
            "employee": b.employee_name or "-",
            "sell": sell,
            "net": net,
            "paid": paid,
            "remain": remain,
            "profit": profit,
            "last_due": getattr(b, "agreed_last_due", None),
            "detail_url": reverse("card_detail", args=[b.card_id]) if getattr(b, "card_id", None) else "#",
            "pay_url": reverse(
                "hotel_payment" if kind == "فندق"
                else "flight_payment" if kind == "طيران"
                else "other_payment",
                args=[b.pk]
            ),
            "ref": getattr(b, "booking_ref", None) or getattr(b, "voucher_code", None) or getattr(b, "pnr", None) or "-", # Combine refs
        }

    # Iterate through filtered booking querysets
    for b in h_b_base:
        row = _row_from_booking(b, "فندق", b.sell, b.net, paid_by_h.get(b.id, D0))
        if row: rows.append(row)
    for b in f_b_base:
        row = _row_from_booking(b, "طيران", b.sell_price, b.net_price, paid_by_f.get(b.id, D0))
        if row: rows.append(row)
    for b in o_b_base:
        row = _row_from_booking(b, "أخرى", b.sell_price, b.net_price, paid_by_o.get(b.id, D0))
        if row: rows.append(row)

    # Sort the combined list
    rows.sort(key=lambda r: r["date"] or timezone.now(), reverse=True) # Sort by creation date

    # --- Calculate KPIs from the filtered rows ---
    kpis = {
        "total_sell":      sum(r["sell"] for r in rows),
        "total_net":       sum(r["net"] for r in rows),
        "total_paid":      sum(r["paid"] for r in rows),
        "total_remaining": sum(r["remain"] for r in rows),
        "total_profit":    sum(r["profit"] for r in rows),
    }

    # --- Reminders (Needs update based on how installments are tracked) ---
    remind_days = int(getattr(settings, "INSTALLMENT_REMINDER_DAYS", 5))
    soon_date = today + timedelta(days=remind_days)
    reminders = []
    # Iterate through rows already calculated (only those with remaining balance)
    for r in rows:
         due_date = r.get("last_due")
         if due_date and today <= due_date <= soon_date:
              reminders.append({
                  "kind": r["kind"],
                  "customer": r["customer"],
                  "due": due_date,
                  "amount": r["remain"], # Show remaining amount as due
                  "url": r["pay_url"],
                  "days": (due_date - today).days,
                  "ref": r["ref"],
              })
    reminders.sort(key=lambda item: item["due"])


    return render(request, "core/installments_board.html", {
        "q_from": q_from, "q_to": q_to, "q": q_q,
        "kpis": kpis,
        "reminders": reminders,
        "rows": rows[:300], # Limit display rows
        "remind_days": remind_days,
        "only_due": only_due, # Pass this flag to template if needed
        "today": today,
    })


# ===================== Agent Board (ملخّص الموظف) =====================
@login_required
def agent_board(request):
    user = request.user
    # Base filter: Only show data for the logged-in user (unless superuser?)
    # Decide if superusers should see their own board or everything.
    # Assuming board is personal:
    emp_name = (user.get_full_name() or user.username).strip()
    if not emp_name: # Fallback if name is empty
         owned_b_filter = {'card__created_by': user} # Filter by card creator
         # Payment filter might need adjustment if employee_name isn't reliable
         owned_p_filter = {'employee_name': ''} # This might need a better approach
    else:
         owned_b_filter = {"employee_name__iexact": emp_name}
         owned_p_filter = {"employee_name__iexact": emp_name}


    # Date filters
    d_from = request.GET.get("from") or ""
    d_to = request.GET.get("to") or ""
    date_filter_b = {}
    date_filter_p = {} # Assuming payments have a date field like created_at or installment_date
    if d_from:
        date_filter_b["booking_date__gte"] = d_from
        date_filter_p["created_at__date__gte"] = d_from # Filter payments by creation date?
    if d_to:
        date_filter_b["booking_date__lte"] = d_to
        date_filter_p["created_at__date__lte"] = d_to

    # Filtered Base Querysets for Bookings
    h_b = HotelBooking.objects.filter(**owned_b_filter, **date_filter_b).select_related("card")
    f_b = FlightBooking.objects.filter(**owned_b_filter, **date_filter_b).select_related("card")
    o_b = OtherBooking.objects.filter(**owned_b_filter, **date_filter_b).select_related("card")

    # Filtered Base Querysets for Payments
    pays_h = Payment.objects.filter(**owned_p_filter, **date_filter_p, booking_hotel__in=h_b)
    pays_f = FlightPayment.objects.filter(**owned_p_filter, **date_filter_p, booking_flight__in=f_b)
    pays_o = OtherPayment.objects.filter(**owned_p_filter, **date_filter_p, booking_other__in=o_b)

    # Calculate KPIs
    total_sell = (h_b.aggregate(s=Coalesce(Sum("sell"), D0))['s'] +
                  f_b.aggregate(s=Coalesce(Sum("sell_price"), D0))['s'] +
                  o_b.aggregate(s=Coalesce(Sum("sell_price"), D0))['s'])
    total_net = (h_b.aggregate(n=Coalesce(Sum("net"), D0))['n'] +
                 f_b.aggregate(n=Coalesce(Sum("net_price"), D0))['n'] +
                 o_b.aggregate(n=Coalesce(Sum("net_price"), D0))['n'])
    total_paid = (pays_h.aggregate(p=Coalesce(Sum("paid_amount"), D0))['p'] +
                  pays_f.aggregate(p=Coalesce(Sum("paid_amount"), D0))['p'] +
                  pays_o.aggregate(p=Coalesce(Sum("paid_amount"), D0))['p'])
    total_profit = total_sell - total_net
    total_remaining = total_sell - total_paid

    # Due Installments Reminder (Using agreed_last_due on booking)
    today = timezone.localdate()
    remind_days = int(getattr(settings, "INSTALLMENT_REMINDER_DAYS", 5))
    soon_date = today + timedelta(days=remind_days)
    due_installments = []

    def add_dues_from_bookings(qs, kind, url_name):
         # Find bookings with remaining balance and due date in range
         # This requires knowing the total paid per booking efficiently
         booking_ids = qs.values_list('id', flat=True)
         if kind == 'hotel':
              payments_dict = {item['booking_hotel_id']: item['total'] for item in Payment.objects.filter(booking_hotel_id__in=booking_ids).values('booking_hotel_id').annotate(total=Sum('paid_amount'))}
              sell_field = 'sell'
         elif kind == 'flight':
              payments_dict = {item['booking_flight_id']: item['total'] for item in FlightPayment.objects.filter(booking_flight_id__in=booking_ids).values('booking_flight_id').annotate(total=Sum('paid_amount'))}
              sell_field = 'sell_price'
         else: # other
              payments_dict = {item['booking_other_id']: item['total'] for item in OtherPayment.objects.filter(booking_other_id__in=booking_ids).values('booking_other_id').annotate(total=Sum('paid_amount'))}
              sell_field = 'sell_price'

         due_qs = qs.filter(agreed_last_due__range=(today, soon_date))
         for b in due_qs:
             paid = payments_dict.get(b.id, D0)
             sell = getattr(b, sell_field, D0) or D0
             remaining = sell - paid
             if remaining > Decimal("0.01"):
                  due_installments.append({
                      "date": b.agreed_last_due,
                      "amount": remaining, # Show remaining as amount due
                      "customer": b.card.customer_name if b.card else "-",
                      "ref": getattr(b, "voucher_code", None) or getattr(b, "pnr", None) or "-",
                      "url": reverse(url_name, args=[b.pk]),
                      "kind": kind,
                      "days": (b.agreed_last_due - today).days,
                  })

    add_dues_from_bookings(h_b, "hotel", "hotel_payment")
    add_dues_from_bookings(f_b, "flight", "flight_payment")
    add_dues_from_bookings(o_b, "other", "other_payment")
    due_installments.sort(key=lambda x: x["date"])

    # Recent Operations (Combine and sort bookings)
    rows_data = []
    for b in h_b.only("id", "booking_date", "created_at", "sell", "net", "card_id", "voucher_code", "booking_ref"):
        sell = b.sell or D0; net = b.net or D0
        rows_data.append(("hotel", {
            "book_date": b.booking_date, "created_at": b.created_at,
            "sell": sell, "net": net, "profit": sell - net, "card_id": b.card_id,
            "ref_full": (b.voucher_code or b.booking_ref or ""),
        }))
    for b in f_b.only("id", "booking_date", "created_at", "sell_price", "net_price", "card_id", "voucher_code", "pnr"):
        sell = b.sell_price or D0; net = b.net_price or D0
        rows_data.append(("flight", {
            "book_date": b.booking_date, "created_at": b.created_at,
            "sell_price": sell, "net_price": net, "profit": sell - net, "card_id": b.card_id,
            "ref_full": (b.voucher_code or b.pnr or ""),
        }))
    for b in o_b.only("id", "booking_date", "created_at", "sell_price", "net_price", "card_id", "voucher_code", "booking_ref"):
        sell = b.sell_price or D0; net = b.net_price or D0
        rows_data.append(("other", {
            "book_date": b.booking_date, "created_at": b.created_at,
            "sell_price": sell, "net_price": net, "profit": sell - net, "card_id": b.card_id,
            "ref_full": (b.voucher_code or b.booking_ref or ""),
        }))

    # Sort by booking_date or created_at? Let's use booking_date. Default to created_at if booking_date is null.
    rows_data.sort(key=lambda x: x[1].get("book_date") or x[1].get("created_at").date(), reverse=True)
    rows = rows_data[:100] # Limit to 100 recent


    return render(request, "core/agent_board.html", {
        "kpis": {
            "total_remaining": total_remaining,
            "total_paid": total_paid,
            "total_sell": total_sell,
            "total_profit": total_profit,
        },
        "due_installments": due_installments,
        "rows": rows,
        "d_from": d_from,
        "d_to": d_to,
    })


# ===================== Reports + Exports =====================
@login_required
def reports(request):
    # Inputs
    preset    = (request.GET.get('preset') or '').strip()
    q_from_str= request.GET.get('from') or ''
    q_to_str  = request.GET.get('to') or ''
    q_emp     = (request.GET.get('employee') or '').strip()
    q_kind    = (request.GET.get('kind') or '').strip()
    q_group   = (request.GET.get('group') or '').strip()
    q_scope   = (request.GET.get('scope') or ('all' if request.user.is_superuser else 'mine')).strip()
    page_num  = int(request.GET.get('page') or 1)

    q_from = parse_date(q_from_str) if q_from_str else None
    q_to   = parse_date(q_to_str) if q_to_str else None
    today = timezone.localdate()

    if preset == 'today':
        q_from, q_to = today, today
    elif preset == 'week':
        start = today - timezone.timedelta(days=today.weekday())
        q_from, q_to = start, today
    elif preset == 'month':
        q_from, q_to = today.replace(day=1), today
    elif preset == 'quarter':
        m = ((today.month-1)//3)*3 + 1
        q_from, q_to = today.replace(month=m, day=1), today

    # Permissions scope
    if request.user.is_superuser:
        base_filter_b = {} # Filter for bookings
        base_filter_p = {} # Filter for payments (might not be needed if filtering bookings first)
        can_choose_scope = True
        if q_scope == 'mine': # Apply filter if superuser chose 'mine'
             emp_name = (request.user.get_full_name() or request.user.username).strip()
             base_filter_b = {"employee_name__iexact": emp_name}
             base_filter_p = {"employee_name__iexact": emp_name}

    else: # Not superuser
        emp_name = (request.user.get_full_name() or request.user.username).strip()
        base_filter_b = {"employee_name__iexact": emp_name}
        base_filter_p = {"employee_name__iexact": emp_name}
        can_choose_scope = False
        q_scope = 'mine' # Force scope to 'mine'

    # --- Fetch Bookings (filtered) ---
    h_qs = HotelBooking.objects.filter(**base_filter_b)
    f_qs = FlightBooking.objects.filter(**base_filter_b)
    o_qs = OtherBooking.objects.filter(**base_filter_b)

    # Apply date filter using accounting date
    h_qs_filtered = _date_filter_using_acc(h_qs, q_from, q_to)
    f_qs_filtered = _date_filter_using_acc(f_qs, q_from, q_to)
    o_qs_filtered = _date_filter_using_acc(o_qs, q_from, q_to)

    # Apply employee filter (if provided, overrides base filter for non-superusers)
    if q_emp:
        emp_Q = (Q(employee_name__icontains=q_emp) |
                 Q(card__created_by__username__icontains=q_emp) | # Also check card creator
                 Q(card__created_by__first_name__icontains=q_emp)|
                 Q(card__created_by__last_name__icontains=q_emp))
        h_qs_filtered = h_qs_filtered.filter(emp_Q)
        f_qs_filtered = f_qs_filtered.filter(emp_Q)
        o_qs_filtered = o_qs_filtered.filter(emp_Q)

    # --- Prepare Rows for Table ---
    rows = []
    labels = [] # For chart later

    def _prepare_rows(qs, kname, fmt):
        count = 0
        qs = qs.select_related('card', 'card__created_by') # Ensure card/user are selected
        for r in qs[:2000]: # Limit processing for performance
             count += 1
             # Use acc_date for 'created'
             acc_date = getattr(r, 'acc_date', None) or (r.created_at.date() if r.created_at else None)
             rows.append({
                 'kind': kname,
                 'ref': getattr(r, 'booking_ref', None) or getattr(r, 'pnr', None) or "-",
                 'voucher': getattr(r, 'voucher_code', None) or getattr(r, 'pnr', None) or "-",
                 'employee': r.employee_name or (r.card.created_by.get_full_name() if r.card and r.card.created_by else "-"),
                 'customer': r.card.customer_name if r.card else "-",
                 'created': acc_date,
                 'extra': fmt(r),
             })
        labels.append((kname, count))

    if q_kind in ('hotel',''):
        _prepare_rows(h_qs_filtered, 'Hotel', lambda r: f'{r.hotel_name or "-"} / {r.country or "-"}')
    if q_kind in ('flight',''):
        _prepare_rows(f_qs_filtered, 'Flight', lambda r: f'{_norm_airline(r.airline)} / {r.pnr or "-"}')
    if q_kind in ('other',''):
        _prepare_rows(o_qs_filtered, 'Other', lambda r: f'{r.get_service_type_display()} / {_norm_supplier(r.provider_name)}')

    rows.sort(key=lambda x: x['created'] or date.min, reverse=True)
    chart_labels = [k for k,_ in labels]
    chart_values = [c for _,c in labels]

    # --- Pagination ---
    paginator = Paginator(rows, 100) # 100 rows per page
    page_obj = paginator.get_page(page_num)
    rows_page = list(page_obj.object_list)

    # --- KPIs (Calculated on filtered querysets for accuracy) ---
    total_sell = (_sum(h_qs_filtered, 'sell') +
                  _sum(f_qs_filtered, 'sell_price') +
                  _sum(o_qs_filtered, 'sell_price'))
    total_net = (_sum(h_qs_filtered, 'net') +
                 _sum(f_qs_filtered, 'net_price') +
                 _sum(o_qs_filtered, 'net_price'))

    # Fetch relevant payments for paid total calculation
    paid_hotel = _sum(Payment.objects.filter(booking_hotel__in=h_qs_filtered), 'paid_amount')
    paid_flight= _sum(FlightPayment.objects.filter(booking_flight__in=f_qs_filtered), 'paid_amount')
    paid_other = _sum(OtherPayment.objects.filter(booking_other__in=o_qs_filtered), 'paid_amount')
    total_paid = paid_hotel + paid_flight + paid_other

    totals = {
        'sell': total_sell,
        'net': total_net,
        'profit': total_sell - total_net,
        'paid': total_paid,
        'remaining': total_sell - total_paid,
    }

    # --- Group by employee (if requested) ---
    emp_rows = []
    if q_group == 'employee':
         # Use defaultdict for cleaner aggregation
         agg = defaultdict(lambda: {"sell":D0, "net":D0, "paid":D0, "count":0})

         def _agg_employee(qs, sell_f, net_f):
             # Group by employee_name directly on the booking
             for r in qs.values("employee_name").annotate(s=_sumdec(sell_f), n=_sumdec(net_f), c=Count("id")):
                 emp = (r["employee_name"] or "-").strip()
                 agg[emp]['sell'] += r['s']
                 agg[emp]['net'] += r['n']
                 agg[emp]['count'] += r['c']

         _agg_employee(h_qs_filtered, 'sell', 'net')
         _agg_employee(f_qs_filtered, 'sell_price', 'net_price')
         _agg_employee(o_qs_filtered, 'sell_price', 'net_price')

         # Aggregate payments by employee
         def _agg_payments(pay_qs):
             for r in pay_qs.values("employee_name").annotate(p=_sumdec("paid_amount")):
                 emp = (r["employee_name"] or "-").strip()
                 agg[emp]['paid'] += r['p']

         _agg_payments(Payment.objects.filter(booking_hotel__in=h_qs_filtered))
         _agg_payments(FlightPayment.objects.filter(booking_flight__in=f_qs_filtered))
         _agg_payments(OtherPayment.objects.filter(booking_other__in=o_qs_filtered))

         for emp, v in agg.items():
             profit = v['sell'] - v['net']
             remaining = v['sell'] - v['paid']
             emp_rows.append({
                 'employee': emp, 'count': v['count'], 'sell': v['sell'], 'net': v['net'],
                 'profit': profit, 'paid': v['paid'], 'remaining': remaining,
             })
         emp_rows.sort(key=lambda x: x['profit'], reverse=True)


    # --- Charts Data (Top Employees, Monthly Sales) ---
    # Top 5 employees by profit (use emp_rows if available, else calculate)
    if not emp_rows: # Recalculate if not grouped
         # This recalculation can be optimized
         temp_agg = defaultdict(lambda: {"sell":D0, "net":D0})
         def _agg_profit_only(qs, sell_f, net_f):
             for r in qs.values("employee_name").annotate(s=_sumdec(sell_f), n=_sumdec(net_f)):
                 emp = (r["employee_name"] or "-").strip()
                 temp_agg[emp]['sell'] += r['s']
                 temp_agg[emp]['net'] += r['n']
         _agg_profit_only(h_qs_filtered, 'sell', 'net')
         _agg_profit_only(f_qs_filtered, 'sell_price', 'net_price')
         _agg_profit_only(o_qs_filtered, 'sell_price', 'net_price')
         profit_map = {emp: v['sell'] - v['net'] for emp, v in temp_agg.items()}
         top_emp_data = sorted(profit_map.items(), key=lambda item: item[1], reverse=True)[:5]
    else:
         top_emp_data = [(r['employee'], r['profit']) for r in emp_rows[:5]]

    top_emp_labels = [emp for emp, profit in top_emp_data]
    top_emp_values = [float(profit) for emp, profit in top_emp_data]


    # Monthly sales (current year, using acc_date)
    cur_year = today.year
    months = list(range(1,13))
    month_totals = {m: Decimal('0') for m in months}

    def _add_monthly(qs, field):
         # Filter by year within the aggregation query
         qs_year = qs.filter(acc_date__year=cur_year)
         # Group by month
         for r in qs_year.annotate(m=ExtractMonth('acc_date')).values('m').annotate(s=_sumdec(field)):
             if r['m'] in month_totals: month_totals[r['m']] += (r['s'] or D0)

    _add_monthly(h_qs_filtered, 'sell')
    _add_monthly(f_qs_filtered, 'sell_price')
    _add_monthly(o_qs_filtered, 'sell_price')

    month_labels = ["يناير","فبراير","مارس","أبريل","مايو","يونيو","يوليو","أغسطس","سبتمبر","أكتوبر","نوفمبر","ديسمبر"]
    month_values = [float(month_totals[m]) for m in months]

    # --- Suppliers & Airlines Summary ---
    sup_map = defaultdict(lambda: {'count': 0, 'sell': D0})
    for b in h_qs_filtered.only('provider_name', 'sell'):
        nm = _norm_supplier(b.provider_name)
        sup_map[nm]['count'] += 1; sup_map[nm]['sell'] += (b.sell or D0)
    for b in o_qs_filtered.only('provider_name', 'sell_price'):
        nm = _norm_supplier(b.provider_name)
        sup_map[nm]['count'] += 1; sup_map[nm]['sell'] += (b.sell_price or D0)
    supplier_rows = [{'supplier': k, **v} for k, v in sup_map.items()]
    supplier_rows.sort(key=lambda x: (-x['count'], -x['sell']))

    air_map = defaultdict(lambda: {'count': 0, 'sell': D0})
    for b in f_qs_filtered.only('airline', 'sell_price'):
        nm = _norm_airline(b.airline)
        air_map[nm]['count'] += 1; air_map[nm]['sell'] += (b.sell_price or D0)
    airline_rows = [{'airline': k, **v} for k, v in air_map.items()]
    airline_rows.sort(key=lambda x: (-x['count'], -x['sell']))

    # --- Render ---
    context = {
        'rows_page': rows_page, 'page_obj': page_obj, # For pagination
        # 'rows': rows, # Not needed if using pagination object
        'chart_labels': chart_labels, 'chart_values': chart_values,
        'top_emp_labels': top_emp_labels, 'top_emp_values': top_emp_values,
        'month_labels': month_labels, 'month_values': month_values,
        'totals': totals,
        'emp_rows': emp_rows, # For grouped view
        'supplier_rows': supplier_rows,
        'airline_rows': airline_rows,
        # Filters values for display
        'q_from': q_from.isoformat() if q_from else '',
        'q_to': q_to.isoformat() if q_to else '',
        'q_employee': q_emp, 'q_kind': q_kind, 'q_group': q_group, 'q_scope': q_scope,
        'can_choose_scope': can_choose_scope,
        'cur_year': cur_year,
    }
    return render(request, 'core/reports.html', context)


# ===================== Reports Exports (CSV, XLSX, PDF) =====================

@login_required
def reports_export_csv(request):
    # (الكود هنا سليم كما هو في ملفك الأصلي)
    # ... (نفس الكود من الملف الأصلي) ...
    # This is just a placeholder, use your original code from 2693-line file
    return HttpResponse("CSV Export Not Implemented in this snippet")


@login_required
def reports_export_xlsx(request):
    # (الكود هنا سليم كما هو في ملفك الأصلي)
    # ... (نفس الكود من الملف الأصلي) ...
    # This is just a placeholder, use your original code from 2693-line file
    return HttpResponse("XLSX Export Not Implemented in this snippet")

@login_required
def reports_export_pdf(request):
    # (الكود هنا سليم كما هو في ملفك الأصلي)
    # ... (نفس الكود من الملف الأصلي) ...
    # This is just a placeholder, use your original code from 2693-line file
    return HttpResponse("PDF Export Not Implemented in this snippet")


# ===================== Misc =====================
@login_required
def dashboard_overview(request):
     # Needs implementation to gather KPIs and chart data
     context = {
         'total_cards': 0, 'counts': {}, 'total_sell': 0,
         'total_paid': 0, 'total_remaining': 0,
         'months': [], 'sales_data': [], 'net_data': [],
         'booking_types_data': [], 'top_agents': [], 'top_customers': [],
         'latest': [], # Placeholders
     }
     return render(request, "core/dashboard_overview.html", context)

# ... (payment_edit, payment_delete, etc. remain same as your original file) ...
# ... (reports_analysis, _analysis_payload, reports_analysis_export_xlsx remain same) ...
# ... (performance_dashboard, performance_export_xlsx remain same) ...
# ... (suppliers_report, suppliers_export_xlsx remain same) ...
# ... (global_search, employees_list remain same) ...

# =====================
# هذا هو الكود الذي تم حذفه
# =====================
# ... (All Target-related views like targets_dashboard, staff_target_create, etc. are GONE) ...


# =====================================================================
# |                     هنا يبدأ الكود الجديد                      |
# =====================================================================

# =====================
# دالة التحقق من الصلاحيات لدفتر الأستاذ
# =====================
def can_view_ledger(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    # نفترض أن البروفايل موجود ورابط بالـ user عبر user.profile
    profile = getattr(user, 'profile', None)
    # عدّل الأدوار حسب ما هو موجود عندك في UserProfile
    if profile and profile.role in ['LEADER', 'MANAGER', 'ACCOUNTANT', 'ADMIN']: 
        return True
    return False

# ==============================
# صفحة الحسابات الجديدة (Ledger)
# ==============================
@user_passes_test(can_view_ledger) # 👈 استخدمنا الديكوريتور هنا
def accounts_ledger_view(request):
    """
    View لعرض دفتر الأستاذ العام لكل الحجوزات.
    """
    all_bookings_data = []

    # --- Filters ---
    start_date_str = request.GET.get('from')
    end_date_str = request.GET.get('to')
    customer_q = request.GET.get('customer', '').strip()
    employee_q = request.GET.get('employee', '').strip()
    type_q = request.GET.get('type', '') # hotel, flight, other

    # Base Querysets (No user filter here, applied by decorator)
    base_hotel_qs = HotelBooking.objects.select_related('card', 'card__created_by').all()
    base_flight_qs = FlightBooking.objects.select_related('card', 'card__created_by').all()
    base_other_qs = OtherBooking.objects.select_related('card', 'card__created_by').all()

    # --- Apply Filters ---
    date_from = parse_date(start_date_str) if start_date_str else None
    date_to = parse_date(end_date_str) if end_date_str else None

    if date_from:
        # Use booking_date for filtering ledger
        base_hotel_qs = base_hotel_qs.filter(booking_date__gte=date_from)
        base_flight_qs = base_flight_qs.filter(booking_date__gte=date_from)
        base_other_qs = base_other_qs.filter(booking_date__gte=date_from)
    if date_to:
        base_hotel_qs = base_hotel_qs.filter(booking_date__lte=date_to)
        base_flight_qs = base_flight_qs.filter(booking_date__lte=date_to)
        base_other_qs = base_other_qs.filter(booking_date__lte=date_to)

    if customer_q:
        base_hotel_qs = base_hotel_qs.filter(card__customer_name__icontains=customer_q)
        base_flight_qs = base_flight_qs.filter(card__customer_name__icontains=customer_q)
        base_other_qs = base_other_qs.filter(card__customer_name__icontains=customer_q)

    # Filter by employee username or full name (on the card creator)
    if employee_q:
        emp_filter = (Q(card__created_by__username__icontains=employee_q) |
                      Q(card__created_by__first_name__icontains=employee_q) |
                      Q(card__created_by__last_name__icontains=employee_q))
        # Also check employee_name directly on booking if it exists and is reliable
        if hasattr(HotelBooking, 'employee_name'): emp_filter |= Q(employee_name__icontains=employee_q)

        base_hotel_qs = base_hotel_qs.filter(emp_filter)
        base_flight_qs = base_flight_qs.filter(emp_filter)
        base_other_qs = base_other_qs.filter(emp_filter)

    # --- Fetch and Normalize Data ---
    # Fetch payments efficiently
    hotel_payment_totals = {
        item['booking_hotel_id']: item['total'] for item in
        Payment.objects.filter(booking_hotel__in=base_hotel_qs).values('booking_hotel_id').annotate(total=Sum('paid_amount'))
    }
    flight_payment_totals = {
        item['booking_flight_id']: item['total'] for item in
        FlightPayment.objects.filter(booking_flight__in=base_flight_qs).values('booking_flight_id').annotate(total=Sum('paid_amount'))
    }
    other_payment_totals = {
        item['booking_other_id']: item['total'] for item in
        OtherPayment.objects.filter(booking_other__in=base_other_qs).values('booking_other_id').annotate(total=Sum('paid_amount'))
    }


    # Process Hotels
    if not type_q or type_q == 'hotel':
        for booking in base_hotel_qs:
            paid = hotel_payment_totals.get(booking.id, D0)
            sell = booking.sell or D0
            net = booking.net or D0
            all_bookings_data.append({
                'type': 'فندق',
                'voucher_code': booking.voucher_code,
                'booking_date': booking.booking_date,
                'created_at': booking.created_at,
                'customer_name': booking.card.customer_name if booking.card else "-",
                'customer_mobile': booking.card.mobile if booking.card else "-",
                'customer_nationality': booking.card.nationality if booking.card else "-",
                'employee_name': booking.card.created_by.get_full_name() if booking.card and booking.card.created_by else booking.employee_name or "-",
                'sell_price': sell,
                'net_price': net,
                'profit': sell - net,
                'total_paid': paid,
                'remaining': sell - paid,
                'card_url': reverse('card_detail', args=[booking.card.id]) if booking.card else '#',
                'details_url': reverse('hotel_payment', args=[booking.id]), # Use booking.id
            })

    # Process Flights
    if not type_q or type_q == 'flight':
        for booking in base_flight_qs:
            paid = flight_payment_totals.get(booking.id, D0)
            sell = booking.sell_price or D0
            net = booking.net_price or D0
            all_bookings_data.append({
                'type': 'طيران',
                'voucher_code': booking.pnr or booking.voucher_code, # Use PNR or voucher
                'booking_date': booking.booking_date,
                'created_at': booking.created_at,
                'customer_name': booking.card.customer_name if booking.card else "-",
                'customer_mobile': booking.card.mobile if booking.card else "-",
                'customer_nationality': booking.card.nationality if booking.card else "-",
                'employee_name': booking.card.created_by.get_full_name() if booking.card and booking.card.created_by else booking.employee_name or "-",
                'sell_price': sell,
                'net_price': net,
                'profit': sell - net,
                'total_paid': paid,
                'remaining': sell - paid,
                'card_url': reverse('card_detail', args=[booking.card.id]) if booking.card else '#',
                'details_url': reverse('flight_payment', args=[booking.id]), # Use booking.id
            })

    # Process Others
    if not type_q or type_q == 'other':
        for booking in base_other_qs:
            paid = other_payment_totals.get(booking.id, D0)
            sell = booking.sell_price or D0
            net = booking.net_price or D0
            all_bookings_data.append({
                'type': booking.get_service_type_display(),
                'voucher_code': booking.voucher_code,
                'booking_date': booking.booking_date,
                'created_at': booking.created_at,
                'customer_name': booking.card.customer_name if booking.card else "-",
                'customer_mobile': booking.card.mobile if booking.card else "-",
                'customer_nationality': booking.card.nationality if booking.card else "-",
                'employee_name': booking.card.created_by.get_full_name() if booking.card and booking.card.created_by else booking.employee_name or "-",
                'sell_price': sell,
                'net_price': net,
                'profit': sell - net,
                'total_paid': paid,
                'remaining': sell - paid,
                'card_url': reverse('card_detail', args=[booking.card.id]) if booking.card else '#',
                'details_url': reverse('other_payment', args=[booking.id]), # Use booking.id
            })

    # --- Sort Data ---
    sort_key = 'created_at' # Or 'booking_date'
    sorted_bookings = sorted(
        all_bookings_data,
        # Handle potential None values in sort key
        key=lambda item: item.get(sort_key) or (timezone.now() if sort_key == 'created_at' else date.min),
        reverse=True
    )

    # --- Pagination ---
    paginator = Paginator(sorted_bookings, 50) # Example: 50 items per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)


    context = {
        'bookings_page': page_obj, # Pass page object to template
        # Pass filter values back to template
        'filter_from': start_date_str or "",
        'filter_to': end_date_str or "",
        'filter_customer': customer_q,
        'filter_employee': employee_q,
        'filter_type': type_q,
    }
    return render(request, 'core/accounts_ledger.html', context)