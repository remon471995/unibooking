# core/views.py
import io
import base64
import csv
import re
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal
from datetime import datetime, timedelta
from django.contrib.auth.decorators import permission_required
from django.contrib.contenttypes.models import ContentType

from .forms import BookingAmendmentForm
from .models import BookingAmendment
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal
from django.db.models import Sum

from .forms import PaymentAdjustmentForm  # فورم التسوية


# Django ORM / DB funcs
from django.db.models import (
    OuterRef, Subquery, Sum, Count, Q, DecimalField, F, Value as V, Max
)
from django.db.models.functions import Coalesce, TruncDate, ExtractMonth, TruncMonth

# Django shortcuts & utils
from django.views.decorators.http import require_POST, require_http_methods
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import format_html
from django.forms import inlineformset_factory
from django.core.paginator import Paginator
from django.conf import settings
from django.db import transaction
from django.shortcuts import render, get_object_or_404
from core.models import Department

# Excel
try:
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter
except Exception:
    Workbook = None
    def get_column_letter(i): return "A"

# PDF (ReportLab)
try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    HAS_REPORTLAB = True
except Exception:
    HAS_REPORTLAB = False

# External libs
import qrcode
from qrcode.image.pil import PilImage
from weasyprint import HTML

# Models & Forms
from .models import (
    UniBookingCard, HotelBooking, FlightBooking, OtherBooking,
    Payment, FlightPayment, OtherPayment, Room, Notification,
    TargetCycle, StaffTarget, LeaderTarget
)
from .forms import (
    UniBookingCardForm, HotelBookingForm, PaymentForm,
    FlightBookingForm, FlightPaymentForm, RoomForm,
    OtherBookingForm, OtherPaymentForm,
    TargetCycleForm, StaffTargetForm, LeaderTargetForm, BookingAdjustmentForm
)
from core.services.targets import (
    employee_achieved_profit, leader_achieved_profit, commission_rate_and_amount
)

User = get_user_model()

# ===================== Helpers عامة =====================

D0 = Decimal("0.00")

def _sumdec(expr):
    return Coalesce(Sum(expr), D0, output_field=DecimalField(max_digits=14, decimal_places=2))

def _count(expr="id"):
    return Coalesce(Count(expr), 0)

def _build_qr_data_url(text: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=4, border=1)
    qr.add_data(text)
    qr.make(fit=True)
    img: PilImage = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"

def _render_pdf_from_template(template_name: str, context: dict, request) -> bytes:
    html_string = get_template(template_name).render(context)
    base_url = request.build_absolute_uri('/')
    return HTML(string=html_string, base_url=base_url).write_pdf()

def _cards_base_qs(request):
    return UniBookingCard.objects.all()

def _latest_emp_subquery(model, fk_name):
    return Subquery(
        model.objects.filter(**{fk_name: OuterRef('pk')})
        .order_by('-created_at').values('employee_name')[:1]
    )

# تاريخ محاسبي موحّد لكل الحجوزات
def _with_acc_date(qs):
    # acc_date = accounting_date -> booking_date -> TruncDate(created_at)
    return qs.annotate(
        acc_date=Coalesce('accounting_date', 'booking_date', TruncDate('created_at'))
    )

def _date_filter_using_acc(qs, date_from, date_to):
    qs = _with_acc_date(qs)
    if date_from:
        qs = qs.filter(acc_date__gte=date_from)
    if date_to:
        qs = qs.filter(acc_date__lte=date_to)
    return qs

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


# ===================== Notifications =====================

@login_required
def notifications_list(request):
    status = (request.GET.get("status") or "all").strip()   # all | unread | read
    page   = int(request.GET.get("page") or 1)

    # الصلاحيات
    if request.user.is_superuser:
        base = Q(to_superusers=True) | Q(to_user=request.user)
    else:
        base = Q(to_user=request.user)

    qs = Notification.objects.filter(base).order_by('-created_at')

    # فلترة حسب الحالة
    if status == "unread":
        qs = qs.filter(is_read=False)
    elif status == "read":
        qs = qs.filter(is_read=True)

    # أرقام ملخصة
    counts = {
        "total": Notification.objects.filter(base).count(),
        "unread": Notification.objects.filter(base, is_read=False).count(),
        "read": Notification.objects.filter(base, is_read=True).count(),
    }

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(page)

    return render(request, 'core/notifications.html', {
        'page_obj': page_obj,
        'rows': list(page_obj.object_list),
        'status': status,
        'counts': counts,
    })

@login_required
def notification_mark_read(request, pk):
    n = get_object_or_404(Notification, pk=pk)
    if request.user.is_superuser or n.to_user_id == request.user.id:
        n.is_read = True
        n.save(update_fields=['is_read'])
        messages.success(request, "تم تمييز التنبيه كمقروء.")
    return redirect(n.target_url or 'notifications_list')


# ===================== Dashboard / Cards =====================

@login_required
def dashboard(request):
    qs = _cards_base_qs(request)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(customer_name__icontains=q) |
            Q(ub_code__icontains=q) |
            Q(mobile__icontains=q)
        )
    paginator = Paginator(qs.order_by("-created_at"), 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "core/dashboard.html", {"cards": page_obj, "q": q})

@login_required
def card_create(request):
    if request.method == 'POST':
        form = UniBookingCardForm(request.POST)
        if form.is_valid():
            card = form.save(commit=False)
            card.created_by = request.user
            card.save()
            messages.success(request, "تم إنشاء كارت العميل.")
            return redirect('card_detail', pk=card.pk)
        else:
            errs = [f"{f}: {', '.join(e)}" for f, e in form.errors.items()]
            messages.error(request, format_html("تحقق من المدخلات: {}", "; ".join(errs)))
    else:
        form = UniBookingCardForm()
    return render(request, 'core/card_form.html', {'form': form})

@login_required
def card_detail(request, pk):
    card = get_object_or_404(UniBookingCard, pk=pk)
    hotel_bookings  = HotelBooking.objects.filter(card=card)
    flight_bookings = FlightBooking.objects.filter(card=card)
    other_bookings  = OtherBooking.objects.filter(card=card)

    totals = {
        "total_net": (
            sum(h.net or 0 for h in hotel_bookings) +
            sum(f.net_price or 0 for f in flight_bookings) +
            sum(o.net_price or 0 for o in other_bookings)
        ),
        "total_sell": (
            sum(h.sell or 0 for h in hotel_bookings) +
            sum(f.sell_price or 0 for f in flight_bookings) +
            sum(o.sell_price or 0 for o in other_bookings)
        ),
        "total_paid": (
            sum(h.total_paid or 0 for h in hotel_bookings) +
            sum(f.total_paid or 0 for f in flight_bookings) +
            sum(o.total_paid or 0 for o in other_bookings)
        ),
    }
    totals["total_profit"]    = totals["total_sell"] - totals["total_net"]
    totals["total_remaining"] = totals["total_sell"] - totals["total_paid"]

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
    qs = _cards_base_qs(request)
    if ids:
        qs = qs.filter(id__in=ids)
    qs = qs.annotate(
        hotels_count=Count('hotels', distinct=True),
        flights_count=Count('flights', distinct=True),
        others_count=Count('others', distinct=True),
    )

    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="cards_export.csv"'
    writer = csv.writer(resp)
    writer.writerow([
        'ID','UB Code','Customer','Mobile','Nationality','Country',
        'Hotels','Flights','Created At'
    ])
    for c in qs:
        writer.writerow([
            c.id, c.ub_code, c.customer_name, c.mobile or '',
            c.nationality or '', c.country or '',
            c.hotels_count, c.flights_count,
            c.created_at.isoformat() if c.created_at else ''
        ])
    return resp

