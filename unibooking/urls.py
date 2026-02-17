# unibooking/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from accounts import views as accounts_views

urlpatterns = [
    # لوحة الإدارة
    path("admin/", admin.site.urls),

    # Core
    path("", include("core.urls")),

    # Accounts (namespace = accounts)
    path("account/", include(("accounts.urls", "accounts"), namespace="accounts")),

    # i18n
    path("i18n/", include("django.conf.urls.i18n")),

    # Auth
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", accounts_views.logout_view, name="logout"),
]

# فعّل helpdesk فقط لو:
# 1) متسجّل في INSTALLED_APPS
# 2) ومسموح بيه من الإعدادات (HELPDESK_ENABLED = True)
if (
    "helpdesk" in settings.INSTALLED_APPS
    and getattr(settings, "HELPDESK_ENABLED", True)
):
    urlpatterns += [
        path("helpdesk/", include(("helpdesk.urls", "helpdesk"), namespace="helpdesk")),
    ]

# Static/Media أثناء التطوير
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

