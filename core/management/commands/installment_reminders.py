# core/management/commands/installment_reminders.py
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.installments import KINDS, notify_installment

REMIND_DAYS = getattr(settings, "INSTALLMENT_REMINDER_DAYS", 5)


class Command(BaseCommand):
    help = (
        "Create in-system notifications for upcoming installments. Each one goes to the agent, the people above "
        "him, data entry, accounts and the superusers. Run it once a day (cron / scheduler)."
    )

    def handle(self, *args, **kwargs):
        today = timezone.localdate()
        total = 0
        for Model, rel, _key, _label, _url, _sell in KINDS:
            qs = (Model.objects
                  .filter(installment_date__isnull=False)
                  .select_related(f"{rel}__card__created_by", f"{rel}__card__team"))
            for p in qs:
                total += notify_installment(p, today=today, days=REMIND_DAYS)
        self.stdout.write(self.style.SUCCESS(f"Installment reminders generated: {total} notification(s)."))
