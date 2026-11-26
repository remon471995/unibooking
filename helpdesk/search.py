"""Search words for requests: the subject, the request number, the booking reference / PNR, people, tags, and the
booking or card a request is linked to (voucher code, Ref, PNR, card code, customer name, mobile number)."""
import re

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q


def _related_q(q):
    from core.models import FlightBooking, HotelBooking, OtherBooking, UniBookingCard
    digits = re.sub(r"\D", "", q)
    card_q = Q(ub_code__icontains=q) | Q(mobile__icontains=q) | Q(customer_name__icontains=q)
    if len(digits) >= 5:
        card_q |= Q(mobile__icontains=digits)
    cards = list(UniBookingCard.objects.filter(card_q).values_list("pk", flat=True)[:200])

    cond = Q()
    if cards:
        cond |= Q(related_content_type=ContentType.objects.get_for_model(UniBookingCard), related_object_id__in=cards)
    own = {
        HotelBooking: Q(voucher_code__icontains=q) | Q(booking_ref__icontains=q),
        FlightBooking: Q(voucher_code__icontains=q) | Q(pnr__icontains=q),
        OtherBooking: Q(voucher_code__icontains=q) | Q(booking_ref__icontains=q),
    }
    for model, match in own.items():
        ids = list(model.objects.filter(match | Q(card_id__in=cards)).values_list("pk", flat=True)[:500])
        if ids:
            cond |= Q(related_content_type=ContentType.objects.get_for_model(model), related_object_id__in=ids)
    return cond


def ticket_search_q(q):
    return (
        Q(subject__icontains=q) | Q(id__icontains=q) | Q(related_ref__icontains=q)
        | Q(requester__username__icontains=q) | Q(requester__first_name__icontains=q)
        | Q(requester__last_name__icontains=q) | Q(assigned_to__username__icontains=q)
        | Q(tags__name__icontains=q) | _related_q(q)
    )
