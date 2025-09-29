from django.core.management.base import BaseCommand
from core.models import HotelBooking

class Command(BaseCommand):
    help = "تحديث السياسة القديمة partial إلى refundable_with_penalty"

    def handle(self, *args, **options):
        updated = HotelBooking.objects.filter(
            cancellation_policy="partial"
        ).update(cancellation_policy="refundable_with_penalty")

        self.stdout.write(
            self.style.SUCCESS(f"✅ تم تحديث {updated} حجز من partial → refundable_with_penalty")
        )
