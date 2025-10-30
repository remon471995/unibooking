from __future__ import annotations
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
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
    manager = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="managed_departments")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

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


# ========= فئات التذاكر (خاصة بكل قسم) =========
class TicketCategory(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = (("department", "slug"),)
        ordering = ["department__name", "order", "name"]

    def __str__(self):
        return f"{self.department.name} / {self.name}"


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
        OPEN = "open", "Open"
        PENDING = "pending", "Pending (Waiting Customer)"
        ON_HOLD = "on_hold", "On Hold"
        RESOLVED = "resolved", "Resolved"
        CANCELLED = "cancelled", "Cancelled"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    subject = models.CharField(max_length=200)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="tickets")
    requester = models.ForeignKey(User, on_delete=models.PROTECT, related_name="requested_tickets")
    assigned_to = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_tickets")

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)

    # فئة حسب القسم
    category = models.ForeignKey(TicketCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")

    # ربط اختياري بأي كيان داخلي
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
            self.sla_due_at = timezone.now() + timezone.timedelta(minutes=int(self.sla_minutes))

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
    sender = models.ForeignKey(User, on_delete=models.PROTECT, related_name="ticket_messages")
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
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)


# ========= إعلانات وردود جاهزة =========
class DepartmentAnnouncement(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="announcements")
    title = models.CharField(max_length=200)
    body = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
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
