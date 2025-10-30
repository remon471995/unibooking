from __future__ import annotations
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Department, DepartmentMembership, TicketTag, Ticket, TicketMessage, TicketAttachment,
    DepartmentAnnouncement, CannedReply, TicketCategory
)

# ========= Departments =========

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "manager", "email", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "email", "manager__username")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("manager",)


@admin.register(DepartmentMembership)
class DepartmentMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "department", "role", "is_active", "joined_at")
    list_filter = ("department", "role", "is_active")
    search_fields = ("user__username", "user__email", "department__name")
    autocomplete_fields = ("user", "department")
    list_select_related = ("user", "department")

# ========= Taxonomy =========

@admin.register(TicketTag)
class TicketTagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "color_preview")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="Color")
    def color_preview(self, obj: TicketTag):
        return format_html(
            '<span style="display:inline-block;width:1.25rem;height:1.25rem;border-radius:4px;'
            'border:1px solid #eee;background:{}"></span> {}',
            obj.color,
            obj.color,
        )

# ========= Tickets =========

class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0
    fields = ("created_at", "sender", "is_internal_note", "body")
    readonly_fields = ("created_at", "sender")
    show_change_link = True


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = (
        "id", "subject", "department", "status", "priority",
        "requester", "assigned_to", "created_at", "sla_due_at", "resolved_at",
    )
    list_filter = ("department", "status", "priority", "tags", "created_at")
    search_fields = (
        "subject", "related_ref", "requester__username", "assigned_to__username",
        "department__name",
    )
    autocomplete_fields = ("requester", "assigned_to", "department")
    filter_horizontal = ("tags", "watchers")
    inlines = [TicketMessageInline]
    readonly_fields = ("created_at", "updated_at", "resolved_at")

# ========= Messages & Attachments =========

class TicketAttachmentInline(admin.TabularInline):
    model = TicketAttachment
    extra = 0
    readonly_fields = ("uploaded_at", "uploaded_by")


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = ("id", "ticket", "sender", "is_internal_note", "short_body", "created_at")
    list_filter = ("is_internal_note", "created_at")
    search_fields = ("body", "ticket__subject", "sender__username")
    autocomplete_fields = ("ticket", "sender")
    inlines = [TicketAttachmentInline]

    @admin.display(description="Body")
    def short_body(self, obj: TicketMessage):
        txt = (obj.body or "").replace("\n", " ")
        return (txt[:80] + "…") if len(txt) > 80 else txt


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "uploaded_by", "file", "uploaded_at")
    search_fields = ("message__ticket__subject", "uploaded_by__username", "file")
    autocomplete_fields = ("message", "uploaded_by")
    date_hierarchy = "uploaded_at"

# ========= Announcements & Canned =========

@admin.register(DepartmentAnnouncement)
class DepartmentAnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "is_pinned", "created_by", "created_at")
    list_filter = ("department", "is_pinned")
    search_fields = ("title", "body", "department__name")
    autocomplete_fields = ("department", "created_by")


@admin.register(CannedReply)
class CannedReplyAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "is_public")
    list_filter = ("department", "is_public")
    search_fields = ("title", "body", "department__name")
    autocomplete_fields = ("department",)

@admin.register(TicketCategory)
class TicketCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "slug", "is_active", "order")
    list_filter = ("department", "is_active")
    search_fields = ("name", "slug", "department__name")
    autocomplete_fields = ("department",)
    ordering = ("department", "order", "name")
