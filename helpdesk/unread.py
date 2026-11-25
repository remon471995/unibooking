"""What is NEW for a user in the helpdesk: a message somebody else wrote after he last opened the request.

Shown as the red number on واردى (and as "جديد" on the request), next to the bell notification.
Anyone who takes part in a request is told: the requester, the owner, the watchers and everybody who already wrote on it,
whichever department he is in.  Closed (resolved / cancelled) requests never count."""
from django.db.models import Max, Q
from django.utils import timezone

from .models import Ticket, TicketMessage, TicketRead


def unread_ticket_ids(user):
    mine = (Ticket.objects.exclude(status__in=Ticket.CLOSED_STATUSES)
            .filter(Q(requester=user) | Q(assigned_to=user) | Q(watchers=user) | Q(messages__sender=user))
            .distinct().values_list("pk", flat=True))
    ids = list(mine)
    if not ids:
        return set()
    reads = dict(TicketRead.objects.filter(user=user, ticket_id__in=ids).values_list("ticket_id", "last_read_at"))
    latest = (TicketMessage.objects.filter(ticket_id__in=ids, is_internal_note=False)
              .exclude(sender=user).values("ticket_id").annotate(m=Max("created_at")).order_by())
    out = set()
    for row in latest:
        seen = reads.get(row["ticket_id"])
        if seen is None or row["m"] > seen:
            out.add(row["ticket_id"])
    return out


def mark_ticket_read(user, ticket):
    """The user opened the request: the number on واردى drops and its bell notifications are read."""
    from core.models import Notification
    TicketRead.objects.update_or_create(ticket=ticket, user=user, defaults={"last_read_at": timezone.now()})
    Notification.objects.filter(to_user=user, is_read=False, target_url=ticket.get_absolute_url()).update(is_read=True)
