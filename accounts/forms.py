from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from .models import UserProfile

User = get_user_model()

# ========= ثوابت للأدوار والأقسام =========

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


# ========= فورم بيانات المستخدم الأساسية (User) =========

class UserBasicForm(forms.ModelForm):
    """
    الفورم اللي بنستخدمه في تعديل المستخدم:
    - اسم المستخدم
    - البريد
    - الاسم الأول/الأخير
    - مفعّل أم لا
    """

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "is_active"]
        labels = {
            "username": "اسم المستخدم (Username)",
            "email": "البريد الإلكتروني",
            "first_name": "الاسم الأول",
            "last_name": "اسم العائلة",
            "is_active": "مفعَّل؟",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.update({
                "class": "w-full border-gray-300 rounded-lg px-3 py-2 text-sm"
            })


# ========= فورم البروفايل (UserProfile) =========

class ProfileForm(forms.ModelForm):
    """
    بيانات الموظف:
    - phone      : الموبايل
    - department : القسم
    - job_title  : المسمى الوظيفي
    - address    : العنوان
    - avatar     : الصورة
    - notes      : ملاحظات
    - role       : الدور (agent/leader/admin)
    """

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
        # نحتفظ بـ request_user عشان نتحكم في الصلاحيات
        self.request_user = kwargs.pop("request_user", None)
        super().__init__(*args, **kwargs)

        # خلّي القسم والدور مش إجباريين (required=False)
        self.fields["department"].required = False
        self.fields["role"].required = False

        # لو المستخدم مش سوبر، قفّل تعديل القسم والدور
        if not (self.request_user and self.request_user.is_superuser):
            self.fields["department"].disabled = True
            self.fields["role"].disabled = True

        # استايل موحد
        for name, f in self.fields.items():
            base_classes = "w-full border-gray-300 rounded-lg px-3 py-2 text-sm"
            if isinstance(f.widget, forms.Textarea):
                f.widget.attrs.setdefault("rows", 4)
            f.widget.attrs.update({"class": base_classes})

    def clean_department(self):
        dep = self.cleaned_data.get("department")
        # لو الحقل مقفول على المستخدم، رجّع القيمة القديمة
        if self.fields["department"].disabled:
            return self.instance.department
        return dep

    def clean_role(self):
        role = self.cleaned_data.get("role")
        if self.fields["role"].disabled:
            return self.instance.role
        return role


# ========= فورم تغيير كلمة المرور =========

class MyPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        label="كلمة المرور الحالية",
        widget=forms.PasswordInput(attrs={"class": "w-full px-3 py-2 rounded-lg border-gray-300"})
    )
    new_password1 = forms.CharField(
        label="كلمة المرور الجديدة",
        widget=forms.PasswordInput(attrs={"class": "w-full px-3 py-2 rounded-lg border-gray-300"})
    )
    new_password2 = forms.CharField(
        label="تأكيد كلمة المرور الجديدة",
        widget=forms.PasswordInput(attrs={"class": "w-full px-3 py-2 rounded-lg border-gray-300"})
    )


# ========= فورم الإجراءات الجماعية (Bulk actions) =========

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
    department = forms.ChoiceField(
        choices=[("", "— اختر قسمًا —")] + DEPARTMENT_CHOICES,
        required=False,
        label="القسم",
    )
    leader = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        label="الليدر",
    )
    target_value = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        label="قيمة التارجت",
    )
    target_month = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "month"}),
        label="شهر التارجت (سنة-شهر)",
    )
    role = forms.ChoiceField(
        choices=[("", "— اختر دورًا —")] + ROLE_CHOICES,
        required=False,
        label="الدور",
    )

    new_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput,
        label="كلمة المرور الجديدة",
    )
    new_password_confirm = forms.CharField(
        required=False,
        widget=forms.PasswordInput,
        label="تأكيد كلمة المرور",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.update({
                "class": "w-full border-gray-300 rounded-lg px-3 py-2 text-sm"
            })

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get("action")

        if action == "set_department" and not cleaned.get("department"):
            self.add_error("department", "اختر قسمًا لنقل المستخدمين إليه.")

        if action == "change_role" and not cleaned.get("role"):
            self.add_error("role", "اختر الدور الجديد.")

        if action == "change_password":
            p1 = cleaned.get("new_password")
            p2 = cleaned.get("new_password_confirm")
            if not p1 or not p2:
                self.add_error("new_password", "ادخل كلمة المرور الجديدة وتأكيدها.")
            elif p1 != p2:
                self.add_error("new_password_confirm", "كلمتا المرور غير متطابقتين.")

        return cleaned


# ========= فورم إنشاء مستخدم جديد =========

class CreateUserForm(forms.Form):
    username = forms.CharField(max_length=150, label="اسم المستخدم (Username)")
    email = forms.EmailField(required=False, label="البريد الإلكتروني")
    first_name = forms.CharField(required=False, label="الاسم الأول")
    last_name = forms.CharField(required=False, label="اسم العائلة")
    password = forms.CharField(widget=forms.PasswordInput, label="كلمة المرور")
    password_confirm = forms.CharField(widget=forms.PasswordInput, label="تأكيد كلمة المرور")
    is_active = forms.BooleanField(required=False, initial=True, label="مفعل")
    role = forms.ChoiceField(
        choices=[("", "— بدون تحديد —")] + ROLE_CHOICES,
        required=False,
        label="الدور",
    )
    department = forms.ChoiceField(
        choices=[("", "— بدون قسم —")] + DEPARTMENT_CHOICES,
        required=False,
        label="القسم",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.update({
                "class": "w-full border-gray-300 rounded-lg px-3 py-2 text-sm"
            })

    def clean(self):
        cleaned = super().clean()
        p = cleaned.get("password")
        pc = cleaned.get("password_confirm")
        if p and pc and p != pc:
            raise forms.ValidationError("كلمتا المرور غير متطابقتين.")
        return cleaned
