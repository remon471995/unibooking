from __future__ import annotations
from django.core.management.base import BaseCommand
from helpdesk.models import Department, TicketCategory

DEPARTMENTS = [
    ("كوتيشن (Quotation)", "quotation"),
    ("أوبريشن (Operations)", "operations"),
    ("FFT (الطيران)", "fft"),
    ("CS (خدمة ما بعد البيع)", "cs"),
]

CATEGORIES = {
    "quotation": [
        ("price_request", "طلب سعر حجز (مش أونلاين)"),
        ("quote_update", "تعديل عرض سعر"),
        ("quote_follow_up", "متابعة عرض سعر"),
    ],
    "operations": [
        ("hotel_confirmation", "تأكيد من الفندق"),
        ("need_hcn", "محتاج HCN"),
        ("email_hotel", "محتاج إرسال إيميل للفندق"),
        ("special_request", "طلب خاص من الفندق"),
    ],
    "fft": [
        ("flight_change", "تعديل طيران"),
        ("flight_cancel", "إلغاء طيران"),
        ("flight_date_change", "تغيير ميعاد رحلة"),
        ("issue_ticket", "إصدار تذكرة"),
    ],
    "cs": [
        ("hotel_confirmation_request", "طلب تأكيد / HCN من الفندق"),
        ("flight_change_request", "تعديل طيران"),
        ("flight_cancel_request", "إلغاء طيران"),
        ("flight_date_request", "تغيير ميعاد رحلة"),
        ("issue_ticket_request", "إصدار تذكرة"),
        ("customer_complaint", "شكوى عميل"),
        ("booking_issue", "مشكلة في حجز"),
        ("modify_request", "طلب تعديل"),
        ("cancel_request", "طلب إلغاء"),
        ("refund", "ريفند"),
        ("follow_up", "متابعة على طلب"),
    ],
}

class Command(BaseCommand):
    help = "Seed default Helpdesk departments, and categories per department."

    def add_arguments(self, parser):
        parser.add_argument("--with-emails", action="store_true", help="Populate department.email as <slug>@unibooking.local")
        parser.add_argument("--with-categories", action="store_true", help="Also create department-specific categories")

    def handle(self, *args, **opts):
        created, updated = 0, 0
        slug_to_obj = {}
        for name, slug in DEPARTMENTS:
            defaults = {"name": name, "description": "", "is_active": True}
            if opts.get("with_emails"):
                defaults["email"] = f"{slug}@unibooking.local"
            obj, was_created = Department.objects.get_or_create(slug=slug, defaults=defaults)
            slug_to_obj[slug] = obj
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"Created: {name} ({slug})"))
            else:
                # تحديثات بسيطة
                changed = False
                if obj.name != name:
                    obj.name = name; changed = True
                if opts.get("with_emails"):
                    if obj.email != defaults["email"]:
                        obj.email = defaults["email"]; changed = True
                if changed:
                    obj.save(); updated += 1
                    self.stdout.write(self.style.WARNING(f"Updated: {name} ({slug})"))

        if opts.get("with_categories"):
            for slug, items in CATEGORIES.items():
                dept = slug_to_obj.get(slug) or Department.objects.filter(slug=slug).first()
                if not dept:
                    continue
                for i, (c_slug, c_name) in enumerate(items):
                    TicketCategory.objects.get_or_create(
                        department=dept, slug=c_slug,
                        defaults={"name": c_name, "order": i}
                    )
            self.stdout.write(self.style.SUCCESS("Categories seeded."))

        # employees whose department was set before the helpdesk existed join their inbox now
        # (adds missing memberships only, never removes anyone)
        from accounts.models import UserProfile
        from helpdesk.signals import sync_membership
        for prof in UserProfile.objects.exclude(department="").select_related("user"):
            sync_membership(prof, only_add=True)

        self.stdout.write(self.style.SUCCESS(f"Done. created={created}, updated={updated}"))
