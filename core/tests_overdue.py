from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.daily import send_installment_notifications
from core.installments import overdue_installments
from core.models import HotelBooking, Notification, Payment, Team, TeamMembership, UniBookingCard

User = get_user_model()


def make_user(username, role="agent"):
    u = User.objects.create_user(username, password="x")
    u.profile.role = role
    u.profile.save()
    return User.objects.get(pk=u.pk)


class OverdueInstallmentsTests(TestCase):
    def setUp(self):
        self.agent = make_user("agent")
        self.other = make_user("other_agent")
        self.de = make_user("de", "data_entry")
        self.today = timezone.localdate()
        self.card = UniBookingCard.objects.create(
            customer_name="Ali", mobile="1", nationality="EG", country="EG", created_by=self.agent)
        self.b = HotelBooking.objects.create(card=self.card, sell=Decimal("1000"), net=Decimal("800"))

    def _pay(self, paid="100", days_ago=3, **kw):
        return Payment.objects.create(
            booking_hotel=self.b, method="cash", paid_amount=Decimal(paid), sell_price=Decimal("1000"),
            net_price=Decimal("800"), installment_date=self.today - timedelta(days=days_ago), **kw)

    def test_a_late_installment_shows_for_its_agent_and_the_people_above_only(self):
        self._pay()
        for u in (self.agent, self.de):
            rows = overdue_installments(u)
            self.assertEqual(len(rows), 1, u.username)
            self.assertEqual((rows[0]["days_late"], rows[0]["remaining"]), (3, Decimal("900")))
        self.assertEqual(overdue_installments(self.other), [])

    def test_a_booking_paid_in_full_is_not_late(self):
        self._pay(paid="1000")
        self.assertEqual(overdue_installments(self.agent), [])

    def test_a_returned_payment_does_not_count_as_paid(self):
        self._pay(paid="1000", review_status="returned")
        self.assertEqual(len(overdue_installments(self.agent)), 1)

    def test_a_future_installment_is_not_late(self):
        self._pay(days_ago=-2)
        self.assertEqual(overdue_installments(self.agent), [])

    def test_most_late_first(self):
        self._pay(days_ago=2)
        card2 = UniBookingCard.objects.create(customer_name="Zed", mobile="2", nationality="EG", country="EG", created_by=self.agent)
        b2 = HotelBooking.objects.create(card=card2, sell=Decimal("500"), net=Decimal("400"))
        Payment.objects.create(booking_hotel=b2, method="cash", paid_amount=Decimal("50"), sell_price=Decimal("500"),
                               net_price=Decimal("400"), installment_date=self.today - timedelta(days=9))
        self.assertEqual([r["days_late"] for r in overdue_installments(self.agent)], [9, 2])

    def test_the_board_shows_the_section(self):
        self._pay()
        self.client.force_login(self.agent)
        r = self.client.get(reverse("installments_board"))
        self.assertEqual(len(r.context["overdue"]), 1)
        self.assertContains(r, "أقساط متأخرة")

    def test_the_daily_job_notifies_once(self):
        self._pay()
        first = send_installment_notifications()
        self.assertGreater(first, 0)
        self.assertTrue(Notification.objects.filter(to_user=self.agent, message__contains="متأخر").exists())
        self.assertEqual(send_installment_notifications(), 0)

    def test_old_history_does_not_flood_the_bell(self):
        self._pay(days_ago=90)
        send_installment_notifications()
        self.assertFalse(Notification.objects.filter(message__contains="متأخر").exists())
        self.assertEqual(len(overdue_installments(self.agent)), 1)       # still on the board
