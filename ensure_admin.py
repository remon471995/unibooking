import os
from django.contrib.auth import get_user_model

User = get_user_model()
username = os.getenv("DJANGO_SUPERUSER_USERNAME")
password = os.getenv("DJANGO_SUPERUSER_PASSWORD")
email = os.getenv("DJANGO_SUPERUSER_EMAIL", "")

if not username or not password:
    print("ENSURE_ADMIN: DJANGO_SUPERUSER_USERNAME / DJANGO_SUPERUSER_PASSWORD are not set - skipped")
else:
    user, created = User.objects.get_or_create(username=username, defaults={"email": email})
    if email:
        user.email = email
    user.is_staff = True
    user.is_superuser = True
    user.is_active = True
    user.set_password(password)
    user.save()
    print("ENSURE_ADMIN: admin '%s' %s" % (username, "created" if created else "updated (password synced)"))
