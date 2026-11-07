from __future__ import annotations
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings

from .models import Ticket, TicketMessage

DEFAULT_FROM = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@unibooking.local")


@receiver(post_save, sender=Ticket)
def notify_new_ticket(sender, instance: Ticket, created, **kwargs):
    """إشعار بإنشاء تذكرة جديدة: يرسل لمدير القسم + إيميل القسم + المعين (لو موجود)."""
    if not created:
        return

    subject = f"[UniBooking] Ticket #{instance.pk}: {instance.subject}"
    body = (
        f"قسم: {instance.department.name}\n"
        f"طالب: {instance.requester}\n"
        f"أولوية: {instance.get_priority_display()}\n"
        f"الحالة: {instance.get_status_display()}\n"
        f"رابط داخلي: {instance.get_absolute_url()}\n"
    )

    to = []
    if instance.department.email:
        to.append(instance.department.email)
    if instance.department.manager and instance.department.manager.email:
        to.append(instance.department.manager.email)
    if instance.assigned_to and instance.assigned_to.email:
        to.append(instance.assigned_to.email)

    if to:
        try:
            send_mail(subject, body, DEFAULT_FROM, list(set(to)), fail_silently=True)
        except Exception:
            pass


@receiver(post_save, sender=TicketMessage)
def notify_new_message(sender, instance: TicketMessage, created, **kwargs):
    """
    إشعار برسالة جديدة:
      - إن كانت ملاحظة داخلية: تُخطر المعيّن ومدير القسم والـ watchers (بدون الطالب).
      - وإلا: تُخطر الطالب + المعيّن + مدير القسم + الـ watchers.
    """
    if getattr(instance, "_system_note", False):
        return          # hand-over / forward / reassign notes are logged silently
    if not created:
        return

    ticket = instance.ticket
    subject = f"[UniBooking] Update Ticket #{ticket.pk}"
    preview = (instance.body or "")[:500]
    body = (
        f"مرسل: {instance.sender}\n"
        f"نوع: {'Internal Note' if instance.is_internal_note else 'Public Message'}\n\n"
        f"{preview}...\n\n"
        f"رابط داخلي: {ticket.get_absolute_url()}\n"
    )

    emails = set()

    # المعيّن + مدير القسم دائماً
    if ticket.assigned_to and ticket.assigned_to.email:
        emails.add(ticket.assigned_to.email)
    if ticket.department.manager and ticket.department.manager.email:
        emails.add(ticket.department.manager.email)

    # الـ watchers
    for u in ticket.watchers.all():
        if getattr(u, "email", None):
            emails.add(u.email)

    # الطالب فقط إن لم تكن ملاحظة داخلية
    if not instance.is_internal_note and getattr(ticket.requester, "email", None):
        emails.add(ticket.requester.email)
    else:
        # في حالة الملاحظة الداخلية، لا ترسل للطالب حتى لو ضمن الـ watchers
        if getattr(ticket.requester, "email", None) in emails:
            emails.discard(ticket.requester.email)

    if emails:
        try:
            send_mail(subject, body, DEFAULT_FROM, list(emails), fail_silently=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Staff department  ->  helpdesk department membership
# (set the department on the employee in "إدارة الموظفين" and he joins that inbox automatically)
# ---------------------------------------------------------------------------
from django.db.models.signals import post_save as _post_save  # noqa: E402

PROFILE_DEPT_TO_SLUG = {"cs": "cs", "ops": "operations", "quotation": "quotation", "fft": "fft"}


def sync_membership(profile, only_add=False):
    from .models import Department, DepartmentMembership
    wanted = PROFILE_DEPT_TO_SLUG.get(profile.department)
    for dept in Department.objects.filter(slug__in=PROFILE_DEPT_TO_SLUG.values()):
        m = DepartmentMembership.objects.filter(user=profile.user, department=dept).first()
        if dept.slug == wanted:
            if m is None:
                DepartmentMembership.objects.create(user=profile.user, department=dept, is_active=True)
            elif not m.is_active:
                m.is_active = True
                m.save(update_fields=["is_active"])
        elif m is not None and m.is_active and not only_add:
            m.is_active = False
            m.save(update_fields=["is_active"])


def _connect_profile_sync():
    from accounts.models import UserProfile

    @receiver(_post_save, sender=UserProfile, weak=False)
    def _on_profile_save(sender, instance, **kwargs):
        sync_membership(instance)


_connect_profile_sync()


# ---------------------------------------------------------------------------
# In-app notifications (the bell), on top of the e-mails above
# ---------------------------------------------------------------------------
def _bell(users, message, ticket, exclude=None):
    from core.models import Notification
    seen = set()
    for u in users:
        if u is None or u.pk in seen or (exclude and u.pk == exclude.pk) or not u.is_active:
            continue
        seen.add(u.pk)
        Notification.objects.create(to_user=u, message=message, target_url=ticket.get_absolute_url())


@receiver(post_save, sender=Ticket, dispatch_uid="hd_bell_new_ticket")
def bell_new_ticket(sender, instance: Ticket, created, **kwargs):
    if not created:
        return
    dept = instance.department
    members = [m.user for m in dept.memberships.filter(is_active=True).select_related("user")]
    _bell(members + [dept.manager, instance.assigned_to],
          f"طلب جديد لقسم {dept.name}: {instance.subject}", instance, exclude=instance.requester)


@receiver(post_save, sender=TicketMessage, dispatch_uid="hd_bell_new_message")
def bell_new_message(sender, instance: TicketMessage, created, **kwargs):
    if not created or getattr(instance, "_system_note", False):
        return
    t = instance.ticket
    if instance.is_internal_note:
        people = [t.assigned_to, t.department.manager]
    else:
        people = [t.requester, t.assigned_to, t.department.manager] + list(t.watchers.all())
    _bell(people, f"رد جديد على الطلب #{t.pk}: {t.subject}", t, exclude=instance.sender)
