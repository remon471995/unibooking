def dept_context(request):
    """Top bar data: which departments the user may write to / open, and the live counters."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from django.db.models import Q
    from core.models import Notification
    from .models import Department, Ticket
    from .permissions import allowed_department_slugs, inbox_slugs

    inbox = inbox_slugs(user)
    open_qs = Ticket.objects.exclude(status__in=Ticket.CLOSED_STATUSES)
    # requests each of my departments still owes an answer on (new request, or the requester wrote last)
    badges = {s: 0 for s in inbox}
    for row in open_qs.filter(awaiting_staff=True, department__slug__in=inbox).values("department__slug"):
        badges[row["department__slug"]] += 1
    unread_qs = Notification.objects.filter(Q(to_user=user) | Q(to_superusers=True), is_read=False)
    return {
        "hd_write_slugs": allowed_department_slugs(user),
        "hd_inbox_slugs": inbox,
        "hd_badges": badges,
        "hd_mine": open_qs.filter(assigned_to=user, awaiting_staff=True).count(),
        "hd_unread": unread_qs.count(),
        "hd_bell_items": list(unread_qs.order_by("-created_at")[:8]),
    }
