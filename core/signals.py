# core/signals.py
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from .models import (
    EmployeeProfile,
    Payment, FlightPayment, OtherPayment, Notification,
    HotelBooking, FlightBooking, OtherBooking, BookingAmendment,
)
from .utils_cycles import cycle_from_booking_accounting

REMIND_DAYS = getattr(settings, "INSTALLMENT_REMINDER_DAYS", 5)
User = get_user_model()

# ---------------- قسط/تذكير الدفعات ----------------


def _should_remind(d):
    if not d:
        return False
    today = timezone.localdate()
    return today <= d <= (today + timedelta(days=REMIND_DAYS))


def _create_notif(message, due_date, url, owner_user):
    """
    تنبيه الأقساط (زي ما هو كان شغال قبل كده)
    """
    if Notification.objects.filter(
        message=message,
        due_date=due_date,
        target_url=url,
        to_user=owner_user,
        to_superusers=True,
    ).exists():
        return
    Notification.objects.create(
        to_user=owner_user,
        to_superusers=True,
        message=message,
        due_date=due_date,
        target_url=url,
    )


@receiver(post_save, sender=Payment)
def notify_installment_hotel(sender, instance, created, **kwargs):
    if instance.method != "installment" or not _should_remind(instance.installment_date):
        return
    card = instance.booking_hotel.card
    msg = f"قسط فندق مستحق بتاريخ {instance.installment_date} — العميل: {card.customer_name}"
    url = f"/hotel/{instance.booking_hotel_id}/payment/"
    _create_notif(msg, instance.installment_date, url, card.created_by)


@receiver(post_save, sender=FlightPayment)
def notify_installment_flight(sender, instance, created, **kwargs):
    if instance.method != "installment" or not _should_remind(instance.installment_date):
        return
    card = instance.booking_flight.card
    msg = f"قسط طيران مستحق بتاريخ {instance.installment_date} — العميل: {card.customer_name}"
    url = f"/flight/{instance.booking_flight_id}/payment/"
    _create_notif(msg, instance.installment_date, url, card.created_by)


@receiver(post_save, sender=OtherPayment)
def notify_installment_other(sender, instance, created, **kwargs):
    if instance.method != "installment" or not _should_remind(instance.installment_date):
        return
    card = instance.booking_other.card
    msg = f"قسط (أخرى) مستحق بتاريخ {instance.installment_date} — العميل: {card.customer_name}"
    url = f"/other/{instance.booking_other_id}/payment/"
    _create_notif(msg, instance.installment_date, url, card.created_by)


# ------------- بروفايل الموظف تلقائيًا -------------


@receiver(post_save, sender=User)
def create_profile_for_user(sender, instance, created, **kwargs):
    if created:
        EmployeeProfile.objects.get_or_create(user=instance)


# ------------- جروبات أساسية وصلاحيات -------------


def ensure_base_groups():
    """ينشئ جروبات أساسية ويضيف صلاحيات قراءة/تعديل للحجوزات."""
    sales_g, _ = Group.objects.get_or_create(name="sales")
    quot_g, _ = Group.objects.get_or_create(name="quotation")
    leaders_g, _ = Group.objects.get_or_create(name="leaders")

    for model in (HotelBooking, FlightBooking, OtherBooking):
        ct = ContentType.objects.get_for_model(model)
        can_view = Permission.objects.get(
            codename=f"view_{model._meta.model_name}",
            content_type=ct,
        )
        can_change = Permission.objects.get(
            codename=f"change_{model._meta.model_name}",
            content_type=ct,
        )
        sales_g.permissions.add(can_view, can_change)
        quot_g.permissions.add(can_view)
        leaders_g.permissions.add(can_view, can_change)


# ---- ائتمان تعديلات الحجوزات (من غير PaymentAdjustment) ----


def _get_booking_from_ct(ct_id, obj_id):
    ct = ContentType.objects.get_for_id(ct_id)
    return ct.get_object_for_this_type(pk=obj_id)


def _owner_and_cycle(booking):
    owner = getattr(getattr(booking, "card", None), "created_by", None)
    acc_date = getattr(booking, "accounting_date", None)
    cycle = cycle_from_booking_accounting(acc_date)
    return owner, cycle


