from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user_repr", "action", "model_label", "object_repr", "card_id")
    list_filter = ("action", "model")
    search_fields = ("user_repr", "object_repr", "object_id")
    date_hierarchy = "created_at"

    # للقراءة فقط
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
