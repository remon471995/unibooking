"""Booking correction before approval, and the review queue rules."""
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
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

    def _fix(self, pay, **over):
        data = {"sell": "1000", "net": "800", f"p{pay.pk}-paid_amount": "1000", f"p{pay.pk}-method": "cash"}
        data.update(over)
        self.client.force_login(self.agent)
        return self.client.post(reverse("booking_fix", args=["flight", self.f.pk]), data)

    def test_fix_rejects_sell_below_net(self):
        pay = self._pay("100", installment_date=timezone.localdate())
        self._fix(pay, sell="100", net="200", **{f"p{pay.pk}-paid_amount": "100"})
        self.f.refresh_from_db()
        self.assertEqual(self.f.sell_price, Decimal("1000"))

    def test_fix_rejects_sell_below_what_is_paid(self):
        pay = self._pay("600")
        self._fix(pay, sell="500", net="400", **{f"p{pay.pk}-paid_amount": "600"})
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


class PendingFixScreenTests(TestCase):
    """Before the review the agent corrects numbers and payment on one prefilled screen."""

    def setUp(self):
        self.agent = make_user("agent")
        self.card = UniBookingCard.objects.create(
            customer_name="Ali", mobile="1", nationality="EG", country="EG", created_by=self.agent)
        self.f = FlightBooking.objects.create(
            card=self.card, airline="MS", pnr="ABC123", sell_price=Decimal("1000"), net_price=Decimal("800"))
        self.pay = FlightPayment.objects.create(
            booking_flight=self.f, method="cash", paid_amount=Decimal("1000"),
            sell_price=Decimal("1000"), net_price=Decimal("800"))
        self.url = reverse("booking_fix", args=["flight", self.f.pk])

    def test_one_save_fixes_numbers_and_payment(self):
        self.client.force_login(self.agent)
        data = {"sell": "1000", "net": "700", f"p{self.pay.pk}-paid_amount": "1000",
                f"p{self.pay.pk}-method": "cash", f"p{self.pay.pk}-note": "تصحيح"}
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.f.refresh_from_db()
        self.pay.refresh_from_db()
        self.assertEqual((self.f.net_price, self.pay.net_price, self.pay.note), (Decimal("700"), Decimal("700"), "تصحيح"))
        self.assertEqual((self.f.review_status, self.pay.review_status), ("pending", "pending"))

    def test_booking_without_a_payment_goes_to_the_payment_page(self):
        FlightPayment.objects.filter(pk=self.pay.pk).delete()
        self.client.force_login(self.agent)
        r = self.client.get(self.url)
        self.assertEqual(r.url, reverse("flight_payment", args=[self.f.pk]))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ReturnedBookingRedoTests(TestCase):
    """The data entry returns the booking: the agent gets the payment page EMPTY and enters everything again."""

    def setUp(self):
        self.agent = make_user("agent")
        self.de = make_user("de", "data_entry")
        self.card = UniBookingCard.objects.create(
            customer_name="Ali", mobile="1", nationality="EG", country="EG", created_by=self.agent)
        self.f = FlightBooking.objects.create(
            card=self.card, airline="MS", pnr="ABC123", sell_price=Decimal("1000"), net_price=Decimal("800"))
        self.old = FlightPayment.objects.create(
            booking_flight=self.f, method="cash", paid_amount=Decimal("1000"),
            sell_price=Decimal("1000"), net_price=Decimal("800"))
        self.client.force_login(self.de)
        self.client.post(reverse("review_action"), {
            "what": "b", "kind": "flight", "pk": self.f.pk, "action": "return",
            "reason": ["invoice"], "note": "الفاتورة غلط"})
        self.f.refresh_from_db()
        self.url = reverse("flight_payment", args=[self.f.pk])

    def _pdf(self, name):
        return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")

    def test_the_booking_was_returned(self):
        self.assertEqual(self.f.review_status, "returned")

    def test_payment_page_comes_back_empty_like_the_first_time(self):
        self.client.force_login(self.agent)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context["has_existing"])                 # sell / net are asked again
        self.assertEqual(list(r.context["payments"]), [])           # the old payment is not shown
        self.assertEqual(r.context["total_sell"], Decimal("0.00"))
        self.assertIn("الفاتورة غلط", " ".join(str(m) for m in r.context["messages"]))

    def test_saving_replaces_the_old_payment_and_resubmits(self):
        self.client.force_login(self.agent)
        r = self.client.post(self.url, {
            "paid_amount": "900", "method": "link", "payment_link": "http://pay.example.com/x",
            "sell_price": "900", "net_price": "700",
            "invoice_file": self._pdf("inv.pdf"), "voucher_original": self._pdf("v.pdf"),
        })
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        self.f.refresh_from_db()
        self.assertFalse(FlightPayment.objects.filter(pk=self.old.pk).exists())
        pays = list(FlightPayment.objects.filter(booking_flight=self.f))
        self.assertEqual(len(pays), 1)
        self.assertEqual((pays[0].paid_amount, pays[0].review_status), (Decimal("900"), "pending"))
        self.assertEqual((self.f.sell_price, self.f.net_price, self.f.review_status),
                         (Decimal("900"), Decimal("700"), "pending"))
        self.assertTrue(ReviewLog.objects.filter(action="fixed", note__contains="من جديد").exists())

    def test_a_failed_save_keeps_the_old_payment(self):
        self.client.force_login(self.agent)
        self.client.post(self.url, {"paid_amount": "900", "method": "link", "sell_price": "900", "net_price": "700"})
        self.assertTrue(FlightPayment.objects.filter(pk=self.old.pk).exists())     # no invoice / voucher / link
        self.f.refresh_from_db()
        self.assertEqual(self.f.review_status, "returned")

    def test_sell_below_net_is_still_refused(self):
        self.client.force_login(self.agent)
        r = self.client.post(self.url, {
            "paid_amount": "100", "method": "link", "payment_link": "http://pay.example.com/x",
            "sell_price": "100", "net_price": "200", "installment_date": timezone.localdate().isoformat(),
            "invoice_file": self._pdf("inv.pdf"), "voucher_original": self._pdf("v.pdf"),
        })
        self.assertTrue(FlightPayment.objects.filter(pk=self.old.pk).exists())

    def test_fix_screen_sends_a_returned_booking_to_the_payment_page(self):
        self.client.force_login(self.agent)
        r = self.client.get(reverse("booking_fix", args=["flight", self.f.pk]))
        self.assertEqual(r.url, self.url)


