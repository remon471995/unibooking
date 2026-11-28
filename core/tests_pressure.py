"""The data entry under pressure: waiting time, order, menu badge and notifications."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import FlightBooking, FlightPayment, Notification, UniBookingCard
from core.views_review import pending_review_count

User = get_user_model()


def make_user(username, role="agent"):
    u = User.objects.create_user(username, password="x")
    u.profile.role = role
    u.profile.save()
    return User.objects.get(pk=u.pk)


class ReviewPressureTests(TestCase):
    def setUp(self):
        self.agent = make_user("agent")
        self.de = make_user("de", "data_entry")
        self.de2 = make_user("de2", "data_entry")
        self.mgr = make_user("mgr", "sales_manager")
        self.count = 0

    def _booking(self, name="C"):
        self.count += 1
        card = UniBookingCard.objects.create(
            customer_name=f"{name}{self.count}", mobile="1", nationality="EG", country="EG", created_by=self.agent)
        return FlightBooking.objects.create(
            card=card, airline="MS", pnr=f"PNR{self.count}", sell_price=Decimal("100"), net_price=Decimal("80"))

    def _pay(self, booking, hours_ago=0, **kw):
        p = FlightPayment.objects.create(
            booking_flight=booking, method="link", payment_link="http://x.com", paid_amount=Decimal("100"),
            sell_price=Decimal("100"), net_price=Decimal("80"), **kw)
        if hours_ago:
            FlightPayment.objects.filter(pk=p.pk).update(created_at=timezone.now() - timedelta(hours=hours_ago))
        return p

    def test_the_longest_waiting_comes_first_and_is_marked(self):
        new, old, mid = self._booking("new"), self._booking("old"), self._booking("mid")
        self._pay(new, 0)
        self._pay(old, 30)
        self._pay(mid, 6)
        self.client.force_login(self.de)
        r = self.client.get(reverse("review_queue"))
        self.assertEqual([i["customer"] for i in r.context["pending_b"]], ["old2", "mid3", "new1"])
        self.assertEqual([i["urgency"] for i in r.context["pending_b"]], ["late", "slow", "ok"])
        self.assertEqual(r.context["summary"]["total"], 3)
        self.assertEqual((r.context["summary"]["late"], r.context["summary"]["slow"]), (1, 1))
        self.assertContains(r, "بانتظار")

    def test_the_menu_number_matches_the_queue(self):
        for _ in range(3):
            self._pay(self._booking())
        self.assertEqual(pending_review_count(), 3)
        self.client.force_login(self.de)
        r = self.client.get(reverse("review_queue"))
        self.assertEqual(r.context["rv_pending"], 3)
        self.assertEqual(r.context["summary"]["total"], 3)

    def test_the_menu_number_is_only_for_the_data_entry(self):
        self._pay(self._booking())
        for u in (self.agent, self.mgr):
            self.client.force_login(u)
            r = self.client.get(reverse("dashboard"))
            self.assertEqual(r.context["rv_pending"], 0, u.username)

    def test_a_booking_without_a_payment_is_not_counted(self):
        self._booking()
        self.assertEqual(pending_review_count(), 0)

    def test_the_data_entry_is_told_when_a_new_booking_arrives(self):
        self._pay(self._booking("Zed"))
        for u in (self.de, self.de2):
            self.assertTrue(Notification.objects.filter(to_user=u, message__contains="حجز جديد").exists(), u.username)
        self.assertFalse(Notification.objects.filter(to_user=self.agent, message__contains="حجز جديد").exists())
        self.assertFalse(Notification.objects.filter(to_user=self.mgr, message__contains="حجز جديد").exists())

    def test_a_second_payment_on_the_same_pending_booking_is_not_a_new_booking(self):
        b = self._booking()
        self._pay(b)
        Notification.objects.all().delete()
        self._pay(b)
        self.assertFalse(Notification.objects.filter(message__contains="حجز جديد").exists())

    def test_a_new_payment_on_an_approved_booking_is_announced(self):
        b = self._booking()
        FlightBooking.objects.filter(pk=b.pk).update(review_status="approved")
        self._pay(b)
        self.assertTrue(Notification.objects.filter(to_user=self.de, message__contains="دفعة جديدة").exists())
