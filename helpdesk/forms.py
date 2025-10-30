from django import forms
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from .models import (
    Ticket, TicketMessage, TicketAttachment, TicketTag,
    CannedReply, TicketCategory, Department
)

class TicketForm(forms.ModelForm):
    body = forms.CharField(label="تفاصيل الطلب", widget=forms.Textarea(attrs={"rows": 5}))
    attachment = forms.FileField(label="مرفق (اختياري)", required=False)

    related_model = forms.ModelChoiceField(label="كيان مرتبط (اختياري)", required=False, queryset=ContentType.objects.none())
    related_id = forms.IntegerField(label="المعرف المرتبط (ID)", required=False)

    tags = forms.ModelMultipleChoiceField(
        label="تصنيفات (Tags)", required=False, queryset=TicketTag.objects.all(),
        widget=forms.SelectMultiple(attrs={"size": 4}),
    )

    # NEW
    category = forms.ModelChoiceField(
        label="الفئة",
        required=False,
        queryset=TicketCategory.objects.none(),
        widget=forms.Select(attrs={"id": "id_category"}),
    )

    class Meta:
        model = Ticket
        fields = ["subject", "department", "category", "priority", "related_ref", "related_url", "tags"]
        widgets = {"subject": forms.TextInput(attrs={"class": "w-full"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # فلترة ContentTypes المسموحة (اختياري)
        allowed_ids = []
        for app_model in [("core", "unibookingcard"), ("core", "hotelbooking"), ("core", "flightbooking")]:
            ct = ContentType.objects.filter(app_label=app_model[0], model=app_model[1]).first()
            if ct:
                allowed_ids.append(ct.pk)
        self.fields["related_model"].queryset = ContentType.objects.filter(pk__in=allowed_ids)

        # Dynamic Category by Department
        dept_id = None
        if self.data.get("department"):
            dept_id = self.data.get("department")
        elif self.initial.get("department"):
            dept = self.initial.get("department")
            dept_id = dept.pk if isinstance(dept, Department) else dept
        elif getattr(self.instance, "department_id", None):
            dept_id = self.instance.department_id

        if dept_id:
            self.fields["category"].queryset = TicketCategory.objects.filter(
                department_id=dept_id, is_active=True
            ).order_by("order", "name")
        else:
            self.fields["category"].queryset = TicketCategory.objects.none()

        # HTMX attributes على اختيار القسم
        self.fields["department"].widget.attrs.update({
            "id": "id_department",
            "hx-get": reverse("helpdesk:category_options"),
            "hx-trigger": "change",
            "hx-target": "#id_category",
            "hx-vals": "js:{dept_id: this.value}",
            "hx-swap": "outerHTML",
        })


class TicketReplyForm(forms.ModelForm):
    attachment = forms.FileField(label="مرفق (اختياري)", required=False)
    canned = forms.ModelChoiceField(label="إدراج رد جاهز", required=False, queryset=CannedReply.objects.none())

    class Meta:
        model = TicketMessage
        fields = ["body", "is_internal_note"]
        widgets = {"body": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        department = kwargs.pop("department", None)
        super().__init__(*args, **kwargs)
        if department:
            self.fields["canned"].queryset = department.canned_replies.filter(is_public=True)
        else:
            self.fields["canned"].queryset = CannedReply.objects.filter(is_public=True)
