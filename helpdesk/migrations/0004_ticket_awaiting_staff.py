from django.db import migrations, models


def seed_flag(apps, schema_editor):
    """Requests that already exist: waiting for the department only if the requester wrote last and it is not closed."""
    Ticket = apps.get_model("helpdesk", "Ticket")
    Message = apps.get_model("helpdesk", "TicketMessage")
    for t in Ticket.objects.exclude(status__in=["resolved", "cancelled"]):
        last = Message.objects.filter(ticket=t, is_internal_note=False).order_by("-created_at", "-id").first()
        if last is None or last.sender_id == t.requester_id:
            Ticket.objects.filter(pk=t.pk).update(awaiting_staff=True)


class Migration(migrations.Migration):

    dependencies = [
        ("helpdesk", "0003_alter_ticket_priority_alter_ticket_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="awaiting_staff",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.RunPython(seed_flag, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="ticket",
            name="awaiting_staff",
            field=models.BooleanField(db_index=True, default=True),
        ),
    ]
