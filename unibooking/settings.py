# unibooking/settings.py
from pathlib import Path
import os
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

# === Core ===
SECRET_KEY = "change-me"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",

    # Apps
    "core.apps.CoreConfig",
    "helpdesk.apps.HelpdeskConfig",
    "accounts",    
    "widget_tweaks",
    "storages",                 # اختياري S3
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "unibooking.urls"

# === Templates ===
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # الإشعارات في الشريط العلوي
                "core.context_processors.notifications_context",
            ],
        },
    },
]

WSGI_APPLICATION = "unibooking.wsgi.application"
ASGI_APPLICATION = "unibooking.asgi.application"

# === Database (SQLite) ===
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# === i18n / tz ===
LANGUAGE_CODE = "ar"
LANGUAGES = [
    ("ar", _("Arabic")),
    ("en", _("English")),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

TIME_ZONE = "Africa/Cairo"
USE_I18N = True
USE_TZ = True

# للتجربة في التطوير
DEFAULT_FROM_EMAIL = "noreply@unibooking.local"
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# === Static & Media ===
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# مهم للمرفقات (الفواتير/الفوّتشر/التحويلات)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# (اختياري) زيادة حدود حجم الرفع/الاستقبال
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024   # 100MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024   # 100MB

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# === Auth redirects ===
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# === اختياري: تخزين S3 عند تفعيل USE_S3 ===
if os.getenv("USE_S3", "0") == "1":
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL")
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

# عدد الأيام قبل ميعاد القسط لإظهار التنبيه
INSTALLMENT_REMINDER_DAYS = 5
