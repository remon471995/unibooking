from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import FlightBooking, Team, UniBookingCard

User = get_user_model()


def make_user(username, role="agent", department=""):
    u = User.objects.create_user(username, password="x")
    u.profile.role, u.profile.department = role, department
    u.profile.save()
    return User.objects.get(pk=u.pk)


class PerformanceVisibilityTests(TestCase):
    def setUp(self):
        self.a1, self.a2 = make_user("agent1"), make_user("agent2")
        for u, sell in ((self.a1, "100"), (self.a2, "300")):
            card = UniBookingCard.objects.create(
                customer_name=u.username, mobile="1", nationality="EG", country="EG", created_by=u)
            FlightBooking.objects.create(card=card, airline="MS", pnr=u.username.upper(), employee_name=u.username,
                                         sell_price=Decimal(sell), net_price=Decimal("50"))
        self.url = reverse("performance_dashboard")

    def _get(self, user):
        self.client.force_login(user)
        return self.client.get(self.url)

    def test_an_agent_sees_only_his_own_numbers(self):
        r = self._get(self.a1)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["kpis"]["total_sell"], Decimal("100"))
        self.assertEqual([x["employee"] for x in r.context["rows"]], ["agent1"])

    def test_the_sales_side_above_the_agent_sees_everything(self):
        boss = make_user("boss")
        Team.objects.create(name="T", leader=boss)                      # leader by team, role still "agent"
        for u in (make_user("lead", "leader"), make_user("sup", "supervisor"), make_user("mgr", "sales_manager"),
                  make_user("adm", "admin"), boss,
                  User.objects.create_user("root", password="x", is_superuser=True, is_staff=True)):
            r = self._get(u)
            self.assertEqual(r.context["kpis"]["total_sell"], Decimal("400"), u.username)

    def test_people_outside_sales_are_refused(self):
        for u in (make_user("de", "data_entry"), make_user("ops", department="ops"),
                  make_user("acc", department="accounts")):
            self.assertEqual(self._get(u).status_code, 403, u.username)

    def test_the_menu_link_follows_the_same_rule(self):
        from core.permissions import sees_performance
        self.assertTrue(sees_performance(self.a1))
        self.assertFalse(sees_performance(make_user("de2", "data_entry")))

    def test_only_those_who_see_everything_can_export(self):
        self.client.force_login(self.a1)
        self.assertEqual(self.client.get(reverse("performance_export_xlsx")).status_code, 403)