@receiver(post_save, sender=BookingAmendment)
def set_credit_on_amendment(sender, instance: BookingAmendment, created, **kwargs):
    """يضبط credited_to و cycle تلقائياً عند حفظ تعديل حجز."""
    booking = _get_booking_from_ct(instance.booking_content_type_id, instance.booking_object_id)
    owner, cycle = _owner_and_cycle(booking)

    updates = {}
    if owner and instance.credited_to_id != getattr(owner, "id", None):
        updates["credited_to_id"] = owner.id
    if cycle and instance.cycle_id != cycle.id:
        updates["cycle_id"] = cycle.id

    if updates:
        BookingAmendment.objects.filter(pk=instance.pk).update(**updates)


# ---------------- تنبيهات تعديل الأسعار (للحسابات فقط) ----------------


def _notify_accounting_price_change(message: str, target_url: str):
    """
    يبعت Notification لكل أعضاء جروب الحسابات
    باستخدام موديل Notification الحالي (to_user / to_superusers / message / target_url)
    """
    try:
        accounting_group = Group.objects.get(name="accounting")
    except Group.DoesNotExist:
        return  # لو الجروب مش موجود نطنّش بهدوء

    for user in accounting_group.user_set.all():
        Notification.objects.create(
            to_user=user,
            to_superusers=False,
            message=message,
            target_url=target_url,
        )


def _store_changes(instance, model_cls, fields_to_track):
    """
    مقارنة القيم القديمة بالجديدة قبل الحفظ وتخزينها في instance._changes
    """
    if not instance.pk:
        return

    try:
        old = model_cls.objects.get(pk=instance.pk)
    except model_cls.DoesNotExist:
        return

    instance._changes = []

    for field in fields_to_track:
        old_val = getattr(old, field)
        new_val = getattr(instance, field)
        if old_val != new_val:
            instance._changes.append((field, old_val, new_val))


# ---------- Payment (Hotel) ----------


@receiver(pre_save, sender=Payment)
def payment_pre_save(sender, instance: Payment, **kwargs):
    _store_changes(instance, Payment, ["net_price", "sell_price", "paid_amount"])


@receiver(post_save, sender=Payment)
def payment_post_save(sender, instance: Payment, created, **kwargs):
    if created:
        return

    changes = getattr(instance, "_changes", [])
    if not changes:
        return

    parts = [f"{field}: {old} → {new}" for field, old, new in changes]
    changes_text = " | ".join(parts)

    card = instance.booking_hotel.card
    msg = (
        f"تم تعديل دفعة فندق على الحجز {instance.booking_hotel_id} "
        f"للعميل {card.customer_name}.\n"
        f"التغييرات: {changes_text}"
    )
    url = f"/hotel/{instance.booking_hotel_id}/payment/"

    _notify_accounting_price_change(msg, url)


# ---------- FlightPayment ----------


@receiver(pre_save, sender=FlightPayment)
def flight_payment_pre_save(sender, instance: FlightPayment, **kwargs):
    _store_changes(instance, FlightPayment, ["net_price", "sell_price", "paid_amount"])


@receiver(post_save, sender=FlightPayment)
def flight_payment_post_save(sender, instance: FlightPayment, created, **kwargs):
    if created:
        return

    changes = getattr(instance, "_changes", [])
    if not changes:
        return

    parts = [f"{field}: {old} → {new}" for field, old, new in changes]
    changes_text = " | ".join(parts)

    card = instance.booking_flight.card
    msg = (
        f"تم تعديل دفعة طيران على الحجز {instance.booking_flight_id} "
        f"للعميل {card.customer_name}.\n"
        f"التغييرات: {changes_text}"
    )
    url = f"/flight/{instance.booking_flight_id}/payment/"

    _notify_accounting_price_change(msg, url)


# ---------- OtherPayment ----------


@receiver(pre_save, sender=OtherPayment)
def other_payment_pre_save(sender, instance: OtherPayment, **kwargs):
    _store_changes(instance, OtherPayment, ["net_price", "sell_price", "paid_amount"])


@receiver(post_save, sender=OtherPayment)
def other_payment_post_save(sender, instance: OtherPayment, created, **kwargs):
    if created:
        return

    changes = getattr(instance, "_changes", [])
    if not changes:
        return

    parts = [f"{field}: {old} → {new}" for field, old, new in changes]
    changes_text = " | ".join(parts)

    card = instance.booking_other.card
    msg = (
        f"تم تعديل دفعة (أخرى) على الحجز {instance.booking_other_id} "
        f"للعميل {card.customer_name}.\n"
        f"التغييرات: {changes_text}"
    )
    url = f"/other/{instance.booking_other_id}/payment/"

    _notify_accounting_price_change(msg, url)
