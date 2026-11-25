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
from .permissions import _department, role_of

# roles that see every installment of the company
FULL_VIEW_ROLES = {"admin", "sales_manager", "data_entry", "leader", "supervisor"}
FULL_VIEW_DEPARTMENT = "accounts"

# (payment model, relation to the booking, key, Arabic label, payment page url name, sell field)
KINDS = (
    (Payment, "booking_hotel", "hotel", "فندق", "hotel_payment", "sell"),
    (FlightPayment, "booking_flight", "flight", "طيران", "flight_payment", "sell_price"),
    (OtherPayment, "booking_other", "other", "أخرى", "other_payment", "sell_price"),
)


def sees_all_installments(user):
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(
        user.is_superuser
        or role_of(user) in FULL_VIEW_ROLES
        or _department(user) == FULL_VIEW_DEPARTMENT
        or Team.objects.filter(is_active=True).filter(Q(leader=user) | Q(supervisor=user)).exists()
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


def due_installments(user, days, today=None, limit=200):
    """Installments due within `days` days that the user may see, soonest first.
    Bookings that are already paid in full are left out."""
    today = today or timezone.localdate()
    soon = today + timedelta(days=days)
    rows = []
    for Model, rel, key, label, url_name, sell_field in KINDS:
        qs = (Model.objects
              .filter(installment_date__range=(today, soon))
              .select_related(f"{rel}__card__created_by"))
        q = scope_q(user, prefix=f"{rel}__")
        if q is not None:
            qs = qs.filter(q)
        pays = list(qs.order_by("installment_date")[:limit])
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
    rows.sort(key=lambda r: (r["due"], r["customer"]))
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
