"""The report numbers must agree with each other and must not count a booking once per payment."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import FlightBooking, FlightPayment, UniBookingCard
from core.reconcile import reconcile

User = get_user_model()


def make_user(username, role="agent"):
    u = User.objects.create_user(username, password="x")
    u.profile.role = role
    u.profile.save()
    return User.objects.get(pk=u.pk)


class _Base(TestCase):
    def setUp(self):
        self.mgr = make_user("mgr", "sales_manager")
        self.agent = make_user("agent")
        self.today = timezone.localdate()
        self.n = 0

    def _booking(self, sell="100", net="80", employee="agent", pays=(), days_ago=0, **kw):
        self.n += 1
        card = UniBookingCard.objects.create(
            customer_name=f"C{self.n}", mobile="1", nationality="EG", country="EG", created_by=self.agent)
        b = FlightBooking.objects.create(
            card=card, airline="MS", pnr=f"P{self.n}", employee_name=employee, sell_price=Decimal(sell),
            net_price=Decimal(net), booking_date=self.today - timedelta(days=days_ago), **kw)
        for amount, status in pays:
            FlightPayment.objects.create(
                booking_flight=b, method="link", payment_link="http://x.com", paid_amount=Decimal(amount),
                sell_price=b.sell_price, net_price=b.net_price, employee_name=employee, review_status=status)
        return b


class ReportAccuracyTests(_Base):
    def test_a_booking_with_two_payments_is_counted_once_per_employee(self):
        self._booking(pays=[("40", "approved"), ("60", "approved")])
        self.client.force_login(self.mgr)
        r = self.client.get(reverse("reports"), {"group": "employee"})
        row = next(x for x in r.context["emp_rows"] if x["employee"] == "agent")
        self.assertEqual((row["sell"], row["net"], row["profit"], row["paid"], row["count"]),
                         (Decimal("100"), Decimal("80"), Decimal("20"), Decimal("100"), 1))
        self.assertEqual(r.context["totals"]["sell"], Decimal("100"))

    def test_the_employee_rows_add_up_to_the_totals(self):
        self._booking(pays=[("50", "approved"), ("50", "approved")])
        self._booking(sell="200", net="150", employee="other", pays=[("200", "approved")])
        self.client.force_login(self.mgr)
        r = self.client.get(reverse("reports"), {"group": "employee"})
        self.assertEqual(sum(x["sell"] for x in r.context["emp_rows"]), r.context["totals"]["sell"])
        self.assertEqual(sum(x["profit"] for x in r.context["emp_rows"]), r.context["totals"]["profit"])

    def test_the_performance_board_counts_money_for_the_same_bookings(self):
        # the first payment has the agreed last date, the second has none: a date filter must not drop it
        self._booking(pays=[("40", "approved"), ("60", "approved")])
        self.client.force_login(self.mgr)
        r = self.client.get(reverse("performance_dashboard"),
                            {"from": (self.today - timedelta(days=1)).isoformat(), "to": self.today.isoformat()})
        self.assertEqual(r.context["kpis"]["total_paid"], Decimal("100"))
        self.assertEqual(r.context["kpis"]["total_remaining"], Decimal("0"))


class ReconcileTests(_Base):
    def test_the_month_totals_count_each_booking_once(self):
        self._booking(pays=[("40", "approved"), ("60", "pending")])
        data = reconcile()
        m = data["months"][0]
        self.assertEqual((m["count"], m["sell"], m["paid"], m["waiting"]), (1, Decimal("100"), Decimal("40"), Decimal("60")))
        self.assertEqual(m["sell_from_payments"], Decimal("200"))        # what summing the payments would have said

    def _keys(self, data):
        return {g["key"]: g["count"] for g in data["issues"]}

    def test_it_finds_the_bookings_that_look_wrong(self):
        self._booking(sell="100", net="150")                                              # loss, no payment today
        self._booking(sell="100", net="80", pays=[("120", "approved")])                    # overpaid
        self._booking(sell="100", net="80", days_ago=3)                                    # stuck: no payment
        b = self._booking(sell="100", net="80", pays=[("100", "approved")])
        FlightPayment.objects.filter(booking_flight=b).update(net_price=Decimal("10"))     # stale snapshot
        c = self._booking(sell="100", net="80", pays=[("50", "approved"), ("50", "returned")], review_status="approved")
        keys = self._keys(reconcile())
        for k in ("loss", "overpaid", "no_payment", "snapshot", "returned_left"):
            self.assertIn(k, keys, k)

    def test_clean_data_has_no_issues(self):
        self._booking(pays=[("100", "approved")])
        self.assertEqual(reconcile()["issues"], [])

    def test_the_page_opens_for_those_who_see_everything_only(self):
        self._booking(pays=[("100", "approved")])
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.get(reverse("reconcile")).status_code, 200)
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(reverse("reconcile")).status_code, 403)
