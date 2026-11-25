import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def mark_existing_as_read(apps, schema_editor):
    """Everybody who already takes part in a request has seen what exists today."""
    Ticket = apps.get_model("helpdesk", "Ticket")
    Message = apps.get_model("helpdesk", "TicketMessage")
    Read = apps.get_model("helpdesk", "TicketRead")
    from django.utils import timezone
    now = timezone.now()
    for t in Ticket.objects.all():
        ids = {t.requester_id, t.assigned_to_id}
        ids |= set(t.watchers.values_list("pk", flat=True))
        ids |= set(Message.objects.filter(ticket=t, sender__isnull=False).values_list("sender_id", flat=True))
        Read.objects.bulk_create(
            [Read(ticket=t, user_id=i, last_read_at=now) for i in ids if i], ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("helpdesk", "0004_ticket_awaiting_staff"),
    ]

    operations = [
        migrations.CreateModel(
            name="TicketRead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("last_read_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reads", to="helpdesk.ticket")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ticket_reads", to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("ticket", "user")}},
        ),
        migrations.RunPython(mark_existing_as_read, migrations.RunPython.noop),
    ]
