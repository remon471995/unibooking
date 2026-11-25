"""Everybody above the agent sees every booking in the employee summary and the reports; an agent sees only his own."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import FlightBooking, Team, UniBookingCard

User = get_user_model()


def make_user(username, role="agent", department="", superuser=False):
    u = User.objects.create_user(username, password="x", is_superuser=superuser, is_staff=superuser)
    u.profile.role, u.profile.department = role, department
    u.profile.save()
    return User.objects.get(pk=u.pk)


class SeeAllBookingsTests(TestCase):
    def setUp(self):
        self.a1 = make_user("agent1")
        self.a2 = make_user("agent2")
        for u, sell in ((self.a1, "100"), (self.a2, "300")):
            card = UniBookingCard.objects.create(
                customer_name=u.username, mobile="1", nationality="EG", country="EG", created_by=u)
            FlightBooking.objects.create(
                card=card, airline="MS", pnr=u.username.upper(), employee_name=u.username,
                sell_price=Decimal(sell), net_price=Decimal("50"))

    def _total_sell(self, user):
        self.client.force_login(user)
        r = self.client.get(reverse("agent_board"))
        self.assertEqual(r.status_code, 200)
        return r.context["kpis"]["total_sell"]

    def test_an_agent_sees_only_his_own(self):
        self.assertEqual(self._total_sell(self.a1), Decimal("100"))
        self.assertEqual(self._total_sell(self.a2), Decimal("300"))

    def test_everybody_above_the_agent_sees_everything(self):
        above = [make_user("lead", "leader"), make_user("sup", "supervisor"), make_user("mgr", "sales_manager"),
                 make_user("adm", "admin"), make_user("de", "data_entry"),
                 make_user("acc", "agent", department="accounts"),
                 User.objects.create_user("root", password="x", is_superuser=True, is_staff=True)]
        for u in above:
            self.assertEqual(self._total_sell(u), Decimal("400"), u.username)

    def test_a_leader_set_on_a_team_sees_everything_even_with_an_agent_role(self):
        boss = make_user("boss")                                   # profile role is still "agent"
        Team.objects.create(name="T", leader=boss)
        self.assertEqual(self._total_sell(boss), Decimal("400"))

    def test_the_summary_says_who_sold_each_booking(self):
        self.client.force_login(make_user("lead", "leader"))
        r = self.client.get(reverse("agent_board"))
        self.assertContains(r, "agent1")
        self.assertContains(r, "agent2")
