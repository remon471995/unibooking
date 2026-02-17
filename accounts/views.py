# accounts/views.py
from typing import Any
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import (
    get_user_model,
    logout as auth_logout,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
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
    بيتأكد الأول إن فيه login.
    """
    return login_required(
        user_passes_test(lambda u: u.is_superuser, login_url="/login/")(view_func)
    )


# ---------- صفحات الحساب (المستخدم العادي) ----------
@login_required
def my_profile(request: HttpRequest) -> HttpResponse:
    """
    صفحة 'حسابي' — تغيير كلمة المرور وتعديل الاسم الأول/الأخير.
    بنميّز نوع الفورم المستَخدم في POST عن طريق الحقل المخفي 'form'.
    """
    pwd_form = PasswordChangeForm(user=request.user)

    if request.method == "POST":
        which = request.POST.get("form")

        # تغيير كلمة المرور الخاصة بالمستخدم الحالي
        if which == "password":
            pwd_form = PasswordChangeForm(user=request.user, data=request.POST)
            if pwd_form.is_valid():
                user = pwd_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "تم تغيير كلمة المرور بنجاح.")
                return redirect("accounts:my_profile")
            else:
                messages.error(request, "من فضلك صحح الأخطاء في نموذج كلمة المرور.")

        # تعديل الاسم الأول/الأخير
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
    مسار منفصل لتغيير الباسورد، يعيد استخدام my_profile داخليًا.
    """
    if request.method == "POST":
        request.POST = request.POST.copy()
        request.POST["form"] = "password"
    return my_profile(request)


def logout_view(request: HttpRequest) -> HttpResponse:
    """تسجيل خروج."""
    auth_logout(request)
    return redirect("login")


# ---------- إدارة المستخدمين (سوبر فقط) ----------
@super_required
def manage_staff(request: HttpRequest) -> HttpResponse:
    """
    عرض جميع المستخدمين + تنفيذ إجراءات جماعية عبر BulkActionForm.
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

        if action == "deactivate":
            count = 0
            for u in qs:
                if u == request.user:
                    continue
                u.is_active = not u.is_active
                u.save()
                count += 1
            messages.success(request, f"تم تغيير حالة {count} مستخدم.")

        elif action == "set_department":
            dep = bulk_form.cleaned_data["department"]
            for u in qs:
                profile, _ = UserProfile.objects.get_or_create(user=u)
                profile.department = dep
                profile.save()
            messages.success(request, "تم تعيين القسم للمستخدمين المحددين.")

        elif action == "assign_leader":
            for u in qs:
                profile, _ = UserProfile.objects.get_or_create(user=u)
                profile.role = "leader"
                profile.save()
            messages.success(request, "تم تعيين الدور Leader للمستخدمين المحددين.")

        elif action == "change_role":
            role = bulk_form.cleaned_data["role"]
            for u in qs:
                profile, _ = UserProfile.objects.get_or_create(user=u)
                profile.role = role
                profile.save()
            messages.success(request, "تم تغيير الأدوار للمستخدمين المحددين.")

        elif action == "change_password":
            new_pass = bulk_form.cleaned_data["new_password"]
            if not new_pass:
                messages.error(request, "ادخل كلمة مرور جديدة في حقل كلمة المرور.")
            else:
                for u in qs:
                    u.set_password(new_pass)
                    u.save()
                messages.success(request, "تم تغيير كلمة المرور للمستخدمين المحددين.")

        elif action == "set_target":
            # هنا تكمّل الربط مع نظام التارجت لو حابب
            messages.success(request, "تم تنفيذ إجراء التارجت (بحاجة لربط فعلي).")

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
    """إنشاء مستخدم جديد من الواجهة."""
    if request.method == "POST":
        form = CreateUserForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                u = User.objects.create_user(
                    username=data["username"],
                    email=data.get("email") or "",
                )
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
            except Exception as e:
                messages.error(request, f"حدث خطأ أثناء الإنشاء: {e}")
        else:
            messages.error(request, "يرجى تصحيح الأخطاء أدناه.")
    else:
        form = CreateUserForm()

    return render(request, "accounts/create_user.html", {"form": form})


@super_required
def edit_user(request: HttpRequest, user_id: int) -> HttpResponse:
    """تعديل بيانات مستخدم + ملفه الشخصي."""
    user = get_object_or_404(User, id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=user)

    if request.method == "POST":
        uform = UserBasicForm(request.POST, instance=user)
        pform = ProfileForm(
            request.POST,
            request.FILES,
            instance=profile,
            request_user=request.user,
        )

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

    context = {
        "uform": uform,
        "pform": pform,
        "the_user": user,
    }
    return render(request, "accounts/edit_user.html", context)


@super_required
def change_user_password(request: HttpRequest, user_id: int) -> HttpResponse:
    """السوبر يغيّر باسورد لمستخدم معيّن."""
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
    """تفعيل/تعطيل مستخدم (مع منع تعطيل نفسك)."""
    user = get_object_or_404(User, id=user_id)
    if user == request.user:
        messages.error(request, "لا يمكنك تعطيل حسابك بنفسك.")
        return redirect("accounts:manage_staff")

    user.is_active = not user.is_active
    user.save()
    state = "تفعيل" if user.is_active else "تعطيل"
    messages.success(request, f"تم {state} حساب {user.username}.")
    return redirect("accounts:manage_staff")
