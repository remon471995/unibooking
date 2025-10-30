from django.contrib import admin
from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "department", "phone", "job_title")
    search_fields = ("user__username", "user__first_name", "user__last_name", "phone", "job_title")
    list_filter = ("department",)
