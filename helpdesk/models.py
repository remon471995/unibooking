from __future__ import annotations

from datetime import timedelta
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.text import slugify
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

User = get_user_model()

# ========= الأقسام =========
class Department(models.Model):
    class Slug(models.TextChoices):
        SALES = "sales", "Sales"
        PRODUCT = "product", "Product"
        OPERATIONS = "operations", "Operations"
        AFTER_SALES = "after_sales", "After Sales"
        HR = "hr", "HR"

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    email = models.EmailField(blank=True)
    manager = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="managed_departments"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)  # لا default مع auto_now_add

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class DepartmentMembership(models.Model):
    class Role(models.TextChoices):
        VIEWER = "viewer", "Viewer"
        MEMBER = "member", "Member"
        LEADER = "leader", "Leader"

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="department_memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("department", "user")

    def __str__(self):
        return f"{self.user} @ {self.department} ({self.role})"


# ========= فئات التذاكر =========
class TicketCategory(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = (("department", "slug"),)
        ordering = ["department__name", "order", "name"]

    def __str__(self):
        return f"{self.department.name} / {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name) or "cat"
            candidate = base
            i = 1
            while TicketCategory.objects.filter(
                department=self.department, slug=candidate
            ).exclude(pk=self.pk).exists():
                i += 1
                candidate = f"{base}-{i}"
            self.slug = candidate
        super().save(*args, **kwargs)


# ========= الوسوم =========
class TicketTag(models.Model):
    name = models.CharField(max_length=40, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    color = models.CharField(max_length=7, default="#3b82f6", help_text="Hex color e.g. #3b82f6")

    def __str__(self):
        return self.name


# ========= التذاكر =========
class Ticket(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "مفتوح (جديد)"
        IN_PROGRESS = "in_progress", "قيد التنفيذ"
        PENDING_ENTRY = "pending_entry", "بانتظار الداتا انتري"
        WAITING_THIRD_PARTY = "waiting_third_party", "بانتظار طرف ثالث (فندق / مورد / أوبريشن / FFT)"
        CALLS = "calls", "اتصالات (مطلوب مكالمة)"
        PENDING = "pending", "بانتظار رد العميل / الأجنت"
        ON_HOLD = "on_hold", "متوقف مؤقتاً"
        RESOLVED = "resolved", "تم الحل"
        CANCELLED = "cancelled", "مُلغى"

    CLOSED_STATUSES = ("resolved", "cancelled")
    _TONES = {
        "open": "blue", "in_progress": "indigo", "pending_entry": "violet",
        "waiting_third_party": "orange", "calls": "teal", "pending": "amber",
        "on_hold": "gray", "resolved": "emerald", "cancelled": "red",
    }
    _BADGE = {
        "blue": "bg-blue-50 text-blue-700 dark:bg-blue-900/40 dark:text-blue-200",
        "indigo": "bg-indigo-50 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200",
        "violet": "bg-violet-50 text-violet-700 dark:bg-violet-900/40 dark:text-violet-200",
        "orange": "bg-orange-50 text-orange-700 dark:bg-orange-900/40 dark:text-orange-200",
        "teal": "bg-teal-50 text-teal-700 dark:bg-teal-900/40 dark:text-teal-200",
        "amber": "bg-amber-50 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200",
        "gray": "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200",
        "emerald": "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200",
        "red": "bg-red-50 text-red-700 dark:bg-red-900/40 dark:text-red-200",
    }
    _DOT = {
        "blue": "bg-blue-500", "indigo": "bg-indigo-500", "violet": "bg-violet-500", "orange": "bg-orange-500",
        "teal": "bg-teal-500", "amber": "bg-amber-500", "gray": "bg-gray-400", "emerald": "bg-emerald-500", "red": "bg-red-500",
    }
    _TEXT = {
        "blue": "text-blue-600", "indigo": "text-indigo-600", "violet": "text-violet-600", "orange": "text-orange-600",
        "teal": "text-teal-600", "amber": "text-amber-600", "gray": "text-gray-600", "emerald": "text-green-600", "red": "text-red-600",
    }

    @property
    def status_tone(self):
        return self._TONES.get(self.status, "gray")

    @property
    def status_badge(self):
        return self._BADGE[self.status_tone]

    @property
    def status_dot(self):
        return self._DOT[self.status_tone]

    @property
    def status_text(self):
        return self._TEXT[self.status_tone]

    @property
    def is_closed(self):
        return self.status in self.CLOSED_STATUSES

    class Priority(models.TextChoices):
        LOW = "low", "منخفضة"
        NORMAL = "normal", "عادية"
        HIGH = "high", "عالية"
        URGENT = "urgent", "عاجلة"

    subject = models.CharField(max_length=200)
    # a request CS forwards to Operations / FFT points back to the sales request it came from
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="tickets")
    requester = models.ForeignKey(User, on_delete=models.PROTECT, related_name="requested_tickets")
    assigned_to = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_tickets"
    )

    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)

    category = models.ForeignKey(TicketCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")

    related_content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    related_object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object = GenericForeignKey("related_content_type", "related_object_id")

    related_ref = models.CharField(max_length=100, blank=True)
    related_url = models.URLField(blank=True)

    sla_minutes = models.PositiveIntegerField(default=1440)
    sla_due_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    watchers = models.ManyToManyField(User, blank=True, related_name="watching_tickets")
    tags = models.ManyToManyField(TicketTag, blank=True, related_name="tickets")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} — {self.subject}"

    def get_absolute_url(self):
        return reverse("helpdesk:ticket_detail", args=[self.pk])

    def compute_default_sla(self):
        mapping = {
            self.Priority.URGENT: 240,
            self.Priority.HIGH: 480,
            self.Priority.NORMAL: 1440,
            self.Priority.LOW: 2880,
        }
        return mapping.get(self.priority, 1440)

    def save(self, *args, **kwargs):
        creating = self.pk is None
        if not self.sla_minutes:
            self.sla_minutes = self.compute_default_sla()
        if not self.sla_due_at:
            self.sla_due_at = timezone.now() + timedelta(minutes=int(self.sla_minutes))

        if not creating:
            old = Ticket.objects.filter(pk=self.pk).values("status").first()
            if old:
                old_status = old["status"]
                if self.status == self.Status.RESOLVED and old_status != self.Status.RESOLVED:
                    self.resolved_at = timezone.now()
                elif old_status == self.Status.RESOLVED and self.status != self.Status.RESOLVED:
                    self.resolved_at = None

        super().save(*args, **kwargs)


# ========= رسائل ومرفقات =========
class TicketMessage(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    # خليّناه مؤقتًا يقبل NULL لتفادي برومبتات وقت الهجرة
    sender = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="ticket_messages",
        null=True, blank=True
    )
    body = models.TextField()
    is_internal_note = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Msg#{self.pk} on Ticket#{self.ticket_id}"


class TicketAttachment(models.Model):
    message = models.ForeignKey(TicketMessage, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="tickets/%Y/%m/%d")
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="ticket_attachments"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)  # لا default مع auto_now_add


# ========= إعلانات وردود جاهزة =========
class DepartmentAnnouncement(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="announcements")
    title = models.CharField(max_length=200)
    body = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)  # لا default مع auto_now_add
    is_pinned = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_pinned", "-created_at"]

    def __str__(self):
        return self.title


class CannedReply(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="canned_replies")
    title = models.CharField(max_length=120)
    body = models.TextField()
    is_public = models.BooleanField(default=True)

    class Meta:
        ordering = ["department", "title"]

    def __str__(self):
        return f"{self.department.name} — {self.title}"
