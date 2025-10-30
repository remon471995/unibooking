# accounts/views.py
from typing import Any
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import get_user_model, logout as auth_logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.http import HttpRequest, HttpResponse

from .forms import (
    UserBasicForm,
    ProfileForm,
    CreateUserForm,
    BulkActionForm,
)
from .models import UserProfile

User = get_user_model()


# ---------- ديكور للتحكم (سوبر فقط) ----------
def super_required(view_func):
    """
    ديكور: يسمح فقط بالسوبر (is_superuser).
    يركّب login_required فوق user_passes_test لإعادة التوجيه إلى /login/ إذا لم يكن مسجل دخول.
    """
    # نرتب الديكورات بحيث يتم التحقق من تسجيل الدخول أولاً
    return login_required(user_passes_test(lambda u: u.is_superuser, login_url="/login/")(view_func))


# ---------- صفحات الحساب (متاحة للمستخدم العادي) ----------
@login_required
def my_profile(request: HttpRequest) -> HttpResponse:
    """
    صفحة 'حسابي' — تغيير كلمة المرور (PasswordChangeForm) وتعديل بيانات بسيطة.
    يتم تمييز الفورم المرسل بواسطة field مخفي 'form' بقيمة 'password' أو 'profile'.
    """
    pwd_form = PasswordChangeForm(user=request.user)

    if request.method == "POST":
        which = request.POST.get("form")
        # ===== تغيير كلمة المرور للمستخدم نفسه =====
        if which == "password":
            pwd_form = PasswordChangeForm(user=request.user, data=request.POST)
            if pwd_form.is_valid():
                user = pwd_form.save()
                update_session_auth_hash(request, user)  # يبقي المستخدم متصل بعد تغيير الباسورد
                messages.success(request, "تم تغيير كلمة المرور بنجاح.")
                return redirect("accounts:my_profile")
            else:
                messages.error(request, "من فضلك صحح الأخطاء الظاهرة بالأسفل.")

        # ===== تعديل معلومات بسيطة (مثال: الاسم الأول والآخر) =====
        elif which == "profile":
            first_name = request.POST.get("first_name", "").strip()
            last_name = request.POST.get("last_name", "").strip()
            request.user.first_name = first_name
            request.user.last_name = last_name
            request.user.save()
            messages.success(request, "تم حفظ بيانات الحساب.")
            return redirect("accounts:my_profile")

    context = {
        "pwd_form": pwd_form,
    }
    return render(request, "accounts/my_profile.html", context)


@login_required
def change_password(request: HttpRequest) -> HttpResponse:
    """
    مسار منفصل يضبط request.POST['form']='password' ثم يعيد استخدام my_profile لمعالجة POST.
    هذا يمكّن وجود رابط مستقل لتغيير الباسورد لكن معالجة الكود تبقى في my_profile.
    """
    if request.method == "POST":
        request.POST = request.POST.copy()
        request.POST["form"] = "password"
    return my_profile(request)


def logout_view(request: HttpRequest) -> HttpResponse:
    """تسجيل خروج وإعادة توجيه لصفحة تسجيل الدخول."""
    auth_logout(request)
    return redirect("login")


# ---------- واجهة إدارة المستخدمين (سوبر فقط) ----------
@super_required
def manage_staff(request: HttpRequest) -> HttpResponse:
    """
    عرض جميع المستخدمين + تنفيذ إجراءات جماعية عبر BulkActionForm.
    هذه الصفحة مرئية فقط للسوبر بفضل @super_required.
    """
    users = User.objects.select_related("profile").order_by("username")
    bulk_form = BulkActionForm(request.POST or None)

    if request.method == "POST" and bulk_form.is_valid():
        action = bulk_form.cleaned_data["action"]
        ids = request.POST.getlist("selected")
        if not ids:
            messages.error(request, "لم تختار أي مستخدم.")
            return redirect("accounts:manage_staff")
        qs = User.objects.filter(id__in=ids)

        # تنفيذ الإجراءات المختلفة
        if action == "deactivate":
            for u in qs:
                # لا تسمح للسوبر بتعطيل نفسه عن طريق هذا الإجراء
                if u == request.user:
                    continue
                u.is_active = not u.is_active
                u.save()
            messages.success(request, "تم تبديل حالة التفعيل للمستخدمين المحددين.")

        elif action == "set_department":
            dep = bulk_form.cleaned_data["department"]
            for u in qs:
                profile, _ = UserProfile.objects.get_or_create(user=u)
                profile.department = dep
                profile.save()
            messages.success(request, "تم نقل المستخدمين للقسم المحدد.")

        elif action == "assign_leader":
            for u in qs:
                profile, _ = UserProfile.objects.get_or_create(user=u)
                profile.role = "leader"
                profile.save()
            messages.success(request, "تم تعيين الليدر للمستخدمين المحددين.")

        elif action == "change_role":
            role = bulk_form.cleaned_data["role"]
            for u in qs:
                profile, _ = UserProfile.objects.get_or_create(user=u)
                profile.role = role
                profile.save()
            messages.success(request, "تم تغيير الدور للمستخدمين المحددين.")

        elif action == "change_password":
            new_pass = bulk_form.cleaned_data["new_password"]
            if not new_pass:
                messages.error(request, "ادخل كلمة مرور جديدة في الحقل الخاص بها.")
            else:
                for u in qs:
                    u.set_password(new_pass)
                    u.save()
                messages.success(request, "تم تغيير كلمة المرور للمستخدمين المحددين.")

        elif action == "set_target":
            # هنا تحتاج ربط منطقي مع app التارجت عندك (مثال targets.models.StaffTarget)
            # الآن نعرض فقط رسالة نجاح كتمثيل:
            messages.success(request, "تم تطبيق التارجت (تحتاج ربط حفظ فعلي في الكود).")

        else:
            messages.warning(request, "الإجراء غير معروف.")
        return redirect("accounts:manage_staff")

    context = {
        "users": users,
        "bulk_form": bulk_form,
    }
    return render(request, "accounts/manage_staff.html", context)