@login_required
def cards_bulk_delete(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Invalid method'}, status=405)

    ids = request.POST.getlist('ids[]') or request.POST.getlist('ids')
    if not ids:
        return JsonResponse({'ok': False, 'error': 'No IDs'}, status=400)

    qs = _cards_base_qs(request).filter(id__in=ids)
    count = qs.count()
    if not count:
        return JsonResponse({'ok': False, 'error': 'No cards found or not permitted'}, status=404)

    qs.delete()
    return JsonResponse({'ok': True, 'deleted': count})


# ===================== Hotel =====================

@login_required
def hotel_create(request, card_pk):
    card = get_object_or_404(UniBookingCard, pk=card_pk)
    if not request.user.is_superuser and card.created_by != request.user:
        messages.error(request, "غير مسموح.")
        return redirect('dashboard')

    RoomFormSet = inlineformset_factory(
        HotelBooking, Room, form=RoomForm,
        extra=1, max_num=5, can_delete=False,
    )

    if request.method == 'POST':
        form = HotelBookingForm(request.POST)
        room_formset = RoomFormSet(request.POST, prefix='rooms')
        if form.is_valid() and room_formset.is_valid():
            hb = form.save(commit=False)
            hb.card = card
            hb.employee_name = request.user.get_full_name() or request.user.username
            if hb.checkin and hb.checkout and hb.checkout > hb.checkin:
                hb.nights = (hb.checkout - hb.checkin).days
            hb.save()
            room_formset.instance = hb
            room_formset.save()
            messages.success(request, f"تم حفظ حجز الفندق. فوّتشر: {hb.voucher_code}")
            return redirect('hotel_payment', booking_pk=hb.pk)
        else:
            if not form.is_valid():
                messages.error(request, "يرجى التحقق من بيانات الحجز الأساسية.")
            if not room_formset.is_valid():
                messages.error(request, "يرجى التحقق من بيانات أسماء النزلاء في الغرف.")
    else:
        form = HotelBookingForm()
        room_formset = RoomFormSet(prefix='rooms')

    return render(request, 'core/hotel_form.html', {
        'card': card, 'form': form, 'room_formset': room_formset
    })

@login_required
def hotel_voucher(request, booking_pk):
    booking = get_object_or_404(HotelBooking, pk=booking_pk)
    qr_data_url = _build_qr_data_url(
        request.build_absolute_uri(reverse('hotel_voucher', args=[booking.pk]))
    )
    rooms = booking.rooms.all()
    return render(request, 'core/voucher.html', {
        'booking': booking,
        'today': timezone.localdate(),
        'nights': booking.nights,
        'qr_data_url': qr_data_url,
        'rooms': rooms,
    })

@login_required
def hotel_voucher_pdf(request, booking_pk):
    booking = get_object_or_404(HotelBooking, pk=booking_pk)
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
    pdf_bytes = _render_pdf_from_template('core/voucher_pdf.html', context, request)
    if pdf_bytes is None:
        return HttpResponse("PDF render error", status=500)
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="Voucher_{booking.voucher_code}.pdf"'
    return resp


# ===================== إدارة دفع الفنادق =====================

@login_required
def hotel_payment(request, booking_pk):
    booking = get_object_or_404(HotelBooking, pk=booking_pk)
    payments = booking.payments.order_by("-created_at")
    has_existing = payments.exists()

    total_paid = payments.aggregate(
        total=Coalesce(
            Sum("paid_amount", output_field=DecimalField(max_digits=12, decimal_places=2)),
            V(0, output_field=DecimalField(max_digits=12, decimal_places=2))
        )
    )["total"] or Decimal("0.00")
    total_sell = booking.sell or Decimal("0.00")
    total_net  = booking.net  or Decimal("0.00")
    remaining  = total_sell - total_paid
    profit     = total_sell - total_net
    is_fully_paid = remaining <= Decimal("0.01")

    if request.method == "POST":
        pay_form = PaymentForm(request.POST, request.FILES,
                               booking=booking, has_existing_payments=has_existing)

        if pay_form.is_valid():
            cd = pay_form.cleaned_data
            paid_amount = cd.get("paid_amount") or Decimal("0")
            sell_price  = (cd.get("sell_price") if not has_existing else booking.sell) or Decimal("0")
            net_price   = (cd.get("net_price")  if not has_existing else booking.net)  or Decimal("0")

            if paid_amount < 0:
                pay_form.add_error("paid_amount", "المبلغ المدفوع يجب أن يكون صفراً أو قيمة موجبة.")
            if not has_existing:
                if not cd.get("invoice_file"):
                    pay_form.add_error("invoice_file", "ملف الفاتورة مطلوب عند أول دفعة.")
                if not cd.get("voucher_original"):
                    pay_form.add_error("voucher_original", "الفاوتشر الأصلي مطلوب عند أول دفعة.")

            method = cd.get("method")
            if method == "link" and not cd.get("payment_link"):
                pay_form.add_error("payment_link", "رابط السداد مطلوب لطريقة الدفع (Link).")
            if method in ("bank", "cash") and not cd.get("bank_file"):
                pay_form.add_error("bank_file", "مطلوب رفع إيصال للـ Bank/Cash.")
            if paid_amount > sell_price:
                pay_form.add_error("paid_amount", "المبلغ المدفوع لا يمكن أن يتجاوز سعر البيع.")
            if not has_existing and paid_amount < sell_price and not cd.get("installment_date"):
                pay_form.add_error("installment_date", "مطلوب تحديد آخر ميعاد للسداد عند أول دفعة غير كاملة.")

            if pay_form.errors:
                messages.error(request, "⚠️ صحح الأخطاء ثم حاول مرة أخرى.")
                return render(request, "core/hotel_payment.html", {
                    "booking": booking, "form": pay_form, "payments": payments,
                    "remaining": remaining, "total_paid": total_paid,
                    "total_sell": total_sell, "total_net": total_net,
                    "profit": profit, "has_existing": has_existing,
                    "is_fully_paid": is_fully_paid,
                })

            p = pay_form.save(commit=False)
            p.booking_hotel = booking
            p.employee_name = request.user.get_full_name() or request.user.username

            if not has_existing:
                booking.net  = net_price
                booking.sell = sell_price
                if paid_amount < sell_price:
                    first_due = cd.get("installment_date")
                    booking.agreed_last_due = first_due
                    p.installment_date = first_due
            else:
                p.installment_date = None

            booking.save()
            p.net_price  = booking.net or Decimal("0")
            p.sell_price = booking.sell or Decimal("0")
            p.save()

            messages.success(request, "✅ تم حفظ بيانات الدفع بنجاح.")
            return redirect("hotel_payment", booking_pk=booking.pk)

        return render(request, "core/hotel_payment.html", {
            "booking": booking, "form": pay_form, "payments": payments,
            "remaining": remaining, "total_paid": total_paid,
            "total_sell": total_sell, "total_net": total_net,
            "profit": profit, "has_existing": has_existing,
            "is_fully_paid": is_fully_paid,
        })

    pay_form = PaymentForm(booking=booking, has_existing_payments=has_existing)
    return render(request, "core/hotel_payment.html", {
        "booking": booking, "form": pay_form, "payments": payments,
        "remaining": remaining, "total_paid": total_paid,
        "total_sell": total_sell, "total_net": total_net,
        "profit": profit, "has_existing": has_existing,
        "is_fully_paid": is_fully_paid,
    })
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
            booking = form.save(commit=False)
            booking.card = card
            booking.employee_name = request.user.get_full_name() or request.user.username
            booking.save()
            return redirect("flight_payment", booking_pk=booking.pk)
    else:
        form = FlightBookingForm()
    return render(request, "core/flight_form.html", {"form": form, "card": card})

@login_required
def flight_voucher(request, booking_pk):
    b = get_object_or_404(FlightBooking, pk=booking_pk)
    qr = _build_qr_data_url(request.build_absolute_uri(reverse("flight_voucher", args=[b.pk])))
    return render(request, "core/flight_voucher.html", {
        "b": b, "today": timezone.localdate(), "qr_data_url": qr,
    })

@login_required
def flight_voucher_pdf(request, booking_pk):
    b = get_object_or_404(FlightBooking, pk=booking_pk)
    qr = _build_qr_data_url(request.build_absolute_uri(reverse('flight_voucher', args=[b.pk])))
    pdf_bytes = _render_pdf_from_template(
        'core/flight_voucher_pdf.html',
        {'b': b, 'today': timezone.localdate(), 'qr_data_url': qr},
        request,
    )
    if pdf_bytes is None:
        return HttpResponse("PDF render error", status=500)
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="Flight_{b.voucher_code}.pdf"'
    return resp


# ===================== Other =====================

@login_required
def other_create(request, card_pk):
    card = get_object_or_404(UniBookingCard, pk=card_pk)

    # نطبق نفس قاعدة السماح هنا (مثل flight_create)
    if not request.user.is_superuser and card.created_by != request.user:
        messages.error(request, "غير مسموح بإضافة خدمة/حجز على كارت ليس ملكك.")
        return redirect('dashboard')

    if request.method == "POST":
        # لو تحتاج رفع ملفات للخدمات خلي request.FILES موجود
        form = OtherBookingForm(request.POST, request.FILES)
        if form.is_valid():
            other = form.save(commit=False)
            other.card = card
            other.employee_name = request.user.get_full_name() or request.user.username
            other.save()
            messages.success(request, "تم حفظ الخدمة بنجاح.")
            return redirect("other_payment", pk=other.pk)
        else:
            messages.error(request, "من فضلك املأ الحقول الإلزامية بشكل صحيح.")
    else:
        form = OtherBookingForm()

    return render(request, "core/other_form.html", {"form": form, "card": card})

# ---------------- Other Payments ----------------
@login_required
def other_payment(request, pk):
    booking = get_object_or_404(OtherBooking, pk=pk)
    payments = booking.payments.order_by("-created_at")
    has_existing = payments.exists()

    total_paid = payments.aggregate(total=Sum("paid_amount"))["total"] or Decimal("0.00")
    total_net  = booking.net_price  or Decimal("0.00")
    total_sell = booking.sell_price or Decimal("0.00")
    remaining  = total_sell - total_paid
    profit     = total_sell - total_net

    try:
        adjustments_qs = booking.adjustments.order_by("-created_at")
        adjustments_total = adjustments_qs.aggregate(s=Sum("amount"))["s"] or Decimal("0")
    except Exception:
        adjustments_qs = []
        adjustments_total = Decimal("0")
    remaining_after_adj = remaining + adjustments_total
    adj_form = None

    if request.method == "POST":
        form = OtherPaymentForm(request.POST, request.FILES, booking=booking, has_existing_payments=has_existing)
        if form.is_valid():
            cd = form.cleaned_data
            paid_amount = cd.get("paid_amount") or Decimal("0")
            sell_price  = (cd.get("sell_price") if not has_existing else booking.sell_price) or Decimal("0")
            net_price   = (cd.get("net_price")  if not has_existing else booking.net_price)  or Decimal("0")

            errors = False
            if paid_amount < 0:
                form.add_error("paid_amount", "المبلغ المدفوع يجب أن يكون قيمة موجبة أو صفر.")
                errors = True
            if paid_amount > sell_price:
                form.add_error("paid_amount", "المبلغ المدفوع لا يمكن أن يتجاوز سعر البيع.")
                errors = True

            if not has_existing:
                if not cd.get("invoice_file"):
                    form.add_error("invoice_file", "ملف الفاتورة مطلوب عند أول دفعة.")
                    errors = True
                if not cd.get("voucher_original"):
                    form.add_error("voucher_original", "الفاوتشر الأصلي مطلوب عند أول دفعة.")
                    errors = True

            method = cd.get("method")
            if method == "link" and not cd.get("payment_link"):
                form.add_error("payment_link", "رابط السداد مطلوب لأسلوب الدفع (Link).")
                errors = True
            if method in ("bank", "cash") and not cd.get("bank_file"):
                form.add_error("bank_file", "مطلوب رفع إيصال للـ Bank/Cash.")
                errors = True

            if not has_existing and paid_amount < sell_price and not cd.get("installment_date"):
                form.add_error("installment_date", "مطلوب تحديد آخر ميعاد للسداد عند أول دفعة غير كاملة.")
                errors = True

            if errors:
                messages.error(request, "صحح الأخطاء ثم حاول مرة أخرى.")
                return render(request, "core/other_payment.html", {
                    "booking": booking, "form": form, "payments": payments,
                    "has_existing": has_existing,
                    "total_paid": total_paid, "total_sell": total_sell,
                    "total_net": total_net, "remaining": remaining,
                    "profit": profit,
                    "adjustments": adjustments_qs,
                    "adjustments_total": adjustments_total,
                    "remaining_after_adj": remaining_after_adj,
                    "adj_form": adj_form,
                })

            p = form.save(commit=False)
            p.booking_other = booking
            p.employee_name = request.user.get_full_name() or request.user.username

            if not has_existing:
                booking.net_price = net_price
                booking.sell_price = sell_price
                if paid_amount < sell_price:
                    first_due = cd.get("installment_date")
                    booking.agreed_last_due = first_due
                    p.installment_date = first_due
                else:
                    p.installment_date = None
                booking.save()
                p.net_price = booking.net_price
                p.sell_price = booking.sell_price
            else:
                p.installment_date = None
                p.net_price = booking.net_price or Decimal("0")
                p.sell_price = booking.sell_price or Decimal("0")

            p.save()
            messages.success(request, "✅ تم حفظ الدفعة بنجاح.")
            return redirect("other_payment", pk=booking.pk)
        else:
            messages.error(request, "⚠️ يوجد خطأ في البيانات.")
    else:
        form = OtherPaymentForm(booking=booking, has_existing_payments=has_existing)

    return render(request, "core/other_payment.html", {
        "booking": booking, "form": form, "payments": payments,
        "has_existing": has_existing,
        "total_paid": total_paid, "total_sell": total_sell,
        "total_net": total_net, "remaining": remaining,
        "profit": profit,
        "adjustments": adjustments_qs,
        "adjustments_total": adjustments_total,
        "remaining_after_adj": remaining_after_adj,
        "adj_form": adj_form,
    })

# --------------- FLIGHT PAYMENTS ----------------
@login_required
def flight_payment(request, booking_pk):
    booking = get_object_or_404(FlightBooking, pk=booking_pk)
    payments = booking.payments.order_by("-created_at")
    has_existing = payments.exists()

    total_paid = payments.aggregate(total=Sum("paid_amount"))["total"] or Decimal("0.00")
    total_net  = booking.net_price  or Decimal("0.00")
    total_sell = booking.sell_price or Decimal("0.00")
    remaining  = total_sell - total_paid
    profit     = total_sell - total_net

    try:
        adjustments_qs = booking.adjustments.order_by("-created_at")
        adjustments_total = adjustments_qs.aggregate(s=Sum("amount"))["s"] or Decimal("0")
    except Exception:
        adjustments_qs = []
        adjustments_total = Decimal("0")
    remaining_after_adj = remaining + adjustments_total
    adj_form = None

    if request.method == "POST":
        form = FlightPaymentForm(request.POST, request.FILES, booking=booking, has_existing_payments=has_existing)
        if form.is_valid():
            cd = form.cleaned_data
            paid_amount = cd.get("paid_amount") or Decimal("0")
            sell_price  = (cd.get("sell_price") if not has_existing else booking.sell_price) or Decimal("0")
            net_price   = (cd.get("net_price")  if not has_existing else booking.net_price)  or Decimal("0")

            errors = False
            if paid_amount < 0:
                form.add_error("paid_amount", "المبلغ المدفوع يجب أن يكون قيمة موجبة أو صفر.")
                errors = True
            if paid_amount > sell_price:
                form.add_error("paid_amount", "المبلغ المدفوع لا يمكن أن يتجاوز سعر البيع.")
                errors = True

            if not has_existing:
                if not cd.get("invoice_file"):
                    form.add_error("invoice_file", "ملف الفاتورة مطلوب عند أول دفعة.")
                    errors = True
                if not cd.get("voucher_original"):
                    form.add_error("voucher_original", "الفاوتشر الأصلي مطلوب عند أول دفعة.")
                    errors = True

            method = cd.get("method")
            if method == "link" and not cd.get("payment_link"):
                form.add_error("payment_link", "رابط السداد مطلوب لأسلوب الدفع (Link).")
                errors = True
            if method in ("bank", "cash") and not cd.get("bank_file"):
                form.add_error("bank_file", "مطلوب رفع إيصال للـ Bank/Cash.")
                errors = True

            if not has_existing and paid_amount < sell_price and not cd.get("installment_date"):
                form.add_error("installment_date", "مطلوب تحديد آخر ميعاد للسداد عند أول دفعة غير مكتملة.")
                errors = True

            if errors:
                messages.error(request, "صحح الأخطاء ثم حاول مرة أخرى.")
                return render(request, "core/flight_payment.html", {
                    "booking": booking, "form": form, "payments": payments,
                    "total_net": total_net, "total_sell": total_sell,
                    "total_paid": total_paid, "remaining": remaining,
                    "profit": profit, "has_existing": has_existing,
                    "adjustments": adjustments_qs,
                    "adjustments_total": adjustments_total,
                    "remaining_after_adj": remaining_after_adj,
                    "adj_form": adj_form,
                })

            p = form.save(commit=False)
            p.booking_flight = booking
            p.employee_name = request.user.get_full_name() or request.user.username

            if not has_existing:
                booking.net_price = net_price
                booking.sell_price = sell_price
                if paid_amount < sell_price:
                    first_due = cd.get("installment_date")
                    booking.agreed_last_due = first_due
                    p.installment_date = first_due
                else:
                    p.installment_date = None
                booking.save()
                p.net_price = booking.net_price
                p.sell_price = booking.sell_price
            else:
                p.installment_date = None
                p.net_price = booking.net_price or Decimal("0")
                p.sell_price = booking.sell_price or Decimal("0")

            p.save()
            messages.success(request, "✅ تم حفظ بيانات الدفع بنجاح.")
            return redirect("flight_payment", booking_pk=booking.pk)
        else:
            messages.error(request, "⚠️ يوجد خطأ في البيانات.")
    else:
        form = FlightPaymentForm(booking=booking, has_existing_payments=has_existing)

    return render(request, "core/flight_payment.html", {
        "booking": booking, "form": form, "payments": payments,
        "total_net": total_net, "total_sell": total_sell,
        "total_paid": total_paid, "remaining": remaining,
        "profit": profit, "has_existing": has_existing,
        "adjustments": adjustments_qs,
        "adjustments_total": adjustments_total,
        "remaining_after_adj": remaining_after_adj,
        "adj_form": adj_form,
    })


# ===================== Installments Board (لوحة الأقساط) =====================

@login_required
def installments_board(request):
    # فلاتر GET
    q_from   = request.GET.get("from") or ""
    q_to     = request.GET.get("to") or ""
    q_q      = (request.GET.get("q") or "").strip()
    # نخلي الصفحة كلها على المتبقي>0
    only_due = True

    date_from = parse_date(q_from) if q_from else None
    date_to   = parse_date(q_to) if q_to else None
    today     = timezone.localdate()

    # صلاحيات
    if request.user.is_superuser:
        base_b = {}
        base_p = {}
    else:
        emp = (request.user.get_full_name() or request.user.username or "").strip()
        base_b = {"employee_name__iexact": emp}
        base_p = {"employee_name__iexact": emp}

    # تذكير الأقساط القريبة (خلال n أيام) — من دفعات لها تاريخ قسط
    remind_days = int(getattr(settings, "INSTALLMENT_REMINDER_DAYS", 5))
    # ✅ إصلاح: استخدم timedelta من datetime بدل timezone.timedelta
    soon = today + timedelta(days=remind_days)

    def _installments_qs(PModel, rel, kind, urlname):
        """
        يرجّع أقساط مستحقة قريبًا *فقط* للحجوزات التي مازال عليها متبقي فعليًا.
        rel: اسم العلاقة على نموذج الدفعة (booking_hotel | booking_flight | booking_other)
        """
        qs = (
            PModel.objects
            .filter(**base_p, installment_date__range=(today, soon))
            .select_related(rel)
            .order_by("installment_date")
        )

        rows_ = []
        for p in qs[:50]:
            b = getattr(p, rel, None)
            if not b or not getattr(b, "pk", None):
                continue

            # إجمالي البيع للحجز (sell أو sell_price حسب النوع)
            sell = getattr(b, "sell_price", None) or getattr(b, "sell", None) or Decimal("0")

            # إجمالي المدفوع لهذا الحجز من نفس جدول الدفعات
            rel_field = f"{rel}_id"
            paid_total = (
                PModel.objects
                .filter(**{rel_field: b.pk})
                .aggregate(total=Sum("paid_amount"))
                .get("total") or Decimal("0")
            )

            remaining = (sell or Decimal("0")) - (paid_total or Decimal("0"))

            # ✅ استبعد الحجوزات المسددة بالكامل (بسماحية 0.01)
            if remaining <= Decimal("0.01"):
                continue

            cust = b.card.customer_name if b.card_id else "-"
            rows_.append({
                "kind": kind,
                "customer": cust,
                "due": p.installment_date,
                "amount": p.paid_amount or Decimal("0"),
                "url": reverse(urlname, args=[b.pk]),
                "days": (p.installment_date - today).days if p.installment_date else None,
            })
        return rows_

    reminders = []
    reminders += _installments_qs(Payment,       "booking_hotel",  "فندق",  "hotel_payment")
    reminders += _installments_qs(FlightPayment, "booking_flight", "طيران", "flight_payment")
    reminders += _installments_qs(OtherPayment,  "booking_other",  "أخرى",  "other_payment")
    reminders.sort(key=lambda r: (r["due"], r["customer"]))

    # مصدر الحجوزات (فلترة بتاريخ الحجز)
    h_b = HotelBooking.objects.filter(**base_b).select_related("card")
    f_b = FlightBooking.objects.filter(**base_b).select_related("card")
    o_b = OtherBooking.objects.filter(**base_b).select_related("card")

    if date_from:
        h_b = h_b.filter(booking_date__gte=date_from)
        f_b = f_b.filter(booking_date__gte=date_from)
        o_b = o_b.filter(booking_date__gte=date_from)
    if date_to:
        h_b = h_b.filter(booking_date__lte=date_to)
        f_b = f_b.filter(booking_date__lte=date_to)
        o_b = o_b.filter(booking_date__lte=date_to)

    if q_q:
        h_b = h_b.filter(card__customer_name__icontains=q_q)
        f_b = f_b.filter(card__customer_name__icontains=q_q)
        o_b = o_b.filter(card__customer_name__icontains=q_q)

    # دفعات كل نوع
    p_h = Payment.objects.filter(booking_hotel__in=h_b)
    p_f = FlightPayment.objects.filter(booking_flight__in=f_b)
    p_o = OtherPayment.objects.filter(booking_other__in=o_b)

    # مجاميع المدفوع لكل حجز
    paid_by_h = dict(
        p_h.values("booking_hotel_id").annotate(total=Sum("paid_amount")).values_list("booking_hotel_id","total")
    )
    paid_by_f = dict(
        p_f.values("booking_flight_id").annotate(total=Sum("paid_amount")).values_list("booking_flight_id","total")
    )
    paid_by_o = dict(
        p_o.values("booking_other_id").annotate(total=Sum("paid_amount")).values_list("booking_other_id","total")
    )

    rows = []

    def _row_from_booking(b, kind, sell, net, paid):
        sell = sell or Decimal("0")
        net  = net  or Decimal("0")
        paid = paid or Decimal("0")
        remain = sell - paid
        return {
            "voucher": getattr(b, "voucher_code", "") or "-",
            "kind": kind,
            "date": b.created_at,
            "book_date": getattr(b, "booking_date", None),
            "customer": b.card.customer_name if getattr(b, "card_id", None) else "",
            "employee": b.employee_name or "-",
            "sell": sell,
            "net": net,
            "paid": paid,
            "remain": remain,
            "profit": sell - net,
            "last_due": getattr(b, "agreed_last_due", None),
            "detail_url": reverse("card_detail", args=[b.card_id]) if getattr(b, "card_id", None) else "#",
            "pay_url": reverse(
                "hotel_payment" if kind == "فندق"
                else "flight_payment" if kind == "طيران"
                else "other_payment",
                args=[b.pk]
            ),
            "ref": getattr(b, "booking_ref", "") or getattr(b, "voucher_code", "") or "",
        }

    for b in h_b.only("id","sell","net","employee_name","card_id","created_at","booking_ref","booking_date","voucher_code","agreed_last_due"):
        rows.append(_row_from_booking(b, "فندق",  b.sell,       b.net,       paid_by_h.get(b.id, Decimal("0"))))
    for b in f_b.only("id","sell_price","net_price","employee_name","card_id","created_at","pnr","booking_date","voucher_code","agreed_last_due"):
        rows.append(_row_from_booking(b, "طيران", b.sell_price, b.net_price, paid_by_f.get(b.id, Decimal("0"))))
    for b in o_b.only("id","sell_price","net_price","employee_name","card_id","created_at","booking_date","voucher_code","agreed_last_due"):
        rows.append(_row_from_booking(b, "أخرى",  b.sell_price, b.net_price, paid_by_o.get(b.id, Decimal("0"))))

    # فلترة نهائية: الحجوزات اللي عليها متبقي فقط
    rows = [r for r in rows if (r.get("remain") or Decimal("0")) > Decimal("0.01")]
    rows.sort(key=lambda r: r["date"], reverse=True)

    # KPIs من المعروض فقط
    kpis = {
        "total_sell":      sum((r.get("sell")    or Decimal("0")) for r in rows),
        "total_net":       sum((r.get("net")     or Decimal("0")) for r in rows),
        "total_paid":      sum((r.get("paid")    or Decimal("0")) for r in rows),
        "total_remaining": sum((r.get("remain")  or Decimal("0")) for r in rows),
        "total_profit":    sum((r.get("profit")  or Decimal("0")) for r in rows),
    }

    return render(request, "core/installments_board.html", {
        "q_from": q_from, "q_to": q_to, "q": q_q,
        "kpis": kpis,
        "reminders": reminders,
        "rows": rows[:300],
        "remind_days": remind_days,
        "only_due": only_due,
        "today": today,
    })


# ===================== Agent Board (ملخّص الموظف) =====================

@login_required
def agent_board(request):
    me = (request.user.get_full_name() or request.user.username).strip()
    owned = Q(employee_name__iexact=me) if not request.user.is_superuser else Q()

    d_from = request.GET.get("from") or ""
    d_to   = request.GET.get("to") or ""
    date_h, date_flt, date_o = {}, {}, {}
    if d_from:
        date_h["booking_date__gte"]   = d_from
        date_flt["booking_date__gte"] = d_from
        date_o["booking_date__gte"]   = d_from
    if d_to:
        date_h["booking_date__lte"]   = d_to
        date_flt["booking_date__lte"] = d_to
        date_o["booking_date__lte"]   = d_to

    h = HotelBooking.objects.filter(owned, **date_h).select_related("card")
    f = FlightBooking.objects.filter(owned, **date_flt).select_related("card")
    o = OtherBooking.objects.filter(owned, **date_o).select_related("card")

    def sum_or0(qs, field):
        v = qs.aggregate(s=Sum(field))["s"]
        return Decimal(v or 0)

    pays_h = Payment.objects.filter(booking_hotel__in=h)
    pays_f = FlightPayment.objects.filter(booking_flight__in=f)
    pays_o = OtherPayment.objects.filter(booking_other__in=o)

    total_sell = sum_or0(h, "sell") + sum_or0(f, "sell_price") + sum_or0(o, "sell_price")
    total_net  = sum_or0(h, "net")  + sum_or0(f, "net_price")  + sum_or0(o, "net_price")
    total_paid = sum_or0(pays_h, "paid_amount") + sum_or0(pays_f, "paid_amount") + sum_or0(pays_o, "paid_amount")
    total_profit    = total_sell - total_net
    total_remaining = total_sell - total_paid

    # أقساط قريبة (5 أيام) — تظهر فقط إن كانت أول دفعة مسجّل لها installment_date
    today = timezone.localdate()
    soon  = today + timedelta(days=5)
    due_installments = []

    def add_dues(qs, title, url_name, id_field):
        for p in qs.filter(method="installment", installment_date__range=(today, soon)).select_related():
            b = getattr(p, f"booking_{title}") if title != "hotel" else p.booking_hotel
            due_installments.append({
                "date": p.installment_date,
                "amount": p.paid_amount,
                "customer": b.card.customer_name if getattr(b, "card_id", None) else "-",
                "ref": getattr(b, "voucher_code", None) or getattr(b, "booking_ref", None) or getattr(b, "pnr", "") or "",
                "url": reverse(url_name, args=[getattr(p, id_field)]),
                "kind": title,
            })

    add_dues(Payment.objects.all(),       "hotel",  "hotel_payment",  "booking_hotel_id")
    add_dues(FlightPayment.objects.all(), "flight", "flight_payment", "booking_flight_id")
    add_dues(OtherPayment.objects.all(),  "other",  "other_payment",  "booking_other_id")
    due_installments.sort(key=lambda x: (x["date"], x["kind"]))

    rows = []
    for b in h.only("id","booking_date","created_at","sell","net","card_id","voucher_code","booking_ref"):
        sell = b.sell or Decimal("0"); net = b.net or Decimal("0")
        rows.append(("hotel", {
            "id": b.id,
            "book_date": b.booking_date,
            "created_at": b.created_at,
            "sell": sell,
            "net": net,
            "profit": sell - net,
            "card_id": b.card_id,
            "ref_full": (b.voucher_code or b.booking_ref or ""),
        }))

    for b in f.only("id","booking_date","created_at","sell_price","net_price","card_id","voucher_code","pnr"):
        sell = b.sell_price or Decimal("0"); net = b.net_price or Decimal("0")
        rows.append(("flight", {
            "id": b.id,
            "book_date": b.booking_date,
            "created_at": b.created_at,
            "sell_price": sell,
            "net_price": net,
            "profit": sell - net,
            "card_id": b.card_id,
            "ref_full": (b.voucher_code or b.pnr or ""),
        }))

    for b in o.only("id","booking_date","created_at","sell_price","net_price","card_id","voucher_code","booking_ref"):
        sell = b.sell_price or Decimal("0"); net = b.net_price or Decimal("0")
        rows.append(("other", {
            "id": b.id,
            "book_date": b.booking_date,
            "created_at": b.created_at,
            "sell_price": sell,
            "net_price": net,
            "profit": sell - net,
            "card_id": b.card_id,
            "ref_full": (b.voucher_code or b.booking_ref or ""),
        }))

    rows.sort(key=lambda x: x[1]["book_date"], reverse=True)
    rows = rows[:100]

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
    q_from    = parse_date(request.GET.get('from') or '')
    q_to      = parse_date(request.GET.get('to') or '')
    q_emp     = (request.GET.get('employee') or '').strip()
    q_kind    = (request.GET.get('kind') or '').strip()
    q_group   = (request.GET.get('group') or '').strip()
    q_scope   = (request.GET.get('scope') or ('all' if request.user.is_superuser else 'mine')).strip()
    page_num  = int(request.GET.get('page') or 1)

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
        base_filter = {}
        can_choose_scope = True
    else:
        current_emp = (request.user.get_full_name() or request.user.username or '').strip()
        base_filter = {'employee_name__iexact': current_emp}
        can_choose_scope = False
        q_scope = 'mine'

    rows, labels = [], []

    def _append(qs, kname, fmt, payments_rel, emp_model, emp_fk):
        qs = qs.filter(**base_filter)
        qs = _date_filter_using_acc(qs, q_from, q_to)
        if q_emp:
            qs = qs.filter(**{f'{payments_rel}__employee_name__icontains': q_emp})

        qs = qs.annotate(last_emp=Subquery(
            emp_model.objects.filter(**{emp_fk: OuterRef('pk')})
            .order_by('-created_at').values('employee_name')[:1]
        ))
        qs = _with_acc_date(qs).select_related('card').only(
            'id','booking_ref','voucher_code','created_at','card__customer_name'
        )

        cnt = qs.count()
        labels.append((kname, cnt))

        for r in qs[:2000]:
            rows.append({
                'kind': kname,
                'ref': getattr(r, 'booking_ref', '') or '',
                'voucher': getattr(r, 'voucher_code', '') or '',
                'employee': r.last_emp or '-',
                'customer': r.card.customer_name if getattr(r, 'card_id', None) else '',
                'created': r.acc_date,
                'extra': fmt(r),
            })

    if q_kind in ('hotel',''):
        _append(HotelBooking.objects.all(), 'Hotel',
                lambda r: f'{getattr(r,"hotel_name","-")}/{getattr(r,"country","-") or "-"}',
                'payments', Payment, 'booking_hotel')
    if q_kind in ('flight',''):
        _append(FlightBooking.objects.all(), 'Flight',
                lambda r: f'{getattr(r,"airline","-")}/{getattr(r,"pnr","-")}',
                'payments', FlightPayment, 'booking_flight')
    if q_kind in ('other',''):
        _append(OtherBooking.objects.all(), 'Other',
                lambda r: f'{r.get_service_type_display()}/{getattr(r,"provider_name","-") or "-"}',
                'payments', OtherPayment, 'booking_other')

    rows.sort(key=lambda x: x['created'] or today, reverse=True)
    chart_labels = [k for k,_ in labels]
    chart_values = [c for _,c in labels]

    # Pagination
    paginator = Paginator(rows, 100)
    page_obj = paginator.get_page(page_num)
    rows_page = list(page_obj.object_list)

    # KPIs (acc_date)
    def _sum(qs, field): return qs.aggregate(v=Sum(field))['v'] or Decimal('0')
    def _filtered(model_qs, payments_rel):
        qs = model_qs.filter(**base_filter)
        qs = _date_filter_using_acc(qs, q_from, q_to)
        if q_emp:
            qs = qs.filter(**{f'{payments_rel}__employee_name__icontains': q_emp})
        return qs.distinct()

    h_qs = _filtered(HotelBooking.objects.all(), 'payments')
    f_qs = _filtered(FlightBooking.objects.all(), 'payments')
    o_qs = _filtered(OtherBooking.objects.all(), 'payments')

    total_sell = _sum(h_qs,'sell') + _sum(f_qs,'sell_price') + _sum(o_qs,'sell_price')
    total_net  = _sum(h_qs,'net')  + _sum(f_qs,'net_price')  + _sum(o_qs,'net_price')
    paid_hotel = _sum(Payment.objects.filter(booking_hotel__in=h_qs), 'paid_amount')
    paid_flight= _sum(FlightPayment.objects.filter(booking_flight__in=f_qs), 'paid_amount')
    paid_other = _sum(OtherPayment.objects.filter(booking_other__in=o_qs), 'paid_amount')
    total_paid = paid_hotel + paid_flight + paid_other
    totals = {
        'sell': total_sell,
        'net': total_net,
        'profit': total_sell - total_net,
        'paid': total_paid,
        'remaining': total_sell - total_paid,
    }

    # Group by employee (اختياري)
    emp_rows = []
    if q_group == 'employee':
        agg = {}
        def _add(emp, sell=0, net=0, paid=0, count=0):
            d = agg.setdefault(emp or '-', {'sell':Decimal('0'), 'net':Decimal('0'),
                                            'paid':Decimal('0'), 'count':0})
            d['sell'] += Decimal(sell); d['net'] += Decimal(net)
            d['paid'] += Decimal(paid); d['count'] += int(count)

        for p in Payment.objects.filter(booking_hotel__in=h_qs).only('employee_name','sell_price','net_price','paid_amount'):
            _add(p.employee_name, sell=p.sell_price or 0, net=p.net_price or 0, paid=p.paid_amount or 0)
        for p in FlightPayment.objects.filter(booking_flight__in=f_qs).only('employee_name','sell_price','net_price','paid_amount'):
            _add(p.employee_name, sell=p.sell_price or 0, net=p.net_price or 0, paid=p.paid_amount or 0)
        for p in OtherPayment.objects.filter(booking_other__in=o_qs).only('employee_name','sell_price','net_price','paid_amount'):
            _add(p.employee_name, sell=p.sell_price or 0, net=p.net_price or 0, paid=p.paid_amount or 0)

        def _count_by_latest(qs, model, fk):
            sub = Subquery(model.objects.filter(**{fk:OuterRef('pk')}).order_by('-created_at').values('employee_name')[:1])
            for rec in _with_acc_date(qs).annotate(last_emp=sub).values('last_emp'):
                _add(rec['last_emp'] or '-', count=1)
        _count_by_latest(h_qs, Payment, 'booking_hotel')
        _count_by_latest(f_qs, FlightPayment, 'booking_flight')
        _count_by_latest(o_qs, OtherPayment, 'booking_other')

        for emp, v in agg.items():
            profit = (v['sell'] - v['net'])
            emp_rows.append({
                'employee': emp,
                'count': v['count'],
                'sell': v['sell'],
                'net': v['net'],
                'profit': profit,
                'paid': v['paid'],
                'remaining': (v['sell'] - v['paid']),
            })
        emp_rows.sort(key=lambda x: x['profit'], reverse=True)

    # Top-5 employees by profit
    if emp_rows:
        top_emp = emp_rows[:5]
    else:
        profit_map = {}
        def _add_profit(qs, sell_field, net_field):
            for p in qs.values('employee_name').annotate(
                sell=Sum(sell_field), net=Sum(net_field)
            ):
                nm = p['employee_name'] or '-'
                profit_map[nm] = profit_map.get(nm, Decimal('0')) + (p['sell'] or 0) - (p['net'] or 0)
        _add_profit(Payment.objects.filter(booking_hotel__in=h_qs), 'sell_price', 'net_price')
        _add_profit(FlightPayment.objects.filter(booking_flight__in=f_qs), 'sell_price', 'net_price')
        _add_profit(OtherPayment.objects.filter(booking_other__in=o_qs), 'sell_price', 'net_price')
        top_emp = sorted(
            [{'employee': k, 'profit': v} for k,v in profit_map.items()],
            key=lambda x: x['profit'], reverse=True
        )[:5]
    top_emp_labels = [t['employee'] for t in top_emp]
    top_emp_values = [float(t['profit']) for t in top_emp]

    # Monthly sales (current year) عبر acc_date
    cur_year = today.year
    months = list(range(1,13))
    month_totals = {m: Decimal('0') for m in months}

    def _add_monthly(qs, field):
        qs = _with_acc_date(qs).filter(acc_date__year=cur_year)
        for r in qs.values(m=ExtractMonth('acc_date')).annotate(s=Sum(field)):
            if r['m'] in month_totals:
                month_totals[r['m']] += r['s'] or 0

    _add_monthly(h_qs, 'sell')
    _add_monthly(f_qs, 'sell_price')
    _add_monthly(o_qs, 'sell_price')

    month_labels = ["يناير","فبراير","مارس","أبريل","مايو","يونيو","يوليو","أغسطس","سبتمبر","أكتوبر","نوفمبر","ديسمبر"]
    month_values = [float(month_totals[m]) for m in months]

    # Suppliers summary
    sup_map = {}
    for b in _with_acc_date(h_qs).only('provider_name', 'sell'):
        nm = _norm_supplier(getattr(b, 'provider_name', '') or '-')
        row = sup_map.setdefault(nm, {'count': 0, 'sell': Decimal('0')})
        row['count'] += 1
        row['sell']  += (b.sell or Decimal('0'))
    for b in _with_acc_date(o_qs).only('provider_name', 'sell_price'):
        nm = _norm_supplier(getattr(b, 'provider_name', '') or '-')
        row = sup_map.setdefault(nm, {'count': 0, 'sell': Decimal('0')})
        row['count'] += 1
        row['sell']  += (b.sell_price or Decimal('0'))
    supplier_rows = [{'supplier': k, 'count': v['count'], 'sell': v['sell']} for k,v in sup_map.items()]
    supplier_rows.sort(key=lambda x: (-x['count'], -x['sell']))

    # Airlines summary
    air_map = {}
    for b in _with_acc_date(f_qs).only('airline', 'sell_price'):
        nm = _norm_airline(getattr(b, 'airline', '') or '-')
        row = air_map.setdefault(nm, {'count': 0, 'sell': Decimal('0')})
        row['count'] += 1
        row['sell']  += (b.sell_price or Decimal('0'))
    airline_rows = [{'airline': k, 'count': v['count'], 'sell': v['sell']} for k,v in air_map.items()]
    airline_rows.sort(key=lambda x: (-x['count'], -x['sell']))

    return render(request, 'core/reports.html', {
        'rows_page': rows_page,
        'page_obj': page_obj,
        'rows': rows,
        'chart_labels': chart_labels,
        'chart_values': chart_values,
        'top_emp_labels': top_emp_labels,
        'top_emp_values': top_emp_values,
        'month_labels': month_labels,
        'month_values': month_values,
        'totals': totals,
        'emp_rows': emp_rows,
        'supplier_rows': supplier_rows,
        'airline_rows': airline_rows,
        'q_from': q_from.isoformat() if q_from else '',
        'q_to': q_to.isoformat() if q_to else '',
        'q_employee': q_emp,
        'q_kind': q_kind,
        'q_group': q_group,
        'q_scope': q_scope,
        'can_choose_scope': can_choose_scope,
        'cur_year': cur_year,
    })

@login_required
def reports_export_csv(request):
    date_from = parse_date(request.GET.get('from') or '')
    date_to   = parse_date(request.GET.get('to') or '')
    employee  = (request.GET.get('employee') or '').strip()
    kind      = (request.GET.get('kind') or '').strip()
    scope     = (request.GET.get('scope') or ('all' if request.user.is_superuser else 'mine')).strip()

    if request.user.is_superuser:
        base_filter = {} if scope == 'all' else {'card__created_by': request.user}
    else:
        base_filter = {'card__created_by': request.user}

    rows = []

    def _append(qs, kname, fmt, payments_rel, emp_model, emp_fk):
        qs = _date_filter_using_acc(qs.filter(**base_filter), date_from, date_to)
        if employee:
            qs = qs.filter(**{f'{payments_rel}__employee_name__icontains': employee})
        qs = qs.annotate(last_emp=_latest_emp_subquery(emp_model, emp_fk))
        qs = _with_acc_date(qs).select_related('card')
        for r in qs[:5000]:
            rows.append([
                kname,
                getattr(r, 'booking_ref', '') or '',
                getattr(r, 'voucher_code', '') or '',
                r.last_emp or '-',
                (r.card.customer_name if getattr(r, 'card_id', None) else ''),
                (r.acc_date.isoformat() if getattr(r, 'acc_date', None) else ''),
                fmt(r),
            ])

    if kind in ('hotel', ''):
        _append(HotelBooking.objects.all(), 'Hotel',
                lambda r: f'{r.hotel_name or "-"} / {getattr(r,"country","-") or "-"}',
                'payments', Payment, 'booking_hotel')
    if kind in ('flight', ''):
        _append(FlightBooking.objects.all(), 'Flight',
                lambda r: f'{getattr(r,"airline","-")} / {getattr(r,"pnr","-")}',
                'payments', FlightPayment, 'booking_flight')
    if kind in ('other', ''):
        _append(OtherBooking.objects.all(), 'Other',
                lambda r: f'{r.get_service_type_display()} / {r.provider_name or "-"}',
                'payments', OtherPayment, 'booking_other')

    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="reports.csv"'
    writer = csv.writer(resp)
    writer.writerow(['Kind','Booking Ref','Voucher','Employee','Customer','Accounting Date','Extra'])
    writer.writerows(rows)
    return resp

@login_required
def reports_export_xlsx(request):
    if Workbook is None:
        return HttpResponse("openpyxl غير مُثبت. ثبّته: pip install openpyxl", status=500)

    date_from = parse_date(request.GET.get('from') or '')
    date_to   = parse_date(request.GET.get('to') or '')
    employee  = (request.GET.get('employee') or '').strip()
    kind      = (request.GET.get('kind') or '').strip()
    scope     = (request.GET.get('scope') or ('all' if request.user.is_superuser else 'mine')).strip()

    if request.user.is_superuser:
        base_filter = {} if scope == 'all' else {'card__created_by': request.user}
    else:
        base_filter = {'card__created_by': request.user}

    rows = []

    def _append(qs, kname, fmt, payments_rel, emp_model, emp_fk):
        qs = _date_filter_using_acc(qs.filter(**base_filter), date_from, date_to)
        if employee:
            qs = qs.filter(**{f'{payments_rel}__employee_name__icontains': employee})
        qs = qs.annotate(last_emp=_latest_emp_subquery(emp_model, emp_fk))
        qs = _with_acc_date(qs).select_related('card')
        for r in qs[:5000]:
            rows.append([
                kname,
                getattr(r, 'booking_ref', '') or '',
                getattr(r, 'voucher_code', '') or '',
                r.last_emp or '-',
                (r.card.customer_name if getattr(r, 'card_id', None) else ''),
                (r.acc_date.isoformat() if getattr(r, 'acc_date', None) else ''),
                fmt(r),
            ])

    if kind in ('hotel', ''):
        _append(HotelBooking.objects.all(), 'Hotel',
                lambda r: f'{r.hotel_name or "-"} / {getattr(r,"country","-") or "-"}',
                'payments', Payment, 'booking_hotel')
    if kind in ('flight', ''):
        _append(FlightBooking.objects.all(), 'Flight',
                lambda r: f'{getattr(r,"airline","-")} / {getattr(r,"pnr","-")}',
                'payments', FlightPayment, 'booking_flight')
    if kind in ('other', ''):
        _append(OtherBooking.objects.all(), 'Other',
                lambda r: f'{r.get_service_type_display()} / {r.provider_name or "-"}',
                'payments', OtherPayment, 'booking_other')

    wb = Workbook()
    ws = wb.active
    ws.title = "Reports"
    ws.append(['Kind','Booking Ref','Voucher','Employee','Customer','Accounting Date','Extra'])
    for r in rows:
        ws.append(r)

    resp = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = 'attachment; filename="reports.xlsx"'
    wb.save(resp)
    return resp

@login_required
def reports_export_pdf(request):
    date_from = parse_date(request.GET.get('from') or '')
    date_to   = parse_date(request.GET.get('to') or '')
    employee  = (request.GET.get('employee') or '').strip()
    kind      = (request.GET.get('kind') or '').strip()
    scope     = (request.GET.get('scope') or ('all' if request.user.is_superuser else 'mine')).strip()

    if request.user.is_superuser:
        base_filter = {} if scope == 'all' else {'card__created_by': request.user}
    else:
        base_filter = {'card__created_by': request.user}

    rows = []

    def _append(qs, kname, formatter, payments_rel, emp_model, emp_fk):
        qs = _date_filter_using_acc(qs.filter(**base_filter), date_from, date_to)
        if employee:
            qs = qs.filter(**{f'{payments_rel}__employee_name__icontains': employee})
        qs = qs.annotate(last_emp=_latest_emp_subquery(emp_model, emp_fk))
        qs = _with_acc_date(qs).select_related('card')
        for r in qs[:2000]:
            rows.append({
                'type': kname,
                'ref': getattr(r, 'booking_ref', '') or '',
                'voucher': getattr(r, 'voucher_code', '') or '',
                'employee': r.last_emp or '-',
                'customer': r.card.customer_name if getattr(r, 'card_id', None) else '',
                'created': r.acc_date,
                'extra': formatter(r),
            })

    if kind in ('hotel',''):
        _append(HotelBooking.objects.all(),'Hotel',
                lambda r:f'{r.hotel_name or "-"} / {getattr(r,"country","-") or "-"}',
                'payments', Payment, 'booking_hotel')
    if kind in ('flight',''):
        _append(FlightBooking.objects.all(),'Flight',
                lambda r:f'{getattr(r,"airline","-")} / {getattr(r,"pnr","-")}',
                'payments', FlightPayment, 'booking_flight')
    if kind in ('other',''):
        _append(OtherBooking.objects.all(),'Other',
                lambda r:f'{r.get_service_type_display()} / {r.provider_name or "-"}',
                'payments', OtherPayment, 'booking_other')

    rows.sort(key=lambda x: x['created'] or timezone.localdate(), reverse=True)

    pdf_bytes = _render_pdf_from_template('core/reports_pdf.html', {
        'rows': rows,
        'q_from': request.GET.get('from',''),
        'q_to': request.GET.get('to',''),
        'q_employee': employee,
        'q_kind': kind,
        'scope': scope,
        'generated_at': timezone.now(),
        'user': request.user,
    }, request)

    if pdf_bytes is None:
        return HttpResponse("PDF render error", status=500)

    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = 'attachment; filename="reports.pdf"'
    return resp


# ===================== Misc =====================

def not_implemented(request, *args, **kwargs):
    return HttpResponse("🚧 تحت الإنشاء: لم يتم تفعيل هذا القسم بعد.")

@login_required
def dashboard_overview(request):
    return render(request, "core/dashboard_overview.html", {})

# تعديل/حذف دفعات الفندق (صلاحيات/24ساعة)
@login_required
def payment_edit(request, payment_pk):
    payment = get_object_or_404(Payment, pk=payment_pk)
    booking = payment.booking_hotel

    if not request.user.is_superuser:
        messages.error(request, "ليس لديك صلاحية لتعديل الدفعات.")
        return redirect('card_detail', pk=booking.card_id)

    if not payment.is_editable:
        messages.error(request, "لا يمكن تعديل هذه الدفعة بعد مرور 24 ساعة.")
        return redirect('card_detail', pk=booking.card_id)

    if request.method == 'POST':
        form = PaymentForm(request.POST, request.FILES, instance=payment, booking=booking)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تعديل الدفعة بنجاح.")
            return redirect('card_detail', pk=booking.card_id)
    else:
        form = PaymentForm(instance=payment, booking=booking)

    return render(request, 'core/payment_edit_form.html', {'form': form, 'payment': payment})

@login_required
@require_POST
def payment_delete(request, payment_pk):
    payment = get_object_or_404(Payment, pk=payment_pk)
    card_id = payment.booking_hotel.card_id

    if not request.user.is_superuser:
        messages.error(request, "ليس لديك صلاحية لحذف الدفعات.")
        return redirect('card_detail', pk=card_id)

    if not payment.is_editable:
        messages.error(request, "لا يمكن حذف هذه الدفعة بعد مرور 24 ساعة.")
        return redirect('card_detail', pk=card_id)

    payment.delete()
    messages.success(request, "تم حذف الدفعة بنجاح.")
    return redirect('card_detail', pk=card_id)


# ===================== Reports Analysis =====================

@login_required
def reports_analysis(request):
    # ===== فلاتر التاريخ + الصلاحيات =====
    q_from = (request.GET.get("from") or "").strip()
    q_to   = (request.GET.get("to") or "").strip()
    date_from = parse_date(q_from) if q_from else None
    date_to   = parse_date(q_to) if q_to else None
    today = timezone.localdate()

    if request.user.is_superuser:
        base_b = {}
        base_p = {}
        can_choose_scope = True
    else:
        emp = (request.user.get_full_name() or request.user.username or "").strip()
        base_b = {"employee_name__iexact": emp}
        base_p = {"employee_name__iexact": emp}
        can_choose_scope = False

    scope = request.GET.get("scope") or ("all" if request.user.is_superuser else "mine")
    if request.user.is_superuser and scope == "mine":
        emp = (request.user.get_full_name() or request.user.username or "").strip()
        base_b = {"employee_name__iexact": emp}
        base_p = {"employee_name__iexact": emp}

    # ===== مصادر الحجوزات =====
    h = HotelBooking.objects.filter(**base_b).select_related("card")
    f = FlightBooking.objects.filter(**base_b).select_related("card")
    o = OtherBooking.objects.filter(**base_b).select_related("card")

    if date_from:
        h = h.filter(booking_date__gte=date_from)
        f = f.filter(booking_date__gte=date_from)
        o = o.filter(booking_date__gte=date_from)
    if date_to:
        h = h.filter(booking_date__lte=date_to)
        f = f.filter(booking_date__lte=date_to)
        o = o.filter(booking_date__lte=date_to)

    # ===== رانك الموظفين (كامل) =====
    rows = defaultdict(lambda: {"sell": D0, "net": D0, "count": 0, "paid": D0})

    # دمج الفنادق/الطيران/أخرى
    for r in h.values("employee_name").annotate(sell=_sumdec("sell"), net=_sumdec("net"), cnt=Count("id")):
        k = (r["employee_name"] or "—").strip()
        rows[k]["sell"] += r["sell"]; rows[k]["net"] += r["net"]; rows[k]["count"] += r["cnt"]

    for r in f.values("employee_name").annotate(sell=_sumdec("sell_price"), net=_sumdec("net_price"), cnt=Count("id")):
        k = (r["employee_name"] or "—").strip()
        rows[k]["sell"] += r["sell"]; rows[k]["net"] += r["net"]; rows[k]["count"] += r["cnt"]

    for r in o.values("employee_name").annotate(sell=_sumdec("sell_price"), net=_sumdec("net_price"), cnt=Count("id")):
        k = (r["employee_name"] or "—").strip()
        rows[k]["sell"] += r["sell"]; rows[k]["net"] += r["net"]; rows[k]["count"] += r["cnt"]

    # تحصيلات
    ph = Payment.objects.filter(**base_p)
    pf = FlightPayment.objects.filter(**base_p)
    po = OtherPayment.objects.filter(**base_p)
    if date_from:
        ph = ph.filter(installment_date__gte=date_from)
        pf = pf.filter(installment_date__gte=date_from)
        po = po.filter(installment_date__gte=date_from)
    if date_to:
        ph = ph.filter(installment_date__lte=date_to)
        pf = pf.filter(installment_date__lte=date_to)
        po = po.filter(installment_date__lte=date_to)

    for r in ph.values("employee_name").annotate(paid=_sumdec("paid_amount")):
        k = (r["employee_name"] or "—").strip(); rows[k]["paid"] += r["paid"]
    for r in pf.values("employee_name").annotate(paid=_sumdec("paid_amount")):
        k = (r["employee_name"] or "—").strip(); rows[k]["paid"] += r["paid"]
    for r in po.values("employee_name").annotate(paid=_sumdec("paid_amount")):
        k = (r["employee_name"] or "—").strip(); rows[k]["paid"] += r["paid"]

    emp_rank = []
    for emp_name, d in rows.items():
        sell, net, cnt, paid = d["sell"], d["net"], d["count"], d["paid"]
        profit = sell - net
        remaining = sell - paid
        score = (profit * Decimal("0.5")) + (Decimal(cnt) * Decimal("0.3")) + (sell * Decimal("0.2"))
        emp_rank.append({
            "employee": emp_name, "count": cnt, "sell": sell, "net": net,
            "profit": profit, "paid": paid, "remaining": remaining, "score": score
        })

    sort = request.GET.get("sort") or "profit"
    direction = request.GET.get("dir") or "desc"
    reverse = (direction != "asc")
    if sort not in {"profit","sell","count","paid","remaining","score","employee","net"}:
        sort = "profit"
    emp_rank.sort(key=lambda r: (r[sort], r["sell"]) if sort != "employee" else r["employee"], reverse=reverse)

    emp_labels = [r["employee"] for r in emp_rank]
    emp_profit = [float(r["profit"]) for r in emp_rank]
    emp_sell   = [float(r["sell"])   for r in emp_rank]
    emp_count  = [int(r["count"])    for r in emp_rank]

    # ===== Sales Mix =====
    mix_sell = {
        "فنادق": float(h.aggregate(v=_sumdec("sell"))["v"]),
        "طيران": float(f.aggregate(v=_sumdec("sell_price"))["v"]),
        "أخرى":  float(o.aggregate(v=_sumdec("sell_price"))["v"]),
    }
    mix_total = sum(mix_sell.values()) or 1.0
    mix_labels = list(mix_sell.keys())
    mix_values = [round(v, 2) for v in mix_sell.values()]
    mix_pct    = [round(v * 100.0 / mix_total, 2) for v in mix_values]

    # ===== المزوّدون =====
    TOP_N = int(request.GET.get("top") or 10)
    hotel_sup = list(h.values("provider_name").annotate(c=_count(), s=_sumdec("sell")).order_by("-c")[:TOP_N])
    other_sup = list(o.values("provider_name").annotate(c=_count(), s=_sumdec("sell_price")).order_by("-c")[:TOP_N])

    sup_agg = defaultdict(lambda: {"count":0, "sell":0.0})
    for r in hotel_sup:
        k = (r["provider_name"] or "—").strip()
        sup_agg[k]["count"] += int(r["c"] or 0); sup_agg[k]["sell"] += float(r["s"] or 0)
    for r in other_sup:
        k = (r["provider_name"] or "—").strip()
        sup_agg[k]["count"] += int(r["c"] or 0); sup_agg[k]["sell"] += float(r["s"] or 0)

    supplier_final = [{"supplier":k, "count":v["count"], "sell":round(v["sell"],2)} for k,v in sup_agg.items()]
    supplier_final.sort(key=lambda x: (x["count"], x["sell"]), reverse=True)
    supplier_chart_labels = [s["supplier"] for s in supplier_final[:TOP_N]]
    supplier_chart_values = [s["count"]   for s in supplier_final[:TOP_N]]

    # ===== تحليلات السوق =====
    top_nationalities = list(h.values("card__nationality").annotate(c=_count()).order_by("-c")[:TOP_N]) \
        or list(f.values("card__nationality").annotate(c=_count()).order_by("-c")[:TOP_N]) \
        or list(o.values("card__nationality").annotate(c=_count()).order_by("-c")[:TOP_N])
    nat_labels = [(r["card__nationality"] or "—") for r in top_nationalities]
    nat_values = [int(r["c"] or 0) for r in top_nationalities]

    top_countries = list(h.values("country").annotate(c=_count()).order_by("-c")[:TOP_N])
    country_labels = [(r["country"] or "—") for r in top_countries]
    country_values = [int(r["c"] or 0) for r in top_countries]

    top_hotels = list(h.values("hotel_name").annotate(c=_count()).order_by("-c")[:TOP_N])
    hotel_labels = [(r["hotel_name"] or "—") for r in top_hotels]
    hotel_values = [int(r["c"] or 0) for r in top_hotels]

    top_airlines = list(f.values("airline").annotate(c=_count()).order_by("-c")[:TOP_N])
    air_labels = [(r["airline"] or "—") for r in top_airlines]
    air_values = [int(r["c"] or 0) for r in top_airlines]

    return render(request, "core/reports_analysis.html", {
        "q_from": q_from, "q_to": q_to, "scope": scope, "can_choose_scope": can_choose_scope,
        "sort": request.GET.get("sort") or "profit", "dir": direction,
        "emp_rank": emp_rank,
        "emp_labels": emp_labels, "emp_profit": emp_profit, "emp_sell": emp_sell, "emp_count": emp_count,
        "mix_labels": mix_labels, "mix_values": mix_values, "mix_pct": mix_pct,
        "supplier_labels": supplier_chart_labels, "supplier_values": supplier_chart_values,
        "supplier_rows": supplier_final[:TOP_N],
        "nat_labels": nat_labels, "nat_values": nat_values,
        "country_labels": country_labels, "country_values": country_values,
        "hotel_labels": hotel_labels, "hotel_values": hotel_values,
        "air_labels": air_labels, "air_values": air_values,
        "TOP_N": TOP_N, "today": today,
    })

def _analysis_payload(request):
    """تجهيز نفس الداتا الظاهرة في شاشة reports_analysis للاستخدام في التصدير."""
    q_from = (request.GET.get("from") or "").strip()
    q_to   = (request.GET.get("to") or "").strip()
    date_from = parse_date(q_from) if q_from else None
    date_to   = parse_date(q_to) if q_to else None
    today = timezone.localdate()

    # الصلاحيات/النطاق
    if request.user.is_superuser:
        base_b = {}
        base_p = {}
    else:
        emp = (request.user.get_full_name() or request.user.username or "").strip()
        base_b = {"employee_name__iexact": emp}
        base_p = {"employee_name__iexact": emp}

    # QuerySets
    h = HotelBooking.objects.filter(**base_b).select_related("card")
    f = FlightBooking.objects.filter(**base_b).select_related("card")
    o = OtherBooking.objects.filter(**base_b).select_related("card")

    if date_from:
        h = h.filter(booking_date__gte=date_from)
        f = f.filter(booking_date__gte=date_from)
        o = o.filter(booking_date__gte=date_from)
    if date_to:
        h = h.filter(booking_date__lte=date_to)
        f = f.filter(booking_date__lte=date_to)
        o = o.filter(booking_date__lte=date_to)

    # --- تجميع الموظفين
    rows = defaultdict(lambda: {"sell": Decimal("0"), "net": Decimal("0"), "count": 0, "paid": Decimal("0")})

    for r in h.values("employee_name").annotate(sell=_sumdec("sell"), net=_sumdec("net"), cnt=Count("id")):
        k = (r["employee_name"] or "—").strip()
        rows[k]["sell"] += r["sell"]; rows[k]["net"] += r["net"]; rows[k]["count"] += r["cnt"]

    for r in f.values("employee_name").annotate(sell=_sumdec("sell_price"), net=_sumdec("net_price"), cnt=Count("id")):
        k = (r["employee_name"] or "—").strip()
        rows[k]["sell"] += r["sell"]; rows[k]["net"] += r["net"]; rows[k]["count"] += r["cnt"]

    for r in o.values("employee_name").annotate(sell=_sumdec("sell_price"), net=_sumdec("net_price"), cnt=Count("id")):
        k = (r["employee_name"] or "—").strip()
        rows[k]["sell"] += r["sell"]; rows[k]["net"] += r["net"]; rows[k]["count"] += r["cnt"]

    ph = Payment.objects.filter(**base_p)
    pf = FlightPayment.objects.filter(**base_p)
    po = OtherPayment.objects.filter(**base_p)
    if date_from:
        ph = ph.filter(installment_date__gte=date_from); pf = pf.filter(installment_date__gte=date_from); po = po.filter(installment_date__gte=date_from)
    if date_to:
        ph = ph.filter(installment_date__lte=date_to); pf = pf.filter(installment_date__lte=date_to); po = po.filter(installment_date__lte=date_to)

    for r in ph.values("employee_name").annotate(paid=_sumdec("paid_amount")):
        rows[(r["employee_name"] or "—").strip()]["paid"] += r["paid"]
    for r in pf.values("employee_name").annotate(paid=_sumdec("paid_amount")):
        rows[(r["employee_name"] or "—").strip()]["paid"] += r["paid"]
    for r in po.values("employee_name").annotate(paid=_sumdec("paid_amount")):
        rows[(r["employee_name"] or "—").strip()]["paid"] += r["paid"]

    emp_rank = []
    for emp_name, d in rows.items():
        sell, net, cnt, paid = d["sell"], d["net"], d["count"], d["paid"]
        profit = sell - net
        remaining = sell - paid
        score = (profit * Decimal("0.5")) + (Decimal(cnt) * Decimal("0.3")) + (sell * Decimal("0.2"))
        emp_rank.append({
            "employee": emp_name, "count": cnt, "sell": sell, "net": net,
            "profit": profit, "paid": paid, "remaining": remaining, "score": score
        })

    # --- Mix
    mix = {
        "فنادق": float(h.aggregate(v=_sumdec("sell"))["v"]),
        "طيران": float(f.aggregate(v=_sumdec("sell_price"))["v"]),
        "أخرى":  float(o.aggregate(v=_sumdec("sell_price"))["v"]),
    }

    # --- Providers
    TOP_N = int(request.GET.get("top") or 10)
    hotel_sup = list(h.values("provider_name").annotate(c=_count(), s=_sumdec("sell")).order_by("-c")[:TOP_N])
    other_sup = list(o.values("provider_name").annotate(c=_count(), s=_sumdec("sell_price")).order_by("-c")[:TOP_N])

    sup_agg = defaultdict(lambda: {"count":0, "sell":0.0})
    for r in hotel_sup:
        k = (r["provider_name"] or "—").strip()
        sup_agg[k]["count"] += int(r["c"] or 0); sup_agg[k]["sell"] += float(r["s"] or 0)
    for r in other_sup:
        k = (r["provider_name"] or "—").strip()
        sup_agg[k]["count"] += int(r["c"] or 0); sup_agg[k]["sell"] += float(r["s"] or 0)

    supplier_rows = [{"supplier":k, "count":v["count"], "sell":round(v["sell"],2)} for k,v in sup_agg.items()]
    supplier_rows.sort(key=lambda x: (x["count"], x["sell"]), reverse=True)

    # --- Market
    top_nationalities = list(h.values("card__nationality").annotate(c=_count()).order_by("-c")[:TOP_N]) \
        or list(f.values("card__nationality").annotate(c=_count()).order_by("-c")[:TOP_N]) \
        or list(o.values("card__nationality").annotate(c=_count()).order_by("-c")[:TOP_N])
    nat_rows = [((r["card__nationality"] or "—"), int(r["c"] or 0)) for r in top_nationalities]

    top_countries = list(h.values("country").annotate(c=_count()).order_by("-c")[:TOP_N])
    country_rows = [((r["country"] or "—"), int(r["c"] or 0)) for r in top_countries]

    top_hotels = list(h.values("hotel_name").annotate(c=_count()).order_by("-c")[:TOP_N])
    hotel_rows = [((r["hotel_name"] or "—"), int(r["c"] or 0)) for r in top_hotels]

    top_airlines = list(f.values("airline").annotate(c=_count()).order_by("-c")[:TOP_N])
    air_rows = [((r["airline"] or "—"), int(r["c"] or 0)) for r in top_airlines]

    return {
        "q_from": q_from, "q_to": q_to, "today": today, "TOP_N": TOP_N,
        "emp_rank": emp_rank,
        "supplier_rows": supplier_rows,
        "mix": mix,
        "nat_rows": nat_rows,
        "country_rows": country_rows,
        "hotel_rows": hotel_rows,
        "air_rows": air_rows,
    }

@login_required
def reports_analysis_export_xlsx(request):
    if Workbook is None:
        return HttpResponse("openpyxl غير مُثبت. ثبّته: pip install openpyxl", status=500)

    data = _analysis_payload(request)
    wb = Workbook()
    ws = wb.active
    ws.title = "Employees"

    # Sheet 1
    ws.append(["Employee","Bookings","Sell","Net","Profit","Paid","Remaining","Score"])
    for r in data["emp_rank"]:
        ws.append([
            r["employee"], int(r["count"]),
            float(r["sell"]), float(r["net"]), float(r["profit"]),
            float(r["paid"]), float(r["remaining"]), float(r["score"])
        ])

    # Sheet 2 Providers
    ws2 = wb.create_sheet("Providers")
    ws2.append(["Provider","COUNT","Sell"])
    for s in data["supplier_rows"]:
        ws2.append([s["supplier"], int(s["count"]), float(s["sell"])])

    # Sheet 3 Mix
    ws3 = wb.create_sheet("Sales Mix")
    ws3.append(["Type","Sell"])
    for k,v in data["mix"].items():
        ws3.append([k, float(v)])

    # Market sheets
    def add_tbl(name, rows):
        w = wb.create_sheet(name)
        w.append([name,"COUNT"])
        for label, c in rows:
            w.append([label, int(c)])
    add_tbl("Nationalities", data["nat_rows"])
    add_tbl("Countries",     data["country_rows"])
    add_tbl("Hotels",        data["hotel_rows"])
    add_tbl("Airlines",      data["air_rows"])

    # تنسيق عرض الأعمدة
    for sheet in wb.worksheets:
        for col in range(1, sheet.max_column+1):
            sheet.column_dimensions[get_column_letter(col)].width = 20

    out = io.BytesIO()
    wb.save(out); out.seek(0)
    filename = f"analysis_{data['q_from'] or 'all'}_{data['q_to'] or 'all'}.xlsx"
    resp = HttpResponse(
        out.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
# ===================== Performance Dashboard =====================

from django.http import HttpResponseForbidden
from django.shortcuts import redirect

@login_required
def performance_dashboard(request):
    """
    لوحة الأداء — ظاهرة فقط للسوبر والليدر والسوبرفايزر والمدير.
    الموظف العادي (agent) لا يراها ولا يستطيع دخولها.
    """
    # فحص الصلاحيات
    if not request.user.is_superuser:
        profile = getattr(request.user, "employee_profile", None)
        role = getattr(profile, "role", "").lower() if profile else ""
        allowed_roles = ["leader", "supervisor", "manager"]
        if role not in allowed_roles:
            # لو عايز تمنع الدخول برسالة:
            return HttpResponseForbidden("🚫 غير مصرح لك بالدخول إلى لوحة الأداء.")
            # أو لو تفضل إعادة توجيه للداشبورد بدل الخطأ:
            # return redirect("dashboard")

    # فلاتر
    q_from = (request.GET.get("from") or "").strip()
    q_to   = (request.GET.get("to")   or "").strip()
    sort   = (request.GET.get("sort") or "profit").strip()
    direction = (request.GET.get("dir") or "desc").strip()
    reverse = (direction != "asc")
    date_from = parse_date(q_from) if q_from else None
    date_to   = parse_date(q_to) if q_to else None
    today = timezone.localdate()

    # مصادر البيانات
    h = HotelBooking.objects.all().select_related("card")
    f = FlightBooking.objects.all().select_related("card")
    o = OtherBooking.objects.all().select_related("card")
    if date_from:
        h = h.filter(booking_date__gte=date_from)
        f = f.filter(booking_date__gte=date_from)
        o = o.filter(booking_date__gte=date_from)
    if date_to:
        h = h.filter(booking_date__lte=date_to)
        f = f.filter(booking_date__lte=date_to)
        o = o.filter(booking_date__lte=date_to)

    # تجميع حسب الموظف
    rows_map = defaultdict(lambda: {"sell": D0, "net": D0, "count": 0, "paid": D0})

    for r in h.values("employee_name").annotate(s=_sumdec("sell"), n=_sumdec("net"), c=Count("id")):
        k = (r["employee_name"] or "—").strip()
        rows_map[k]["sell"] += r["s"]; rows_map[k]["net"] += r["n"]; rows_map[k]["count"] += r["c"]
    for r in f.values("employee_name").annotate(s=_sumdec("sell_price"), n=_sumdec("net_price"), c=Count("id")):
        k = (r["employee_name"] or "—").strip()
        rows_map[k]["sell"] += r["s"]; rows_map[k]["net"] += r["n"]; rows_map[k]["count"] += r["c"]
    for r in o.values("employee_name").annotate(s=_sumdec("sell_price"), n=_sumdec("net_price"), c=Count("id")):
        k = (r["employee_name"] or "—").strip()
        rows_map[k]["sell"] += r["s"]; rows_map[k]["net"] += r["n"]; rows_map[k]["count"] += r["c"]

    # تحصيلات
    ph = Payment.objects.all()
    pf = FlightPayment.objects.all()
    po = OtherPayment.objects.all()
    if date_from:
        ph = ph.filter(installment_date__gte=date_from)
        pf = pf.filter(installment_date__gte=date_from)
        po = po.filter(installment_date__gte=date_from)
    if date_to:
        ph = ph.filter(installment_date__lte=date_to)
        pf = pf.filter(installment_date__lte=date_to)
        po = po.filter(installment_date__lte=date_to)

    for r in ph.values("employee_name").annotate(p=_sumdec("paid_amount")):
        rows_map[(r["employee_name"] or "—").strip()]["paid"] += r["p"]
    for r in pf.values("employee_name").annotate(p=_sumdec("paid_amount")):
        rows_map[(r["employee_name"] or "—").strip()]["paid"] += r["p"]
    for r in po.values("employee_name").annotate(p=_sumdec("paid_amount")):
        rows_map[(r["employee_name"] or "—").strip()]["paid"] += r["p"]

    # بناء الصفوف والترتيب
    rows = []
    for emp_name, d in rows_map.items():
        sell, net, cnt, paid = d["sell"], d["net"], d["count"], d["paid"]
        profit = sell - net
        remaining = sell - paid
        rows.append({
            "employee": emp_name,
            "count": cnt,
            "sell": sell, "net": net,
            "profit": profit, "paid": paid, "remaining": remaining,
        })

    if sort not in {"profit","sell","count","paid","remaining","employee","net"}:
        sort = "profit"
    rows.sort(key=lambda r: (r[sort], r["sell"]) if sort != "employee" else r["employee"], reverse=reverse)

    # المؤشرات الإجمالية
    kpis = {
        "total_sell":      sum((r["sell"]      or D0) for r in rows),
        "total_net":       sum((r["net"]       or D0) for r in rows),
        "total_profit":    sum((r["profit"]    or D0) for r in rows),
        "total_paid":      sum((r["paid"]      or D0) for r in rows),
        "total_remaining": sum((r["remaining"] or D0) for r in rows),
    }

    # الرسم البياني
    labels = [r["employee"] for r in rows]
    if sort == "sell":
        values = [float(r["sell"]) for r in rows]
    elif sort == "count":
        values = [int(r["count"]) for r in rows]
    elif sort == "paid":
        values = [float(r["paid"]) for r in rows]
    elif sort == "remaining":
        values = [float(r["remaining"]) for r in rows]
    elif sort == "net":
        values = [float(r["net"]) for r in rows]
    else:
        values = [float(r["profit"]) for r in rows]

    return render(request, "core/performance.html", {
        "q_from": q_from, "q_to": q_to,
        "sort": sort, "dir": direction, "today": today,
        "kpis": kpis, "rows": rows,
        "labels": labels, "values": values,
    })


@login_required
def performance_export_xlsx(request):
    """نفس فكرة لوحة الأداء — مسموح فقط للسوبر والليدر والسوبرفايزر والمدير"""
    if not request.user.is_superuser:
        profile = getattr(request.user, "employee_profile", None)
        role = getattr(profile, "role", "").lower() if profile else ""
        if role not in ["leader", "supervisor", "manager"]:
            return HttpResponseForbidden("🚫 غير مصرح بتصدير بيانات الأداء.")

    if Workbook is None:
        return HttpResponse("openpyxl غير مُثبت. ثبّته: pip install openpyxl", status=500)

    q_from = (request.GET.get("from") or "").strip()
    q_to   = (request.GET.get("to") or "").strip()
    date_from = parse_date(q_from) if q_from else None
    date_to   = parse_date(q_to) if q_to else None

    h = HotelBooking.objects.all()
    f = FlightBooking.objects.all()
    o = OtherBooking.objects.all()
    if date_from:
        h = h.filter(booking_date__gte=date_from); f = f.filter(booking_date__gte=date_from); o = o.filter(booking_date__gte=date_from)
    if date_to:
        h = h.filter(booking_date__lte=date_to); f = f.filter(booking_date__lte=date_to); o = o.filter(booking_date__lte=date_to)

    rows = defaultdict(lambda: {"sell": D0, "net": D0, "count": 0, "paid": D0})
    for r in h.values("employee_name").annotate(sell=_sumdec("sell"), net=_sumdec("net"), cnt=Count("id")):
        k = (r["employee_name"] or "—").strip(); rows[k]["sell"] += r["sell"]; rows[k]["net"] += r["net"]; rows[k]["count"] += r["cnt"]
    for r in f.values("employee_name").annotate(sell=_sumdec("sell_price"), net=_sumdec("net_price"), cnt=Count("id")):
        k = (r["employee_name"] or "—").strip(); rows[k]["sell"] += r["sell"]; rows[k]["net"] += r["net"]; rows[k]["count"] += r["cnt"]
    for r in o.values("employee_name").annotate(sell=_sumdec("sell_price"), net=_sumdec("net_price"), cnt=Count("id")):
        k = (r["employee_name"] or "—").strip(); rows[k]["sell"] += r["sell"]; rows[k]["net"] += r["net"]; rows[k]["count"] += r["cnt"]

    ph = Payment.objects.all(); pf = FlightPayment.objects.all(); po = OtherPayment.objects.all()
    if date_from: ph = ph.filter(installment_date__gte=date_from); pf = pf.filter(installment_date__gte=date_from); po = po.filter(installment_date__gte=date_from)
    if date_to:   ph = ph.filter(installment_date__lte=date_to); pf = pf.filter(installment_date__lte=date_to); po = po.filter(installment_date__lte=date_to)
    for r in ph.values("employee_name").annotate(paid=_sumdec("paid_amount")):
        k = (r["employee_name"] or "—").strip(); rows[k]["paid"] += r["paid"]
    for r in pf.values("employee_name").annotate(paid=_sumdec("paid_amount")):
        k = (r["employee_name"] or "—").strip(); rows[k]["paid"] += r["paid"]
    for r in po.values("employee_name").annotate(paid=_sumdec("paid_amount")):
        k = (r["employee_name"] or "—").strip(); rows[k]["paid"] += r["paid"]

    wb = Workbook(); ws = wb.active; ws.title = "Performance"
    ws.append(["Employee","Bookings","Sell","Net","Profit","Paid","Remaining"])
    for emp_name, d in rows.items():
        sell, net, cnt, paid = d["sell"], d["net"], d["count"], d["paid"]
        profit = sell - net; remaining = sell - paid
        ws.append([emp_name, int(cnt), float(sell), float(net), float(profit), float(paid), float(remaining)])
    for col in range(1, ws.max_column+1):
        ws.column_dimensions[get_column_letter(col)].width = 16

    resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="performance.xlsx"'
    wb.save(resp)
    return resp


# ===================== Suppliers Report =====================

@login_required
def suppliers_report(request):
    # فلاتر
    q_from = (request.GET.get("from") or "").strip()
    q_to   = (request.GET.get("to") or "").strip()
    top_n  = int(request.GET.get("top") or 10)

    date_from = parse_date(q_from) if q_from else None
    date_to   = parse_date(q_to) if q_to else None

    # الصلاحيات
    if request.user.is_superuser:
        base_b = {}
    else:
        emp = (request.user.get_full_name() or request.user.username or "").strip()
        base_b = {"employee_name__iexact": emp}

    # مصادر البيانات (فنادق + خدمات أخرى)
    h = HotelBooking.objects.filter(**base_b)
    o = OtherBooking.objects.filter(**base_b)

    if date_from:
        h = h.filter(booking_date__gte=date_from)
        o = o.filter(booking_date__gte=date_from)
    if date_to:
        h = h.filter(booking_date__lte=date_to)
        o = o.filter(booking_date__lte=date_to)

    # تجميع حسب المزوّد
    agg = defaultdict(lambda: {"count": 0, "sell": Decimal("0.00"), "net": Decimal("0.00")})

    for r in _with_acc_date(h).values("provider_name").annotate(
        c=Count("id"),
        s=Coalesce(Sum("sell"), D0, output_field=DecimalField(max_digits=14, decimal_places=2)),
        n=Coalesce(Sum("net"),  D0, output_field=DecimalField(max_digits=14, decimal_places=2)),
    ):
        k = (r["provider_name"] or "—").strip()
        agg[k]["count"] += int(r["c"] or 0)
        agg[k]["sell"]  += (r["s"] or D0)
        agg[k]["net"]   += (r["n"] or D0)

    for r in _with_acc_date(o).values("provider_name").annotate(
        c=Count("id"),
        s=Coalesce(Sum("sell_price"), D0, output_field=DecimalField(max_digits=14, decimal_places=2)),
        n=Coalesce(Sum("net_price"),  D0, output_field=DecimalField(max_digits=14, decimal_places=2)),
    ):
        k = (r["provider_name"] or "—").strip()
        agg[k]["count"] += int(r["c"] or 0)
        agg[k]["sell"]  += (r["s"] or D0)
        agg[k]["net"]   += (r["n"] or D0)

    rows = []
    for k, v in agg.items():
        rows.append({"supplier": k, "count": v["count"], "sell": v["sell"], "net": v["net"], "profit": v["sell"] - v["net"]})
    rows.sort(key=lambda x: (x["count"], x["profit"]), reverse=True)

    # للرسم (Top N)
    chart_rows = rows[:top_n]
    labels = [r["supplier"] for r in chart_rows]
    values = [int(r["count"]) for r in chart_rows]

    # KPI بسيط
    kpis = {
        "total_suppliers": len(rows),
        "total_sell": sum((r["sell"] for r in rows), start=Decimal("0.00")),
        "total_count": sum((r["count"] for r in rows), start=0),
    }

    return render(request, "core/suppliers.html", {
        "q_from": q_from, "q_to": q_to, "top_n": top_n,
        "rows": rows,
        "chart_labels": labels, "chart_values": values,
        "kpis": kpis,
        "today": timezone.localdate(),
    })

@login_required
def suppliers_export_xlsx(request):
    if Workbook is None:
        return HttpResponse("openpyxl غير مُثبت. ثبّته: pip install openpyxl", status=500)

    # نفس فلاتر الصفحة
    q_from = (request.GET.get("from") or "").strip()
    q_to   = (request.GET.get("to") or "").strip()

    date_from = parse_date(q_from) if q_from else None
    date_to   = parse_date(q_to) if q_to else None

    # الصلاحيات
    if request.user.is_superuser:
        base_b = {}
    else:
        emp = (request.user.get_full_name() or request.user.username or "").strip()
        base_b = {"employee_name__iexact": emp}

    h = HotelBooking.objects.filter(**base_b)
    o = OtherBooking.objects.filter(**base_b)

    if date_from:
        h = h.filter(booking_date__gte=date_from)
        o = o.filter(booking_date__gte=date_from)
    if date_to:
        h = h.filter(booking_date__lte=date_to)
        o = o.filter(booking_date__lte=date_to)

    agg = defaultdict(lambda: {"count": 0, "sell": Decimal("0.00"), "net": Decimal("0.00")})

    for r in _with_acc_date(h).values("provider_name").annotate(
        c=Count("id"),
        s=Coalesce(Sum("sell"), D0, output_field=DecimalField(max_digits=14, decimal_places=2)),
        n=Coalesce(Sum("net"),  D0, output_field=DecimalField(max_digits=14, decimal_places=2)),
    ):
        k = (r["provider_name"] or "—").strip()
        agg[k]["count"] += int(r["c"] or 0)
        agg[k]["sell"]  += (r["s"] or D0)
        agg[k]["net"]   += (r["n"] or D0)

    for r in _with_acc_date(o).values("provider_name").annotate(
        c=Count("id"),
        s=Coalesce(Sum("sell_price"), D0, output_field=DecimalField(max_digits=14, decimal_places=2)),
        n=Coalesce(Sum("net_price"),  D0, output_field=DecimalField(max_digits=14, decimal_places=2)),
    ):
        k = (r["provider_name"] or "—").strip()
        agg[k]["count"] += int(r["c"] or 0)
        agg[k]["sell"]  += (r["s"] or D0)
        agg[k]["net"]   += (r["n"] or D0)

    rows = [{"supplier": k, "count": v["count"], "sell": v["sell"], "net": v["net"], "profit": (v["sell"] - v["net"])} for k, v in agg.items()]
    rows.sort(key=lambda x: (x["count"], x["profit"]), reverse=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Suppliers"
    ws.append(["Supplier", "COUNT", "Sell", "Net", "Profit"])
    for r in rows:
        ws.append([r["supplier"], int(r["count"]), float(r["sell"]), float(r["net"]), float(r["profit"])])
    for col in range(1, 6):
        ws.column_dimensions[get_column_letter(col)].width = 22

    out = io.BytesIO()
    wb.save(out); out.seek(0)
    filename = f"suppliers_{q_from or 'all'}_{q_to or 'all'}.xlsx"
    resp = HttpResponse(out.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp

# ===== Global Search (Cards + Bookings) =====
from django.db.models import Q
from django.shortcuts import render, redirect
from django.urls import reverse
from .models import UniBookingCard as Card
from django.contrib.auth.decorators import login_required

def _pick_field(model, candidates):
    if not model:
        return None
    names = {f.name for f in model._meta.get_fields()}
    for c in candidates:
        if c in names:
            return c
    return None

def _norm_phone(s: str) -> str:
    if not s:
        return ""
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    s = s.translate(trans)
    return "".join(ch for ch in s if ch.isdigit())

@login_required
def global_search(request):
    q = (request.GET.get("q") or "").strip()
    if not q:
        return redirect("dashboard")

    q_lower = q.lower()
    phone = _norm_phone(q)

    results = {"cards": [], "customers": [], "hotels": [], "flights": [], "others": []}

    # ================= Cards =================
    cards_qs = []
    CardModel = Card  # استخدم الـ alias اللي استوردناه
    if CardModel:
        name_f  = _pick_field(CardModel, ["customer_name", "name", "client_name", "full_name"])
        code_f  = _pick_field(CardModel, ["ub_code", "code", "card_code"])
        phone_f = _pick_field(CardModel, ["mobile", "phone", "phone_number"])
        id_f    = _pick_field(CardModel, ["id", "pk"]) or "id"

        filters = Q()
        if name_f:
            filters |= Q(**{f"{name_f}__icontains": q})
        if code_f:
            filters |= (
                Q(**{f"{code_f}__iexact": q}) |
                Q(**{f"{code_f}__icontains": q}) |
                Q(**{f"{code_f}__istartswith": q})
            )
            if q_lower.startswith("u"):
                filters |= Q(**{f"{code_f}__istartswith": q})
        if phone and phone_f:
            filters |= Q(**{f"{phone_f}__icontains": phone})

        if filters:
            cards_qs = list(CardModel.objects.filter(filters).order_by(f"-{id_f}")[:50])

        for c in cards_qs:
            try:
                url = reverse("card_detail", args=[getattr(c, id_f)])
            except Exception:
                url = "#"
            title = getattr(c, name_f, None) or f"Card #{getattr(c, id_f)}"
            sub_parts = []
            if code_f and getattr(c, code_f, None):
                sub_parts.append(f"كود: {getattr(c, code_f)}")
            if phone_f and getattr(c, phone_f, None):
                sub_parts.append(f"موبايل: {getattr(c, phone_f)}")
            results["cards"].append({"title": title, "sub": " — ".join(sub_parts), "url": url})

    # ===== Helper: البحث في الحجوزات (نفتح الكارت المرتبط) =====
    def search_booking(Model, nice_name):
        if not Model:
            return [], []
        ref_f   = _pick_field(Model, [
            "voucher_code", "pnr", "reference", "ref", "booking_code", "provider_ref", "voucher", "mark", "code"
        ])
        name_f  = _pick_field(Model, ["customer_name", "passenger_name", "client_name", "name"])
        phone_f = _pick_field(Model, ["mobile", "phone", "phone_number"])
        card_f  = _pick_field(Model, ["card", "sales_card", "salescard"])

        filters = Q()
        if ref_f:
            filters |= Q(**{f"{ref_f}__icontains": q})
            if q_lower[:1] in ("h", "f", "o"):
                filters |= Q(**{f"{ref_f}__istartswith": q})
        if name_f:
            filters |= Q(**{f"{name_f}__icontains": q})
        if phone and phone_f:
            filters |= Q(**{f"{phone_f}__icontains": phone})

        if not filters:
            return [], []

        qs = Model.objects.filter(filters)
        if card_f:
            qs = qs.select_related(card_f)
        qs = qs.order_by("-id")[:50]

        items, extracted_cards = [], []
        for b in qs:
            url = "#"
            card_obj = getattr(b, card_f, None) if card_f else None
            if card_obj is not None:
                try:
                    url = reverse("card_detail", args=[getattr(card_obj, "id")])
                except Exception:
                    url = "#"
                extracted_cards.append(card_obj)

            title = nice_name
            if ref_f and getattr(b, ref_f, None):
                title += f" — {getattr(b, ref_f)}"
            sub = getattr(b, name_f, "") if name_f else ""
            items.append({"title": title, "sub": sub, "url": url})
        return items, extracted_cards

    # ================= Hotels / Flights / Others =================
    hotels_items,  hotels_cards  = search_booking(HotelBooking,  "حجز فندق")
    flights_items, flights_cards = search_booking(FlightBooking, "حجز طيران")
    others_items,  others_cards  = search_booking(OtherBooking,  "خدمة أخرى")

    results["hotels"]  = hotels_items
    results["flights"] = flights_items
    results["others"]  = others_items

    # لو مافيش كروت مباشرة، أضف كروت مستخلصة من الحجوزات
    if not results["cards"] and CardModel:
        seen = set(getattr(c, "id", None) for c in cards_qs)
        for c in (hotels_cards + flights_cards + others_cards):
            cid = getattr(c, "id", None)
            if not cid or cid in seen:
                continue
            seen.add(cid)
            name_f  = _pick_field(CardModel, ["customer_name", "name", "client_name", "full_name"])
            code_f  = _pick_field(CardModel, ["ub_code", "code", "card_code"])
            phone_f = _pick_field(CardModel, ["mobile", "phone", "phone_number"])
            try:
                url = reverse("card_detail", args=[cid])
            except Exception:
                url = "#"
            title = getattr(c, name_f, None) or f"Card #{cid}"
            sub_parts = []
            if code_f and getattr(c, code_f, None):
                sub_parts.append(f"كود: {getattr(c, code_f)}")
            if phone_f and getattr(c, phone_f, None):
                sub_parts.append(f"موبايل: {getattr(c, phone_f)}")
            results["cards"].append({"title": title, "sub": " — ".join(sub_parts), "url": url})

    return render(request, "core/search_results.html", {"q": q, "results": results})


User = get_user_model()

@login_required
def employees_list(request):
    dep_code = (request.GET.get("dep") or "").strip()  # مثال: ?dep=sales
    departments = Department.objects.all().order_by("name")

    qs = User.objects.filter(is_active=True).select_related("profile")
    if dep_code:
        qs = qs.filter(profile__department__code__iexact=dep_code)

    # فلتر إضافي بالاسم (اختياري): ?q=ali
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(username__icontains=q)   | Q(email__icontains=q)
        )

    qs = qs.order_by("first_name", "last_name", "username")
    return render(request, "core/employees_list.html", {
        "departments": departments,
        "current_dep": dep_code,
        "q": q,
        "users": qs[:500],  # سقف معقول للعرض
    })


# ===================== Amendments (طلبات التعديل) =====================

# خريطة الموديلات حسب النوع المستخدم في الروابط
MODEL_MAP = {
    "hotel": HotelBooking,
    "flight": FlightBooking,
    "other": OtherBooking,
}

# core/views.py
from django.urls import reverse

@login_required
def amendment_create(request, model, pk):
    Model = MODEL_MAP.get(model)
    if not Model:
        return render(request, "core/404.html", status=404)

    booking = get_object_or_404(Model, pk=pk)
    ct = ContentType.objects.get_for_model(Model)

    if request.method == "POST":
        form = BookingAmendmentForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.booking_content_type = ct
            obj.booking_object_id = booking.pk
            obj.requested_by = request.user
            obj.save()
            messages.success(request, "تم إنشاء طلب التعديل.")
            return redirect("amendment_list", model=model, pk=booking.pk)
    else:
        form = BookingAmendmentForm()

    back_url = reverse("amendment_list", kwargs={"model": model, "pk": booking.pk})
    return render(request, "amendments/form.html", {
        "form": form,
        "booking": booking,
        "model": model,
        "back_url": back_url,
    })

@login_required
def amendment_list(request, model, pk):
    Model = MODEL_MAP.get(model)
    if Model is None:
        return render(request, "core/404.html", status=404)

    booking = get_object_or_404(Model, pk=pk)
    ct = ContentType.objects.get_for_model(Model)

    qs = BookingAmendment.objects.filter(
        booking_content_type=ct,
        booking_object_id=booking.pk,
    ).order_by("-id")

    # برضه غيّرنا المسار إلى templates/amendments/
    return render(request, "amendments/list.html", {"booking": booking, "amendments": qs})


@login_required
def amendment_apply(request, pk):
    """تطبيق التعديل: نحاول نحدث الحقول إن كانت موجودة في الموديل، ثم نرجّع للقائمة."""
    amend = get_object_or_404(BookingAmendment, pk=pk)

    changed = False
    # الحقول اختيارية—نحدّث بس لو موجودة عندك في الموديل
    if hasattr(amend, "status") and getattr(amend, "status") != "applied":
        amend.status = "applied"
        changed = True
    if hasattr(amend, "applied_by") and not getattr(amend, "applied_by_id", None):
        amend.applied_by = request.user
        changed = True
    if hasattr(amend, "applied_at") and not getattr(amend, "applied_at", None):
        amend.applied_at = timezone.now()
        changed = True
    if changed:
        amend.save()
        messages.success(request, "تم تطبيق التعديل.")

    # نرجع لنفس شاشة لستة التعديلات
    model_key = None
    target_model = amend.booking_content_type.model_class()
    for k, M in MODEL_MAP.items():
        if M is target_model:
            model_key = k
            break

    return redirect("amendment_list", model=model_key, pk=amend.booking_object_id)

from django.urls import reverse
from django.contrib import messages
from django.shortcuts import redirect

@login_required
def amendments_redirect(request, model, pk):
    # حوّل حسب نوع الحجز مع أنكر لفتح سكشن التسويات
    if model == "hotel":
        url = reverse("hotel_payment", kwargs={"booking_pk": pk})
    elif model == "flight":
        url = reverse("flight_payment", kwargs={"booking_pk": pk})
    elif model == "other":
        url = reverse("other_payment", kwargs={"pk": pk})
    else:
        messages.error(request, "نوع الحجز غير مدعوم.")
        return redirect("dashboard")
    return redirect(f"{url}?adjust=1#adjustments")

@login_required
def amendments_redirect_unknown(request, pk):
    messages.info(request, "تم نقل إدارة التعديلات إلى صفحة الدفع.")
    return redirect("dashboard")

from decimal import Decimal
from django.contrib import messages
from django.db.models import Sum, DecimalField, Value as V
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from .models import HotelBooking, Payment
from .forms import ModifyAdjustmentForm


@login_required
def hotel_payment_modify(request, booking_pk):
    booking = get_object_or_404(HotelBooking, pk=booking_pk)

    current_paid = booking.payments.aggregate(
        total=Coalesce(
            Sum(
                "paid_amount",
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            V(0, output_field=DecimalField(max_digits=12, decimal_places=2)),
        )
    )["total"] or Decimal("0.00")

    current_sell = booking.sell or Decimal("0.00")
    current_net = booking.net or Decimal("0.00")

    if request.method == "POST":
        form = ModifyAdjustmentForm(request.POST, request.FILES)
        if form.is_valid():
            dnet = form.cleaned_data.get("delta_net") or Decimal("0")
            dsell = form.cleaned_data.get("delta_sell") or Decimal("0")
            dpaid = form.cleaned_data.get("delta_paid") or Decimal("0")
            method = form.cleaned_data.get("method") or "cash"
            note = form.cleaned_data.get("note") or ""

            new_net = current_net + dnet
            new_sell = current_sell + dsell
            new_paid = current_paid + dpaid  # للعرض بس لو حابب

            if new_net < 0:
                form.add_error("delta_net", "لا يمكن أن يصبح صافي الشراء أقل من صفر.")
            if new_sell < 0:
                form.add_error("delta_sell", "لا يمكن أن يصبح سعر البيع أقل من صفر.")

            if form.errors:
                return render(
                    request,
                    "core/hotel_payment_modify.html",
                    {
                        "booking": booking,
                        "form": form,
                        "current_net": current_net,
                        "current_sell": current_sell,
                        "current_paid": current_paid,
                    },
                )

            # ✅ طبّق التغيير على الحجز
            booking.net = new_net
            booking.sell = new_sell
            booking.save()

            # ✅ لو فيه تغيير في المدفوع، سجّل Payment بموجب/سالب مع اسم الموظف + النوت
            if dpaid != 0:
                p = Payment(
                    booking_hotel=booking,
                    paid_amount=dpaid,  # سالب = استرداد
                    method=method,
                    payment_link=form.cleaned_data.get("payment_link") or "",
                    bank_file=form.cleaned_data.get("bank_file"),
                    invoice_file=form.cleaned_data.get("invoice_file"),
                    voucher_original=form.cleaned_data.get("voucher_original"),
                    employee_name=(
                        request.user.get_full_name() or request.user.username
                    ),
                    note=note or "تعديل دفعة من شاشة تعديل الدفع",
                )
                p.net_price = booking.net or Decimal("0")
                p.sell_price = booking.sell or Decimal("0")
                p.save()

            messages.success(request, "تم تنفيذ التعديل (جمع/طرح) بنجاح.")
            return redirect("hotel_payment", booking_pk=booking.pk)

    else:
        form = ModifyAdjustmentForm(initial={"method": "cash"})

    return render(
        request,
        "core/hotel_payment_modify.html",
        {
            "booking": booking,
            "form": form,
            "current_net": current_net,
            "current_sell": current_sell,
            "current_paid": current_paid,
        },
    )
@login_required
def flight_payment_modify(request, booking_pk):
    booking = get_object_or_404(FlightBooking, pk=booking_pk)

    # قيم حالية
    current_paid = booking.payments.aggregate(
        total=Coalesce(
            Sum("paid_amount", output_field=DecimalField(max_digits=12, decimal_places=2)),
            V(0, output_field=DecimalField(max_digits=12, decimal_places=2)),
        )
    )["total"] or Decimal("0.00")

    current_sell = booking.sell_price or Decimal("0.00")
    current_net  = booking.net_price  or Decimal("0.00")

    if request.method == "POST":
        form = ModifyAdjustmentForm(request.POST, request.FILES)
        if form.is_valid():
            dnet  = form.cleaned_data["delta_net"]  or Decimal("0")
            dsell = form.cleaned_data["delta_sell"] or Decimal("0")
            dpaid = form.cleaned_data["delta_paid"] or Decimal("0")
            method = form.cleaned_data.get("method")
            note   = form.cleaned_data.get("note") or ""

            # حساب الجديد
            new_net  = current_net  + dnet
            new_sell = current_sell + dsell

            # منع السالب
            if new_net < 0:
                form.add_error("delta_net", "لا يمكن أن يصبح صافي الشراء أقل من صفر.")
            if new_sell < 0:
                form.add_error("delta_sell", "لا يمكن أن يصبح سعر البيع أقل من صفر.")

            if form.errors:
                return render(request, "core/flight_payment_modify.html", {
                    "booking": booking,
                    "form": form,
                    "current_net": current_net,
                    "current_sell": current_sell,
                    "current_paid": current_paid,
                })

            # حفظ الأسعار الجديدة
            booking.net_price  = new_net
            booking.sell_price = new_sell
            booking.save()

            # لو في مدفوع موجب / سالب → سجل Payment
            if dpaid != 0:
                p = FlightPayment(
                    booking_flight=booking,
                    paid_amount=dpaid,
                    method=method or "cash",
                    payment_link=form.cleaned_data.get("payment_link") or "",
                    bank_file=form.cleaned_data.get("bank_file"),
                    invoice_file=form.cleaned_data.get("invoice_file"),
                    voucher_original=form.cleaned_data.get("voucher_original"),
                    employee_name=request.user.get_full_name() or request.user.username,
                    note=note or "تعديل دفعة من شاشة تعديل الدفع للطيران",
                )
                p.net_price  = booking.net_price
                p.sell_price = booking.sell_price
                p.save()

            messages.success(request, "تم تنفيذ التعديل بنجاح.")
            return redirect("flight_payment", booking_pk=booking.pk)

    else:
        form = ModifyAdjustmentForm(initial={"method": "cash"})

    return render(request, "core/flight_payment_modify.html", {
        "booking": booking,
        "form": form,
        "current_net": current_net,
        "current_sell": current_sell,
        "current_paid": current_paid,
    })
@login_required
def other_payment_modify(request, booking_pk):
    booking = get_object_or_404(OtherBooking, pk=booking_pk)

    current_paid = booking.payments.aggregate(
        total=Coalesce(
            Sum("paid_amount", output_field=DecimalField(max_digits=12, decimal_places=2)),
            V(0, output_field=DecimalField(max_digits=12, decimal_places=2)),
        )
    )["total"] or Decimal("0.00")

    current_sell = booking.sell_price or Decimal("0.00")
    current_net  = booking.net_price  or Decimal("0.00")

    if request.method == "POST":
        form = ModifyAdjustmentForm(request.POST, request.FILES)
        if form.is_valid():
            dnet  = form.cleaned_data["delta_net"]  or Decimal("0")
            dsell = form.cleaned_data["delta_sell"] or Decimal("0")
            dpaid = form.cleaned_data["delta_paid"] or Decimal("0")
            method = form.cleaned_data.get("method")
            note   = form.cleaned_data.get("note") or ""

            new_net  = current_net  + dnet
            new_sell = current_sell + dsell

            if new_net < 0:
                form.add_error("delta_net", "لا يمكن أن يكون النت أقل من صفر.")
            if new_sell < 0:
                form.add_error("delta_sell", "لا يمكن أن يكون البيع أقل من صفر.")

            if form.errors:
                return render(request, "core/other_payment_modify.html", {
                    "booking": booking,
                    "form": form,
                    "current_net": current_net,
                    "current_sell": current_sell,
                    "current_paid": current_paid,
                })

            booking.net_price  = new_net
            booking.sell_price = new_sell
            booking.save()

            if dpaid != 0:
                p = OtherPayment(
                    booking_other=booking,
                    paid_amount=dpaid,
                    method=method or "cash",
                    payment_link=form.cleaned_data.get("payment_link") or "",
                    bank_file=form.cleaned_data.get("bank_file"),
                    invoice_file=form.cleaned_data.get("invoice_file"),
                    voucher_original=form.cleaned_data.get("voucher_original"),
                    employee_name=request.user.get_full_name() or request.user.username,
                    note=note or "تعديل دفعة من شاشة التعديل",
                )
                p.net_price  = booking.net_price
                p.sell_price = booking.sell_price
                p.save()

            messages.success(request, "تم حفظ التعديل بنجاح.")
            return redirect("other_payment", booking_pk=booking.pk)

    else:
        form = ModifyAdjustmentForm(initial={"method": "cash"})

    return render(request, "core/other_payment_modify.html", {
        "booking": booking,
        "form": form,
        "current_net": current_net,
        "current_sell": current_sell,
        "current_paid": current_paid,
    })
