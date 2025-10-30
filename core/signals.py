from datetime import timedelta
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from .models import EmployeeProfile, Department



from .models import Payment, FlightPayment, OtherPayment, Notification

REMIND_DAYS = getattr(settings, "INSTALLMENT_REMINDER_DAYS", 5)

def _should_remind(d):
    if not d:
        return False
    today = timezone.localdate()
    return today <= d <= (today + timedelta(days=REMIND_DAYS))

def _create_notif(message, due_date, url, owner_user):
    if Notification.objects.filter(
        message=message, due_date=due_date, target_url=url,
        to_user=owner_user, to_superusers=True
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
    msg  = f"قسط فندق مستحق بتاريخ {instance.installment_date} — العميل: {card.customer_name}"
    url  = f"/hotel/{instance.booking_hotel_id}/payment/"
    _create_notif(msg, instance.installment_date, url, card.created_by)

@receiver(post_save, sender=FlightPayment)
def notify_installment_flight(sender, instance, created, **kwargs):
    if instance.method != "installment" or not _should_remind(instance.installment_date):
        return
    card = instance.booking_flight.card
    msg  = f"قسط طيران مستحق بتاريخ {instance.installment_date} — العميل: {card.customer_name}"
    url  = f"/flight/{instance.booking_flight_id}/payment/"
    _create_notif(msg, instance.installment_date, url, card.created_by)

@receiver(post_save, sender=OtherPayment)
def notify_installment_other(sender, instance, created, **kwargs):
    if instance.method != "installment" or not _should_remind(instance.installment_date):
        return
    card = instance.booking_other.card
    msg  = f"قسط (أخرى) مستحق بتاريخ {instance.installment_date} — العميل: {card.customer_name}"
    url  = f"/other/{instance.booking_other_id}/payment/"
    _create_notif(msg, instance.installment_date, url, card.created_by)

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile_for_user(sender, instance, created, **kwargs):
    if created:
        EmployeeProfile.objects.get_or_create(user=instance)

def ensure_base_groups():
    """
    ينشئ جروبات أساسية: sales, quotation, leaders
    واربطها بصلاحيات مناسبة (كمثال: عرض/تعديل حجوزات).
    شغّلها مرة من shell أو استدعِها من ready().
    """
    # أمثلة لجروبات
    sales_g, _ = Group.objects.get_or_create(name="sales")
    quot_g,  _ = Group.objects.get_or_create(name="quotation")
    leaders_g,_= Group.objects.get_or_create(name="leaders")

    # مثال ربط صلاحيات (عدّل على حسب موديلاتك)
    # من فضلك حدّث ContentType للموديلات الفعلية عندك
    try:
        from .models import HotelBooking, FlightBooking, OtherBooking
        for model in (HotelBooking, FlightBooking, OtherBooking):
            ct = ContentType.objects.get_for_model(model)
            can_view = Permission.objects.get(codename=f"view_{model._meta.model_name}", content_type=ct)
            can_change = Permission.objects.get(codename=f"change_{model._meta.model_name}", content_type=ct)
            sales_g.permissions.add(can_view, can_change)
            quot_g.permissions.add(can_view)  # الكوتيشن يشوف فقط كمثال
            leaders_g.permissions.add(can_view, can_change)
    except Exception:
        pass
