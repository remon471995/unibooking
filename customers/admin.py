from django.contrib import admin

from .models import CustomerProfile


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ("phone_key", "email", "no_marketing", "updated_at", "updated_by")
    search_fields = ("phone_key", "email")
    list_filter = ("no_marketing",)
