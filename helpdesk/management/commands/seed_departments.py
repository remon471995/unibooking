from __future__ import annotations
from django.core.management.base import BaseCommand
from helpdesk.models import Department, TicketCategory

DEPARTMENTS = [
    ("Sales", "sales"),
    ("Product", "product"),
    ("Operations", "operations"),
    ("After Sales", "after_sales"),
    ("HR", "hr"),
]

CATEGORIES = {
    "after_sales": [
        ("booking_issue", "مشكلة في حجز"),
        ("customer_complaint", "شكوى عميل"),
        ("modify_request", "طلب تعديل"),
        ("refund", "ريفند"),
        ("change_booking_date", "تغيير ميعاد حجز"),
        ("follow_up", "متابعة على طلب"),
    ],
    "hr": [
        ("leave_request", "طلب إجازة"),
        ("official_letter", "طلب ورقة لجهة"),
    ],
    "operations": [
        ("need_hcn", "محتاج HCN"),
        ("email_hotel", "محتاج إرسال إيميل للفندق"),
    ],
    "product": [
        ("new_booking", "حجز جديد"),
    ],
    "sales": [
        ("lead_inquiry", "استفسار عميل"),
        ("discount_request", "طلب خصم"),
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

        self.stdout.write(self.style.SUCCESS(f"Done. created={created}, updated={updated}"))
