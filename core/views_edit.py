"""Edit the DETAILS of a booking (hotel / flight / other) while it is not approved yet.

Before the data entry approves, the agent may correct anything he typed wrong: the booking data, the guests,
the flight itinerary (flightdocs), the numbers (views_review.booking_fix) and the payments with their invoice /
voucher / payment link / proof (views_review.payment_fix).  The voucher is built from the live booking data, so a
correction shows on it at once.  Once the booking is approved it is locked: the agent has to ask for a change.
Every change is written to the review log (old -> new).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.forms import inlineformset_factory
from django.shortcuts import get_object_or_404, redirect, render

from .forms import FlightBookingForm, HotelBookingForm, OtherBookingForm, RoomForm
from .models import FlightBooking, HotelBooking, OtherBooking, ReviewFields, Room
from .views_review import METHOD_LABELS, _log, _may_fix

KINDS = {
    "hotel": (HotelBooking, HotelBookingForm, "فندق"),
    "flight": (FlightBooking, FlightBookingForm, "طيران"),
    "other": (OtherBooking, OtherBookingForm, "خدمة أخرى"),
}


def _diff(form):
    parts = []
    for name in form.changed_data:
        label = form.fields[name].label or name
        old, new = form.initial.get(name), form.cleaned_data.get(name)
        parts.append(f"{label}: {old if old not in (None, '') else '—'} → {new if new not in (None, '') else '—'}")
    return " | ".join(parts)


def _edit(request, kind, pk):
    Model, Form, label = KINDS[kind]
    booking = get_object_or_404(Model.objects.select_related("card"), pk=pk)
    card = booking.card
    if not _may_fix(request.user, card):
        messages.error(request, "غير مسموح.")
        return redirect("card_detail", pk=card.pk)
    if booking.is_locked:
        messages.error(request, "الحجز معتمد ومقفول من الداتا انتري. اطلب تعديل من صفحة الكارت.")
        return redirect("card_detail", pk=card.pk)

    form = Form(request.POST or None, instance=booking)
    if kind == "hotel":
        form.fields.pop("voucher_code", None)       # the voucher number may already be with the customer
    RoomFormSet = None
    room_formset = None
    if kind == "hotel":
        RoomFormSet = inlineformset_factory(
            HotelBooking, Room, form=RoomForm,
            extra=0 if booking.rooms.exists() else 1, max_num=5, can_delete=False,
        )
        room_formset = RoomFormSet(request.POST or None, instance=booking, prefix="rooms")

    if request.method == "POST":
        ok = form.is_valid() and (room_formset is None or room_formset.is_valid())
        if ok:
            changes = _diff(form)
            obj = form.save(commit=False)
            if kind == "hotel" and obj.checkin and obj.checkout and obj.checkout > obj.checkin:
                obj.nights = (obj.checkout - obj.checkin).days
            obj.save()
            if room_formset is not None:
                if room_formset.has_changed():
                    changes = (changes + " | " if changes else "") + "أسماء النزلاء"
                room_formset.save()
            if changes:
                _log(obj, "edited", changes, request.user)
                messages.success(request, "تم حفظ التعديل. الفاوتشر بيتحدّث بالبيانات الجديدة.")
            else:
                messages.info(request, "ماحصلش أي تغيير.")
            if obj.review_status == ReviewFields.REVIEW_RETURNED:
                messages.info(request, "الحجز مرجوع: لما تخلّص كل التصحيحات اضغط «إعادة إرسال للمراجعة».")
            return redirect("card_detail", pk=card.pk)
        messages.error(request, "في بيانات محتاجة تصحيح، راجع الحقول.")

    payments = [{
        "pk": p.pk, "method": METHOD_LABELS.get(p.method, p.method), "paid": p.paid_amount,
        "editable": p.review_status != ReviewFields.REVIEW_APPROVED,
    } for p in booking.payments.order_by("created_at")]
    itinerary_url = None
    if kind == "flight":
        from flightdocs.services import itinerary_block_reason
        if itinerary_block_reason(booking) is None:
            itinerary_url = "flightdocs:upload"
    return render(request, "core/booking_edit.html", {
        "kind": kind, "label": label, "booking": booking, "card": card, "form": form,
        "room_formset": room_formset, "payments": payments, "itinerary_url": itinerary_url,
        "note": booking.review_note if booking.review_status == ReviewFields.REVIEW_RETURNED else "",
    })


@login_required
def hotel_edit(request, booking_pk):
    return _edit(request, "hotel", booking_pk)


@login_required
def flight_edit(request, booking_pk):
    return _edit(request, "flight", booking_pk)


@login_required
def other_edit(request, booking_pk):
    return _edit(request, "other", booking_pk)
