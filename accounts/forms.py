from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from .models import UserProfile

User = get_user_model()

ROLE_CHOICES = [
    ("agent", "موظف مبيعات"),
    ("leader", "ليدر"),
    ("admin", "سوبر/مدير"),
]

DEPARTMENT_CHOICES = [
    ("sales", "المبيعات"),
    ("cs", "خدمة العملاء"),
    ("ops", "الأوبريشن"),
    ("accounts", "الحسابات"),
    ("hr", "الموارد البشرية"),
    ("it", "IT"),
    ("other", "أخرى"),
]

class UserBasicForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["email"]
        labels = {"email": "البريد الإلكتروني"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # إضافة كلاس افتراضي للحقل
        for f in self.fields.values():
            f.widget.attrs.update({"class": "w-full border-gray-300 rounded-lg px-3 py-2"})

class ProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["phone", "department", "job_title", "address", "avatar", "notes", "role"]
        labels = {
            "phone": "الموبايل",
            "department": "القسم",
            "job_title": "المسمى الوظيفي",
            "address": "العنوان",
            "avatar": "الصورة الشخصية",
            "notes": "ملاحظات",
            "role": "الدور",
        }

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop("request_user", None)
        super().__init__(*args, **kwargs)
        # عطل حقل القسم لو مش سوبر
        if not (self.request_user and self.request_user.is_superuser):
            self.fields["department"].disabled = True
        # أضف كلاس لكل الحقول لعرض مرتب
        for f in self.fields.values():
            # للـ file field نحتفظ ببعض الattrs الخاصة
            f.widget.attrs.update({"class": "w-full border-gray-300 rounded-lg px-3 py-2"})

    def clean_department(self):
        dep = self.cleaned_data.get("department")
        if self.request_user and not self.request_user.is_superuser:
            return self.instance.department
        return dep


class MyPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(label="كلمة المرور الحالية", widget=forms.PasswordInput(attrs={"class":"w-full px-3 py-2 rounded"}))
    new_password1 = forms.CharField(label="كلمة المرور الجديدة", widget=forms.PasswordInput(attrs={"class":"w-full px-3 py-2 rounded"}))
    new_password2 = forms.CharField(label="تأكيد كلمة المرور الجديدة", widget=forms.PasswordInput(attrs={"class":"w-full px-3 py-2 rounded"}))


class BulkActionForm(forms.Form):
    action = forms.ChoiceField(
        choices=[
            ("", "اختر إجراء..."),
            ("set_department", "نقل إلى قسم"),
            ("assign_leader", "تعيين ليدر"),
            ("set_target", "تحديد/تحديث تارجت شهري"),
            ("change_role", "تغيير الدور/ترقية"),
            ("deactivate", "إيقاف/تفعيل المستخدم"),
            ("change_password", "تغيير كلمة المرور لمستخدم واحد"),
        ],
        required=True,
        label="الإجراء",
    )
    department = forms.ChoiceField(choices=DEPARTMENT_CHOICES, required=False, label="القسم")
    leader = forms.ModelChoiceField(queryset=User.objects.filter(is_active=True), required=False, label="الليدر")
    target_value = forms.DecimalField(max_digits=12, decimal_places=2, required=False, label="قيمة التارجت")
    target_month = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "month"}),
        label="شهر التارجت (سنة-شهر)",
    )
    role = forms.ChoiceField(choices=ROLE_CHOICES, required=False, label="الدور")

    new_password = forms.CharField(required=False, widget=forms.PasswordInput, label="كلمة المرور الجديدة")
    new_password_confirm = forms.CharField(required=False, widget=forms.PasswordInput, label="تأكيد كلمة المرور")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # أضف كلاس لكل الحقول
        for f in self.fields.values():
            f.widget.attrs.update({"class": "w-full border-gray-300 rounded-lg px-3 py-2"})


class CreateUserForm(forms.Form):
    username = forms.CharField(max_length=150, label="اسم المستخدم (Username)")
    email = forms.EmailField(required=False, label="البريد الإلكتروني")
    first_name = forms.CharField(required=False, label="الاسم الأول")
    last_name = forms.CharField(required=False, label="اسم العائلة")
    password = forms.CharField(widget=forms.PasswordInput, label="كلمة المرور")
    password_confirm = forms.CharField(widget=forms.PasswordInput, label="تأكيد كلمة المرور")
    is_active = forms.BooleanField(required=False, initial=True, label="مفعل")
    role = forms.ChoiceField(choices=ROLE_CHOICES, required=False, label="الدور")
    department = forms.ChoiceField(choices=DEPARTMENT_CHOICES, required=False, label="القسم")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.update({"class": "w-full border-gray-300 rounded-lg px-3 py-2"})

    def clean(self):
        cleaned = super().clean()
        p, pc = cleaned.get("password"), cleaned.get("password_confirm")
        if p and pc and p != pc:
            raise forms.ValidationError("كلمتا المرور غير متطابقتين.")
        return cleaned
