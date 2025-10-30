# core/management/commands/delete_all_data.py

from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import UniBookingCard, Notification

class Command(BaseCommand):
    help = 'Deletes all UniBookingCards and all related bookings, payments, and notifications. USE WITH EXTREME CAUTION.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING(
            '===================================================\n'
            'تحذير: هذا الأمر سيقوم بحذف جميع بيانات الحجز بشكل دائم.\n'
            'هذا يشمل جميع كروت العملاء (UniBookingCards) وكل ما يتعلق بها\n'
            'من حجوزات فنادق، طيران، خدمات أخرى، ومدفوعات.\n'
            'لا يمكن التراجع عن هذا الإجراء.\n'
            '==================================================='
        ))

        # طلب تأكيد من المستخدم
        confirmation = input('للمتابعة، اكتب "امسح كل شيء" ثم اضغط Enter: ')

        if confirmation != 'امسح كل شيء':
            self.stdout.write(self.style.ERROR('تم إلغاء العملية.'))
            return

        try:
            with transaction.atomic():
                # حذف كروت العملاء سيؤدي إلى حذف كل شيء مرتبط بها بسبب on_delete=models.CASCADE
                card_count, _ = UniBookingCard.objects.all().delete()
                self.stdout.write(self.style.SUCCESS(f'تم بنجاح حذف {card_count} كارت عميل وكل الحجوزات والمدفوعات المرتبطة بها.'))

                # الإشعارات غير مرتبطة مباشرة بالكروت، لذا نحذفها بشكل منفصل
                notif_count, _ = Notification.objects.all().delete()
                self.stdout.write(self.style.SUCCESS(f'تم بنجاح حذف {notif_count} إشعار.'))

            self.stdout.write(self.style.SUCCESS('\n✅ تم مسح جميع البيانات بنجاح.'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'حدث خطأ: {e}'))
            self.stdout.write(self.style.ERROR('فشلت العملية. لم يتم حذف أي بيانات.'))