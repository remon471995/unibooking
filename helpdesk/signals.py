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
