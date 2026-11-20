from django.contrib import admin

from .models import ModificationRequest


@admin.register(ModificationRequest)
class ModificationRequestAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "ref", "customer", "delta_sell", "delta_net", "delta_paid", "status", "requested_by_name")
    list_filter = ("status", "kind")
    search_fields = ("ref", "customer", "requested_by_name")
