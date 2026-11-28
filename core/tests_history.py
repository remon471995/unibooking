from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.history import booking_history
from core.models import FlightBooking, FlightPayment, UniBookingCard

User = get_user_model()


def make_user(username, role="agent"):
    u = User.objects.create_user(username, password="x")
    u.profile.role = role
    u.profile.save()
    return User.objects.get(pk=u.pk)


class BookingHistoryTests(TestCase):
    def setUp(self):
        self.agent = make_user("agent")
        self.de = make_user("de", "data_entry")
        card = UniBookingCard.objects.create(
            customer_name="Ali", mobile="1", nationality="EG", country="EG", created_by=self.agent)
        self.f = FlightBooking.objects.create(
            card=card, airline="MS", pnr="ABC123", employee_name="agent",
            sell_price=Decimal("100"), net_price=Decimal("80"))
        self.p = FlightPayment.objects.create(
            booking_flight=self.f, method="link", payment_link="http://x.com", paid_amount=Decimal("100"),
            sell_price=Decimal("100"), net_price=Decimal("80"), employee_name="agent")

    def _review(self, action, **extra):
        self.client.force_login(self.de)
        self.client.post(reverse("review_action"), {"what": "b", "kind": "flight", "pk": self.f.pk, "action": action, **extra})

    def test_the_story_is_told_in_order(self):
        self._review("return", reason=["invoice"], note="الفاتورة غلط")
        titles = [e["title"] for e in booking_history("flight", self.f)]
        self.assertEqual(titles[0], "تم إنشاء حجز طيران")
        self.assertTrue(any(t.startswith("دفعة 100") for t in titles))
        self.assertIn("رجّع الداتا انتري للتصحيح", titles)
        ats = [e["at"] for e in booking_history("flight", self.f)]
        self.assertEqual(ats, sorted(ats))

    def test_the_return_reason_is_in_the_story(self):
        self._review("return", reason=["invoice"], note="الفاتورة غلط")
        details = " ".join(e["detail"] for e in booking_history("flight", self.f))
        self.assertIn("الفاتورة غلط", details)

    def test_approval_shows_who_did_it(self):
        self._review("approve", chk_sell="1", chk_net="1", chk_pay="1", chk_docs="1", chk_ref="1")
        approved = [e for e in booking_history("flight", self.f) if e["title"] == "اعتمد الداتا انتري"]
        self.assertTrue(approved)
        self.assertEqual(approved[0]["who"], "de")

    def test_field_changes_from_the_audit_log_are_included(self):
        from audit.models import AuditLog
        AuditLog.objects.create(action="update", model="FlightBooking", model_label="حجز طيران",
                                object_id=str(self.f.pk), user_repr="agent", card_id=self.f.card_id,
                                changes={"airline": {"label": "الشركة", "old": "MS", "new": "KU"}})
        changed = [e for e in booking_history("flight", self.f) if e["changes"]]
        self.assertEqual(len(changed), 1)
        self.assertIn("MS", changed[0]["changes"][0])
        self.assertIn("KU", changed[0]["changes"][0])

    def test_everybody_signed_in_can_open_the_page(self):
        for u in (self.agent, self.de):
            self.client.force_login(u)
            r = self.client.get(reverse("booking_history", args=["flight", self.f.pk]))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "سجل حجز")

    def test_an_unknown_kind_is_a_404(self):
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(reverse("booking_history", args=["car", 1])).status_code, 404)