@super_required
def create_user(request: HttpRequest) -> HttpResponse:
    """إنشاء مستخدم جديد من الواجهة (سوبر فقط)."""
    if request.method == "POST":
        form = CreateUserForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            # أنشئ المستخدم بطريقة create_user لتضمن إعداد الباسورد بشكل صحيح
            u = User.objects.create_user(username=data["username"], email=data.get("email") or "")
            u.first_name = data.get("first_name") or ""
            u.last_name = data.get("last_name") or ""
            u.is_active = data.get("is_active", True)
            u.set_password(data["password"])
            u.save()

            profile, _ = UserProfile.objects.get_or_create(user=u)
            if data.get("department"):
                profile.department = data.get("department")
            if data.get("role"):
                profile.role = data.get("role")
            profile.save()

            messages.success(request, "تم إنشاء المستخدم بنجاح.")
            return redirect("accounts:manage_staff")
    else:
        form = CreateUserForm()
    return render(request, "accounts/create_user.html", {"form": form})


@super_required
def edit_user(request: HttpRequest, user_id: int) -> HttpResponse:
    """تعديل بيانات مستخدم + ملفه الشخصي (سوبر فقط يقدر يصلح جميع الحقول)."""
    user = get_object_or_404(User, id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=user)

    if request.method == "POST":
        uform = UserBasicForm(request.POST, instance=user)
        pform = ProfileForm(request.POST, request.FILES, instance=profile, request_user=request.user)
        if uform.is_valid() and pform.is_valid():
            uform.save()
            pform.save()
            messages.success(request, "تم حفظ بيانات المستخدم.")
            return redirect("accounts:manage_staff")
        else:
            messages.error(request, "صحح الأخطاء ثم حاول مرة أخرى.")
    else:
        uform = UserBasicForm(instance=user)
        pform = ProfileForm(instance=profile, request_user=request.user)

    return render(request, "accounts/edit_user.html", {"uform": uform, "pform": pform, "the_user": user})


@super_required
def change_user_password(request: HttpRequest, user_id: int) -> HttpResponse:
    """السوبر يغير باسورد لمستخدم (بدون الحاجة للباس القديم)."""
    user = get_object_or_404(User, id=user_id)
    if request.method == "POST":
        new_password = request.POST.get("new_password")
        confirm = request.POST.get("confirm_password")
        if not new_password:
            messages.error(request, "ادخل كلمة المرور الجديدة.")
        elif new_password != confirm:
            messages.error(request, "كلمتا المرور غير متطابقتين.")
        else:
            user.set_password(new_password)
            user.save()
            messages.success(request, f"تم تغيير كلمة مرور {user.username}.")
            return redirect("accounts:manage_staff")
    return render(request, "accounts/change_user_password.html", {"the_user": user})


@super_required
def toggle_active(request: HttpRequest, user_id: int) -> HttpResponse:
    """سويتش تفعيل/تعطيل مستخدم (لا تسمح للسوبر بتعطيل نفسه من هنا)."""
    user = get_object_or_404(User, id=user_id)
    if user == request.user:
        messages.error(request, "لا يمكنك تعطيل/تفعيل حسابك بنفسك هنا.")
        return redirect("accounts:manage_staff")
    user.is_active = not user.is_active
    user.save()
    messages.success(request, f"تم تحديث حالة التفعيل للمستخدم {user.username}.")
    return redirect("accounts:manage_staff")
