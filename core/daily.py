"""The daily work: bell notifications for upcoming and late installments.  Safe to run any number of times a day
(every notification is created once)."""
from django.conf import settings
from django.utils import timezone

from .installments import KINDS, notify_installment, notify_overdue


def send_installment_notifications(today=None):
    today = today or timezone.localdate()
    days = getattr(settings, "INSTALLMENT_REMINDER_DAYS", 5)
    total = 0
    for Model, rel, _key, _label, _url, _sell in KINDS:
        qs = (Model.objects.filter(installment_date__isnull=False)
              .select_related(f"{rel}__card__created_by", f"{rel}__card__team"))
        for p in qs:
            total += notify_installment(p, today=today, days=days)
            total += notify_overdue(p, today=today)
    return total
