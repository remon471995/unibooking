# core/installment_reminders.py
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Payment,
    FlightPayment,
    OtherPayment,
    Notification,
)

# عدد الأيام قبل الاستحقاق
REMIND_DAYS = getattr(settings, "INSTALLMENT_REMINDER_DAYS", 5)


def _payment_target_url(p):
    """يرجّع لينك صفحة الدفع المناسبة حسب نوع الحجز."""
    if isinstance(p, Payment) and p.booking_hotel_id:
        return reverse("hotel_payment", args=[p.booking_hotel_id])
    if isinstance(p, FlightPayment) and p.booking_flight_id:
        return reverse("flight_payment", args=[p.booking_flight_id])
    if isinstance(p, OtherPayment) and p.booking_other_id:
        return reverse("other_payment", args=[p.booking_other_id])
    return reverse("notifications_list")


class Command(BaseCommand):
    help = "Create in-system notifications for upcoming installment payments"

    def handle(self, *args, **kwargs):
        today = timezone.localdate()
        soon = today + timedelta(days=REMIND_DAYS)

        # اسكان عام لأي كويري ست
        def scan(qs, title, get_card):
            qs = qs.filter(
                method="installment",
                installment_date__range=(today, soon),
            )

            # نحمّل علاقات الكارد عشان مانعملش N+1
            for p in qs.select_related():
                card = get_card(p)
                url = _payment_target_url(p)
                msg = f"{title} مستحق بتاريخ {p.installment_date} — العميل: {card.customer_name}"

                # 1) تنبيه لصاحب الكارت (الايجنت)
                if card.created_by_id:
                    Notification.objects.get_or_create(
                        to_user=card.created_by,
                        message=msg,
                        due_date=p.installment_date,
                        target_url=url,
                    )

                # 2) تنبيه عام للسوبر يوزرز
                Notification.objects.get_or_create(
                    to_superusers=True,
                    message=msg,
                    due_date=p.installment_date,
                    target_url=url,
                )

        scan(
            Payment.objects.all(),
            "قسط فندق",
            lambda p: p.booking_hotel.card,
        )
        scan(
            FlightPayment.objects.all(),
            "قسط طيران",
            lambda p: p.booking_flight.card,
        )
        scan(
            OtherPayment.objects.all(),
            "قسط (أخرى)",
            lambda p: p.booking_other.card,
        )

        self.stdout.write(self.style.SUCCESS("Installment reminders generated."))
