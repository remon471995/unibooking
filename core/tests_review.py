"""Booking correction before approval, and the review queue rules."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import FlightBooking, FlightPayment, ReviewLog, UniBookingCard

User = get_user_model()


def make_user(username, role="agent"):
    u = User.objects.create_user(username, password="x")
    u.profile.role = role
    u.profile.save()
    return User.objects.get(pk=u.pk)


class CorrectionTests(TestCase):
    def setUp(self):
        self.agent = make_user("agent")
        self.de = make_user("de", "data_entry")
        self.card = UniBookingCard.objects.create(
            customer_name="Ali", mobile="1", nationality="EG", country="EG", created_by=self.agent)
        self.f = FlightBooking.objects.create(
            card=self.card, airline="MS", pnr="ABC123", sell_price=Decimal("1000"), net_price=Decimal("800"))
        self.edit_url = reverse("flight_edit", args=[self.f.pk])
        self.data = {"airline": "KU", "pnr": "xyz789", "booking_date": timezone.localdate().isoformat()}

    def _pay(self, amount="1000", **kw):
        return FlightPayment.objects.create(
            booking_flight=self.f, method="cash", paid_amount=Decimal(amount),
            sell_price=self.f.sell_price, net_price=self.f.net_price, **kw)

    def test_agent_corrects_a_pending_booking(self):
        self.client.force_login(self.agent)
        r = self.client.post(self.edit_url, self.data)
        self.assertEqual(r.status_code, 302)
        self.f.refresh_from_db()
        self.assertEqual((self.f.airline, self.f.pnr), ("KU", "XYZ789"))
        self.assertTrue(ReviewLog.objects.filter(action="edited").exists())

    def test_approved_booking_cannot_be_edited(self):
        FlightBooking.objects.filter(pk=self.f.pk).update(review_status="approved")
        self.client.force_login(self.agent)
        self.client.post(self.edit_url, self.data)
        self.f.refresh_from_db()
        self.assertEqual(self.f.airline, "MS")

    def test_data_entry_cannot_edit_what_he_reviews(self):
        self.client.force_login(self.de)
        self.client.post(self.edit_url, self.data)
        self.f.refresh_from_db()
        self.assertEqual(self.f.airline, "MS")

    def test_queue_shows_a_booking_only_after_its_first_payment(self):
        self.client.force_login(self.de)
        r = self.client.get(reverse("review_queue"))
        self.assertEqual(len(r.context["pending_b"]), 0)
        self._pay()
        r = self.client.get(reverse("review_queue"))
        self.assertEqual(len(r.context["pending_b"]), 1)

    def _approve(self):
        return self.client.post(reverse("review_action"), {
            "what": "b", "kind": "flight", "pk": self.f.pk, "action": "approve",
            "chk_sell": "1", "chk_net": "1", "chk_docs": "1", "chk_pay": "1", "chk_ref": "1"})

    def test_cannot_approve_a_booking_without_payments(self):
        self.client.force_login(self.de)
        self._approve()
        self.f.refresh_from_db()
        self.assertEqual(self.f.review_status, "pending")

    def test_cannot_approve_while_a_payment_is_still_returned(self):
        self._pay(review_status="returned")
        self.client.force_login(self.de)
        self._approve()
        self.f.refresh_from_db()
        self.assertEqual(self.f.review_status, "pending")

    def test_booking_fix_rejects_sell_below_net(self):
        self._pay("100", installment_date=timezone.localdate())
        self.client.force_login(self.agent)
        self.client.post(reverse("booking_fix", args=["flight", self.f.pk]), {"sell": "100", "net": "200"})
        self.f.refresh_from_db()
        self.assertEqual(self.f.sell_price, Decimal("1000"))

    def test_booking_fix_rejects_sell_below_what_is_paid(self):
        self._pay("600")
        self.client.force_login(self.agent)
        self.client.post(reverse("booking_fix", args=["flight", self.f.pk]), {"sell": "500", "net": "400"})
        self.f.refresh_from_db()
        self.assertEqual(self.f.sell_price, Decimal("1000"))

    def test_nobody_but_the_card_owner_side_can_add_a_payment(self):
        other = make_user("other")
        self.client.force_login(other)
        self.client.post(reverse("flight_payment", args=[self.f.pk]), {"paid_amount": "100", "method": "cash"})
        self.assertFalse(FlightPayment.objects.filter(booking_flight=self.f).exists())


class OnlyDataEntryApprovesTests(TestCase):
    def setUp(self):
        self.agent = make_user("agent")
        self.card = UniBookingCard.objects.create(
            customer_name="Ali", mobile="1", nationality="EG", country="EG", created_by=self.agent)
        self.f = FlightBooking.objects.create(
            card=self.card, airline="MS", pnr="ABC123", sell_price=Decimal("1000"), net_price=Decimal("800"))
        FlightPayment.objects.create(
            booking_flight=self.f, method="cash", paid_amount=Decimal("1000"),
            sell_price=Decimal("1000"), net_price=Decimal("800"))

    def _approve(self):
        return self.client.post(reverse("review_action"), {
            "what": "b", "kind": "flight", "pk": self.f.pk, "action": "approve",
            "chk_sell": "1", "chk_net": "1", "chk_docs": "1", "chk_pay": "1", "chk_ref": "1"})

    def test_nobody_else_can_approve_or_open_the_queue(self):
        others = [make_user("mgr", "sales_manager"), make_user("adm", "admin"), make_user("lead", "leader"),
                  make_user("sup", "supervisor"), self.agent,
                  User.objects.create_user("root", password="x", is_superuser=True, is_staff=True)]
        for u in others:
            self.client.force_login(u)
            self.assertEqual(self._approve().status_code, 403, u.username)
            self.assertEqual(self.client.get(reverse("review_queue")).status_code, 403, u.username)
            self.f.refresh_from_db()
            self.assertEqual(self.f.review_status, "pending", u.username)

    def test_data_entry_approves(self):
        self.client.force_login(make_user("de", "data_entry"))
        self.assertEqual(self.client.get(reverse("review_queue")).status_code, 200)
        self._approve()
        self.f.refresh_from_db()
        self.assertEqual(self.f.review_status, "approved")

    def test_review_menu_is_for_data_entry_only(self):
        from core.permissions import sees_review
        self.assertTrue(sees_review(make_user("de", "data_entry")))
        for role in ("sales_manager", "admin", "leader", "supervisor", "agent"):
            self.assertFalse(sees_review(make_user(role + "_u", role)), role)
