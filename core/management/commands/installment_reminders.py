# core/management/commands/installment_reminders.py
from django.core.management.base import BaseCommand

from core.daily import send_installment_notifications


class Command(BaseCommand):
    help = (
        "Create in-system notifications for upcoming and late installments. Each one goes to the agent, the people "
        "above him, data entry, accounts and the superusers. The server also runs it by itself once a day "
        "(core/background.py); this command is for running it by hand or from a scheduler."
    )

    def handle(self, *args, **kwargs):
        total = send_installment_notifications()
        self.stdout.write(self.style.SUCCESS(f"Installment notifications created: {total}."))
