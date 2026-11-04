from django.db import migrations

MODELS = ["HotelBooking", "FlightBooking", "OtherBooking", "Payment", "FlightPayment", "OtherPayment"]


def approve_existing(apps, schema_editor):
    """Everything that existed before the review cycle was introduced counts as already approved."""
    for name in MODELS:
        apps.get_model("core", name).objects.all().update(review_status="approved")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0065_flightbooking_review_note_and_more"),
    ]

    operations = [migrations.RunPython(approve_existing, migrations.RunPython.noop)]
