# unibooking/settings.py
from pathlib import Path
import os
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

# === Helpers: read configuration from environment variables ===
def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


# === Core ===
# DEBUG is OFF unless you explicitly turn it on (set DJANGO_DEBUG=1 on your own machine only).
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY is not set. Generate one and add it to your environment variables.")

# Example: DJANGO_ALLOWED_HOSTS=crm.example.com,my-app.onrender.com
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
# Example: CSRF_TRUSTED_ORIGINS=https://crm.example.com,https://my-app.onrender.com
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

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
    'helpdesk',
    "accounts.apps.AccountsConfig",    
    "widget_tweaks",
    "storages",   # S3-compatible file storage
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",   # serves static files in production
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

# === Database ===
# Production: set DATABASE_URL (PostgreSQL). Local development falls back to SQLite.
import dj_database_url

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
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

# Email: prints to the console unless EMAIL_HOST is configured
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@unibooking.local")
if os.getenv("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.getenv("EMAIL_HOST")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
else:
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
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024     # files above 5MB stream to a temp file instead of RAM

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# === Auth redirects ===
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# === File storage (invoices, bank transfers, vouchers, avatars) ===
# NOTE: Django 5.1+ ignores the old DEFAULT_FILE_STORAGE setting, so STORAGES is required.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Production: use a PRIVATE S3-compatible bucket (AWS S3, Cloudflare R2, Supabase Storage S3...).
# Hosting disks are wiped on every deploy, so uploaded files would be lost without this.
if env_bool("USE_S3", False):
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL") or None
    AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME") or None
    AWS_DEFAULT_ACL = None            # keep files private
    AWS_QUERYSTRING_AUTH = True       # links are signed and expire
    AWS_QUERYSTRING_EXPIRE = 600      # seconds
    AWS_S3_FILE_OVERWRITE = False     # never overwrite a file with the same name
    STORAGES["default"] = {"BACKEND": "storages.backends.s3.S3Storage"}

# === Production security (active only when DEBUG is off) ===
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "3600"))  # raise to 31536000 once everything works
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.getenv("DJANGO_LOG_LEVEL", "INFO")},
}

# عدد الأيام قبل ميعاد القسط لإظهار التنبيه
INSTALLMENT_REMINDER_DAYS = 5

# تشغيل/إيقاف نظام الهيلب دِسك
HELPDESK_ENABLED = env_bool("HELPDESK_ENABLED", False)
