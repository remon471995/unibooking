import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import get_template
from django.views.decorators.http import require_POST

from core.models import FlightBooking
from core.permissions import can_edit_card

from .parser import parse_ticket_pdf
from .services import itinerary_block_reason, save_itinerary_from_post, voucher_context

MAX_UPLOAD = 8 * 1024 * 1024  # 8MB


@login_required
@require_POST
def parse_ticket(request):
    """بيستقبل PDF ويرجّع البيانات المستخرجة JSON (مابيحفظش حاجة، والملف مابيتخزنش)."""
    f = request.FILES.get("ticket")
    if not f:
        return JsonResponse({"ok": False, "error": "ما اخترتش ملف."}, status=400)
    if f.size > MAX_UPLOAD:
        return JsonResponse({"ok": False, "error": "الملف كبير (أقصى حجم 8 ميجا)."}, status=400)
    raw = f.read()
    if not raw.startswith(b"%PDF"):
        return JsonResponse({"ok": False, "error": "الملف لازم يكون PDF."}, status=400)
    data = parse_ticket_pdf(io.BytesIO(raw))
    return JsonResponse({"ok": bool(data.get("segments")), "data": data})


@login_required
def itinerary_upload(request, booking_pk):
    """رفع تذكرة لحجز طيران موجود (أو استبدال خط السير)."""
    booking = get_object_or_404(FlightBooking.objects.select_related("card"), pk=booking_pk)
    if not can_edit_card(request.user, booking.card):
        raise PermissionDenied
    reason = itinerary_block_reason(booking)
    if reason:  # الحجز مقفول أو خط السير متسجّل: ممنوع التغيير
        messages.error(request, reason)
        if hasattr(booking, "itinerary"):
            return redirect("flightdocs:voucher", booking_pk=booking.pk)
        return redirect("card_detail", pk=booking.card_id)
    if request.method == "POST":
        if save_itinerary_from_post(booking, request.POST.get("itinerary_json"), request.user):
            messages.success(request, "تم حفظ خط سير الرحلة.")
            return redirect("flightdocs:voucher", booking_pk=booking.pk)
        messages.error(request, "ما اتحفظش خط السير. ارفع التذكرة الأول وتأكد إن البيانات ظهرت.")
    return render(request, "flightdocs/itinerary_upload.html", {"booking": booking})


@login_required
def voucher(request, booking_pk):
    booking = get_object_or_404(FlightBooking.objects.select_related("card"), pk=booking_pk)
    ctx = voucher_context(booking)
    if ctx is None:
        if itinerary_block_reason(booking) is None and can_edit_card(request.user, booking.card):
            messages.info(request, "مفيش خط سير للحجز ده لسه. ارفع التذكرة الأول.")
            return redirect("flightdocs:upload", booking_pk=booking.pk)
        messages.info(request, "مفيش خط سير للحجز ده.")
        return redirect("card_detail", pk=booking.card_id)
    ctx["pdf"] = False
    ctx["can_replace"] = itinerary_block_reason(booking) is None and can_edit_card(request.user, booking.card)
    return render(request, "flightdocs/voucher.html", ctx)


@login_required
def voucher_pdf(request, booking_pk):
    from weasyprint import HTML  # نفس المكتبة المستخدمة في فاوتشر الفنادق

    booking = get_object_or_404(FlightBooking.objects.select_related("card"), pk=booking_pk)
    ctx = voucher_context(booking)
    if ctx is None:
        return redirect("card_detail", pk=booking.card_id)
    ctx["pdf"] = True
    html = get_template("flightdocs/voucher.html").render(ctx, request)
    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    resp = HttpResponse(pdf, content_type="application/pdf")
    ref = ctx["itinerary"].booking_ref or booking.pk
    resp["Content-Disposition"] = f'inline; filename="flight-voucher-{ref}.pdf"'
    return resp
