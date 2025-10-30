# unibooking/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from accounts import views as accounts_views

urlpatterns = [
    # لوحة الإدارة الأصلية (Django admin)
    path("admin/", admin.site.urls),

    # Core app (الصفحة الرئيسية، dashboard، الخ)
    path("", include("core.urls")),

    # تطبيقات أخرى
    path("helpdesk/", include(("helpdesk.urls", "helpdesk"), namespace="helpdesk")),

    # حسابات: لاحظ أننا نمرّر namespace "accounts"
    path("account/", include(("accounts.urls", "accounts"), namespace="accounts")),

    # i18n (اختياري)
    path("i18n/", include("django.conf.urls.i18n")),

    # Auth: صفحة تسجيل الدخول (Django generic)
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),

    # خيار تسجيل الخروج على مستوى المشروع (يمكن الإبقاء عليه أو حذفه
    # إذا كنت تستدعي logout عبر accounts:logout داخل accounts/urls.py)
    path("logout/", accounts_views.logout_view, name="logout"),
]

# Static/Media أثناء التطوير فقط
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
