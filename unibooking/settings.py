from pathlib import Path
import os
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'change-me'
DEBUG = True
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Apps
    'core',
    'widget_tweaks',
    'storages',
    "django.contrib.humanize",   # ← عشان التنسيقات
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',  # ← مهم للغات
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'unibooking.urls'

# ✅ القوالب
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],  # templates على مستوى المشروع
        'APP_DIRS': True,                  # يقرأ templates داخل كل app أيضًا
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'unibooking.wsgi.application'
ASGI_APPLICATION = 'unibooking.asgi.application'

# قاعدة البيانات (SQLite)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# 🌍 اللغة والوقت
LANGUAGE_CODE = 'ar'   # خليها 'en' لو عايز الإنجليزي افتراضي
LANGUAGES = [
    ('ar', _('Arabic')),
    ('en', _('English')),
]
LOCALE_PATHS = [BASE_DIR / 'locale']

TIME_ZONE = 'Africa/Cairo'
USE_I18N = True
USE_TZ = True

# ملفات ستاتيك وميديا
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [BASE_DIR / 'static']     # اعمل مجلد static فاضي
STATIC_ROOT = BASE_DIR / 'staticfiles'       # للإنتاج (collectstatic)

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 🔑 توجيه بعد تسجيل الدخول/الخروج
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# ☁️ تخزين سحابي (اختياري لاحقًا)
if os.getenv('USE_S3', '0') == '1':
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_ENDPOINT_URL = os.getenv('AWS_S3_ENDPOINT_URL')  # S3-compatible
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
