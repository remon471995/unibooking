from django.db import migrations, models
import django.db.models.deletion

def seed_categories(apps, schema_editor):
    Department = apps.get_model('helpdesk', 'Department')
    TicketCategory = apps.get_model('helpdesk', 'TicketCategory')

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

    for dept_slug, items in CATEGORIES.items():
        dept = Department.objects.filter(slug=dept_slug).first()
        if not dept:
            continue
        for order, (c_slug, c_name) in enumerate(items):
            TicketCategory.objects.get_or_create(
                department=dept, slug=c_slug,
                defaults={"name": c_name, "order": order, "is_active": True}
            )

def move_old_category_data(apps, schema_editor):
    Ticket = apps.get_model('helpdesk', 'Ticket')
    TicketCategory = apps.get_model('helpdesk', 'TicketCategory')

    # ننقل القيم النصية القديمة من Ticket.category إلى Ticket.category_fk
    for t in Ticket.objects.all().only('id', 'department_id', 'category'):
        old_slug = (t.category or "").strip()
        if not old_slug:
            continue
        cat = TicketCategory.objects.filter(department_id=t.department_id, slug=old_slug).first()
        if cat:
            # نحدّث باستخدام update لتفادي حفظ Signals أو مشاكل تاريخيّة
            Ticket.objects.filter(pk=t.pk).update(category_fk_id=cat.id)
        else:
            # لو الملائمة مش موجودة بنسيبها فاضية (NULL)
            pass

class Migration(migrations.Migration):

    dependencies = [
        ('helpdesk', '0001_initial'),
    ]

    operations = [
        # 1) إنشاء جدول TicketCategory
        migrations.CreateModel(
            name='TicketCategory',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80)),
                ('slug', models.SlugField(max_length=80)),
                ('is_active', models.BooleanField(default=True)),
                ('order', models.PositiveIntegerField(default=0)),
                ('department', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='categories', to='helpdesk.department')),
            ],
            options={
                'ordering': ['department__name', 'order', 'name'],
                'unique_together': {('department', 'slug')},
            },
        ),

        # 2) إضافة حقل FK مؤقت (nullable) بجانب الحقل النصي القديم
        migrations.AddField(
            model_name='ticket',
            name='category_fk',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tickets', to='helpdesk.ticketcategory'),
        ),

        # 3) زرع الفئات لكل قسم (علشان نلاقي IDs ننقل لها)
        migrations.RunPython(seed_categories, reverse_code=migrations.RunPython.noop),

        # 4) نقل البيانات من الحقل النصي القديم إلى FK المؤقت
        migrations.RunPython(move_old_category_data, reverse_code=migrations.RunPython.noop),

        # 5) حذف الحقل القديم
        migrations.RemoveField(
            model_name='ticket',
            name='category',
        ),

        # 6) إعادة تسمية الحقل المؤقت إلى الاسم النهائي
        migrations.RenameField(
            model_name='ticket',
            old_name='category_fk',
            new_name='category',
        ),
    ]