class ReturnedLaterPaymentTests(TestCase):
    """Booking approved, first payment approved, the SECOND payment returned: the agent must be able to redo it."""

    def setUp(self):
        self.agent = make_user("agent")
        self.card = UniBookingCard.objects.create(
            customer_name="Ali", mobile="1", nationality="EG", country="EG", created_by=self.agent)
        self.f = FlightBooking.objects.create(
            card=self.card, airline="MS", pnr="ABC123", sell_price=Decimal("20"), net_price=Decimal("10"),
            review_status="approved")
        self.p1 = FlightPayment.objects.create(
            booking_flight=self.f, method="link", payment_link="http://x.com/1", paid_amount=Decimal("10"),
            sell_price=Decimal("20"), net_price=Decimal("10"), review_status="approved")
        self.p2 = FlightPayment.objects.create(
            booking_flight=self.f, method="cash", paid_amount=Decimal("10"),
            sell_price=Decimal("20"), net_price=Decimal("10"), review_status="returned",
            review_note="[الفاتورة] غلط")
        self.url = reverse("flight_payment", args=[self.f.pk])
        self.client.force_login(self.agent)

    def test_page_shows_the_form_again_instead_of_fully_paid(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["remaining"], Decimal("10"))        # the returned payment does not count
        self.assertEqual([p.pk for p in r.context["payments"]], [self.p1.pk])
        self.assertTrue(r.context["has_existing"])                      # sell / net stay locked
        self.assertIn("الفاتورة", " ".join(str(m) for m in r.context["messages"]))

    def test_redo_replaces_only_the_returned_payment_and_keeps_the_booking_approved(self):
        r = self.client.post(self.url, {"paid_amount": "10", "method": "link", "payment_link": "http://x.com/2"})
        self.assertEqual(r.status_code, 302)
        self.f.refresh_from_db()
        self.assertFalse(FlightPayment.objects.filter(pk=self.p2.pk).exists())
        self.assertTrue(FlightPayment.objects.filter(pk=self.p1.pk, review_status="approved").exists())
        new = FlightPayment.objects.exclude(pk__in=[self.p1.pk]).get(booking_flight=self.f)
        self.assertEqual((new.paid_amount, new.review_status), (Decimal("10"), "pending"))
        self.assertEqual(self.f.review_status, "approved")

    def test_review_box_links_to_the_payment_page(self):
        r = self.client.get(reverse("card_detail", args=[self.card.pk]))
        self.assertContains(r, self.url)


class PaidCountsOnlyAfterApprovalTests(TestCase):
    """A payment counts as paid only after the data entry approved it; returned / waiting ones do not."""

    def setUp(self):
        self.agent = make_user("agent")
        self.de = make_user("de", "data_entry")
        self.card = UniBookingCard.objects.create(
            customer_name="Ali", mobile="1", nationality="EG", country="EG", created_by=self.agent)
        self.f = FlightBooking.objects.create(
            card=self.card, airline="MS", pnr="ABC123", sell_price=Decimal("20"), net_price=Decimal("10"))

        def pay(amount, status):
            return FlightPayment.objects.create(
                booking_flight=self.f, method="link", payment_link="http://x.com", paid_amount=Decimal(amount),
                sell_price=Decimal("20"), net_price=Decimal("10"), review_status=status)
        self.ok, self.wait, self.ret = pay("5", "approved"), pay("4", "pending"), pay("3", "returned")

    def test_booking_counts_only_approved_money(self):
        self.assertEqual(self.f.total_paid, Decimal("5"))
        self.assertEqual(self.f.remaining_balance, Decimal("15"))
        self.assertEqual(self.f.paid_committed, Decimal("9"))        # approved + waiting; the returned one is out

    def test_card_totals_count_only_approved_money(self):
        self.assertEqual(self.card.total_paid, Decimal("5"))
        self.client.force_login(self.agent)
        r = self.client.get(reverse("card_detail", args=[self.card.pk]))
        self.assertEqual(r.context["totals"]["total_paid"], Decimal("5"))
        self.assertEqual(r.context["totals"]["total_remaining"], Decimal("15"))

    def test_money_waiting_for_approval_cannot_be_entered_twice(self):
        self.client.force_login(self.agent)
        before = FlightPayment.objects.count()
        # 20 sell - 5 approved - 4 waiting = 11 left to enter, so 12 is refused
        self.client.post(reverse("flight_payment", args=[self.f.pk]),
                         {"paid_amount": "12", "method": "link", "payment_link": "http://x.com/2"})
        self.assertEqual(FlightPayment.objects.count(), before)

    def test_approving_makes_the_waiting_payment_count(self):
        FlightPayment.objects.filter(pk=self.ret.pk).delete()
        self.client.force_login(self.de)
        self.client.post(reverse("review_action"), {
            "what": "b", "kind": "flight", "pk": self.f.pk, "action": "approve",
            "chk_sell": "1", "chk_net": "1", "chk_pay": "1", "chk_docs": "1", "chk_ref": "1"})
        self.assertEqual(self.f.total_paid, Decimal("9"))
