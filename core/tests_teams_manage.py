"""Teams are for the sales side only."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Team, TeamMembership

User = get_user_model()


def make_user(username, role="agent", department=""):
    u = User.objects.create_user(username, password="x")
    u.profile.role, u.profile.department = role, department
    u.profile.save()
    return User.objects.get(pk=u.pk)


class TeamsAreForSalesTests(TestCase):
    def setUp(self):
        self.mgr = make_user("mgr", "sales_manager")
        self.sales = make_user("sales_agent", department="sales")
        self.blank = make_user("blank_dept_agent")                      # no department = sales
        self.others = {d: make_user(f"{d}_agent", department=d) for d in ("ops", "accounts", "cs", "fft", "quotation", "hr", "it")}
        self.team = Team.objects.create(name="T")
        self.client.force_login(self.mgr)

    def test_only_sales_agents_are_offered_without_a_team(self):
        r = self.client.get(reverse("teams_manage"))
        names = {u.username for u in r.context["unassigned"]}
        self.assertEqual(names, {"sales_agent", "blank_dept_agent"})

    def test_a_person_from_another_department_cannot_be_added_to_a_team(self):
        for dept, u in self.others.items():
            self.client.post(reverse("teams_manage"),
                             {"action": "move_member", "user_id": u.id, "team_id": self.team.id})
            self.assertFalse(TeamMembership.objects.filter(user=u).exists(), dept)

    def test_a_sales_agent_can_be_added(self):
        self.client.post(reverse("teams_manage"),
                         {"action": "move_member", "user_id": self.sales.id, "team_id": self.team.id})
        self.assertTrue(TeamMembership.objects.filter(user=self.sales, team=self.team).exists())

    def test_leaders_and_supervisors_of_other_departments_are_not_offered(self):
        make_user("ops_leader", "leader", "ops")
        good = make_user("sales_leader", "leader", "sales")
        make_user("acc_super", "supervisor", "accounts")
        r = self.client.get(reverse("teams_manage"))
        row = next(x for x in r.context["rows"] if x["team"].pk == self.team.pk)
        self.assertEqual({u.username for u in row["leader_options"]}, {good.username})
        self.assertEqual(row["supervisor_options"], [])
