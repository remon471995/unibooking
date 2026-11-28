"""Who sees which installment.  One place for the rule, used by the boards and by the notifications.

Rule
----
* An agent sees only the installments of his own cards.
* Team leaders and supervisors see the installments of ALL teams (not only their own team),
  and so do the sales manager, the admin, data entry, the accounts department and superusers.
  A user counts as leader / supervisor when his role says so OR when he leads / supervises an active team.

The rule exists twice because the database needs two shapes of it:
  scope_q(user)              -> a Q filter ("which rows may THIS user see")
  installment_recipients()   -> a user list ("who must be told about THIS card's installment")
Both live here so they cannot drift apart (core/tests.py checks that they agree).
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

from .models import FlightPayment, Notification, OtherPayment, Payment, Team
from .permissions import FULL_VIEW_DEPARTMENT, FULL_VIEW_ROLES, sees_all_bookings as sees_all_installments  # noqa: F401

# (payment model, relation to the booking, key, Arabic label, payment page url name, sell field)
KINDS = (
    (Payment, "booking_hotel", "hotel", "فندق", "hotel_payment", "sell"),
    (FlightPayment, "booking_flight", "flight", "طيران", "flight_payment", "sell_price"),
    (OtherPayment, "booking_other", "other", "أخرى", "other_payment", "sell_price"),
)


def scope_q(user, prefix=""):
    """Q filter limiting a queryset to what `user` may see, or None when he sees everything.

    prefix is the path to the booking: "" on a booking model, "booking_hotel__" on a hotel payment.
    Only a plain agent is limited, and only to the cards he owns (his team mates' cards are not his).
    """
    if sees_all_installments(user):
        return None
    return Q(**{f"{prefix}card__created_by_id": user.id})


def installment_recipients(card):
    """Active users who must see (and be notified about) an installment of this card."""
    User = get_user_model()
    owner = card.created_by
    cond = (
        Q(is_superuser=True)
        | Q(profile__role__in=FULL_VIEW_ROLES)
        | Q(profile__department=FULL_VIEW_DEPARTMENT)
        | Q(led_teams__is_active=True)
        | Q(supervised_teams__is_active=True)
    )
    if owner is not None:
        cond |= Q(pk=owner.id)
    return User.objects.filter(is_active=True).filter(cond).distinct()


def _name(u):
    return ((u.get_full_name() or u.get_username()) if u else "—")


def booking_remaining(booking, key):
    """sell - paid for one booking (key: hotel / flight / other)."""
    for Model, rel, k, _label, _url, sell_field in KINDS:
        if k == key:
            sell = getattr(booking, sell_field) or Decimal("0")
            paid = (Model.objects.filter(**{f"{rel}_id": booking.pk}).exclude(review_status="returned")
                    .aggregate(t=Sum("paid_amount"))["t"] or Decimal("0"))
            return sell - paid
    return Decimal("0")


def _rows(user, when, today, limit, newest_first=False):
    """Installment rows the user may see.  `when` = filter on installment_date.  A booking that is already paid in full
    (approved + waiting payments, not the returned ones) is left out."""
    rows = []
    for Model, rel, key, label, url_name, sell_field in KINDS:
        qs = (Model.objects.filter(**when).select_related(f"{rel}__card__created_by"))
        q = scope_q(user, prefix=f"{rel}__")
        if q is not None:
            qs = qs.filter(q)
        pays = list(qs.order_by("-installment_date" if newest_first else "installment_date")[:limit])
        if not pays:
            continue
        booking_ids = {getattr(p, f"{rel}_id") for p in pays}
        paid = dict(
            Model.objects.filter(**{f"{rel}_id__in": booking_ids}).exclude(review_status="returned")
            .values(f"{rel}_id").annotate(t=Sum("paid_amount")).values_list(f"{rel}_id", "t")
        )
        for p in pays:
            b = getattr(p, rel)
            remaining = (getattr(b, sell_field) or Decimal("0")) - (paid.get(b.pk) or Decimal("0"))
            if remaining <= Decimal("0.01"):
                continue
            rows.append({
                "kind_key": key, "kind": label, "customer": b.card.customer_name,
                "ref": getattr(b, "voucher_code", None) or getattr(b, "booking_ref", None) or getattr(b, "pnr", "") or "",
                "due": p.installment_date, "date": p.installment_date,
                "amount": p.paid_amount or Decimal("0"), "remaining": remaining,
                "url": reverse(url_name, args=[b.pk]),
                "days": (p.installment_date - today).days,
                "owner": _name(b.card.created_by),
            })
    return rows


def due_installments(user, days, today=None, limit=200):
    """Installments due within `days` days that the user may see, soonest first."""
    today = today or timezone.localdate()
    rows = _rows(user, {"installment_date__range": (today, today + timedelta(days=days))}, today, limit)
    rows.sort(key=lambda r: (r["due"], r["customer"]))
    return rows


def overdue_installments(user, today=None, limit=300):
    """Installments whose last agreed date has PASSED and that are still not paid in full, the most late first."""
    today = today or timezone.localdate()
    rows = _rows(user, {"installment_date__lt": today}, today, limit)
    for r in rows:
        r["days_late"] = -r["days"]
    rows.sort(key=lambda r: (-r["days_late"], r["customer"]))
    return rows


def notify_installment(payment, today=None, days=None):
    """Tell every person who must see this installment, once per person (safe to call again)."""
    from django.conf import settings

    days = days if days is not None else getattr(settings, "INSTALLMENT_REMINDER_DAYS", 5)
    today = today or timezone.localdate()
    due = payment.installment_date
    if not due or not (today <= due <= today + timedelta(days=days)):
        return 0
    for Model, rel, key, label, url_name, _sell in KINDS:
        if isinstance(payment, Model):
            booking = getattr(payment, rel)
            break
    else:
        return 0
    if booking_remaining(booking, key) <= Decimal("0.01"):
        return 0
    card = booking.card
    url = reverse(url_name, args=[booking.pk])
    msg = f"قسط {label} مستحق بتاريخ {due} — العميل: {card.customer_name} — الأجنت: {_name(card.created_by)}"
    sent = 0
    for u in installment_recipients(card):
        _n, created = Notification.objects.get_or_create(
            to_user=u, message=msg, due_date=due, target_url=url,
        )
        sent += int(created)
    return sent


def notify_overdue(payment, today=None, days=None):
    """Tell everybody who must see it that an installment is late (once per installment).  Only the ones that became
    late within the last `days` days (default 30) so the first run does not flood the bell with old history."""
    from django.conf import settings

    days = days if days is not None else getattr(settings, "INSTALLMENT_OVERDUE_NOTIFY_DAYS", 30)
    today = today or timezone.localdate()
    due = payment.installment_date
    if not due or not (today - timedelta(days=days) <= due < today):
        return 0
    for Model, rel, key, label, url_name, _sell in KINDS:
        if isinstance(payment, Model):
            booking = getattr(payment, rel)
            break
    else:
        return 0
    remaining = booking_remaining(booking, key)
    if remaining <= Decimal("0.01"):
        return 0
    card = booking.card
    url = reverse(url_name, args=[booking.pk])
    msg = (f"⚠ قسط {label} متأخر (كان مستحق {due}) — المتبقي {remaining:.2f} — "
           f"العميل: {card.customer_name} — الأجنت: {_name(card.created_by)}")
    sent = 0
    for u in installment_recipients(card):
        _n, created = Notification.objects.get_or_create(to_user=u, message=msg, due_date=due, target_url=url)
        sent += int(created)
    return sent
