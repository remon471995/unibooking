"""Every signed-in employee sees every request; only the people involved can answer it."""
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from core.models import Team, TeamMembership, UniBookingCard
from helpdesk.models import Department, DepartmentMembership, Ticket, TicketMessage

User = get_user_model()


def make_user(username, role="agent"):
    u = User.objects.create_user(username, password="x")
    u.profile.role = role
    u.profile.save()
    return User.objects.get(pk=u.pk)


class EverybodySeesEveryRequestTests(TestCase):
    def setUp(self):
        self.leader = make_user("leader", "leader")
        self.agent = make_user("agent")                    # in the leader's team
        self.stranger = make_user("stranger")              # in nobody's team
        self.ops = make_user("ops")
        self.mgr = make_user("mgr", "sales_manager")
        self.team = Team.objects.create(name="T", leader=self.leader)
        TeamMembership.objects.create(team=self.team, user=self.agent)
        self.dept = Department.objects.create(name="Operations", slug="operations")
        DepartmentMembership.objects.create(department=self.dept, user=self.ops)

        self.card = UniBookingCard.objects.create(
            customer_name="Sham", mobile="66662733", nationality="KW", country="KW", created_by=self.agent)
        ct = ContentType.objects.get_for_model(UniBookingCard)
        mk = lambda subject, who, **kw: Ticket.objects.create(subject=subject, department=self.dept, requester=who, **kw)
        self.own = mk("mine", self.leader)
        self.team_t = mk("of my agent", self.agent, related_ref="H20261125GEHAD0577",
                         related_content_type=ct, related_object_id=self.card.pk)
        self.other = mk("somebody else", self.stranger)
        self.everything = {self.own.pk, self.team_t.pk, self.other.pk}
        self.people = [self.leader, self.agent, self.stranger, self.ops, self.mgr]

    def _ids(self, name, user, **params):
        self.client.force_login(user)
        r = self.client.get(reverse(name), params)
        return {t.pk for t in r.context["tickets"]}

    def test_the_dashboard_shows_every_request_to_everybody(self):
        for u in self.people:
            self.assertEqual(self._ids("helpdesk:dashboard", u), self.everything, u.username)

    def test_search_shows_every_request_to_everybody(self):
        for u in self.people:
            self.assertEqual(self._ids("helpdesk:search", u), self.everything, u.username)

    def test_search_finds_a_request_by_number_ref_or_mobile(self):
        for word in (str(self.team_t.pk), "GEHAD0577", "66662733", "Sham"):
            for u in (self.leader, self.stranger):
                self.assertIn(self.team_t.pk, self._ids("helpdesk:search", u, q=word), word)

    def test_anybody_can_open_any_request(self):
        for u in self.people:
            self.client.force_login(u)
            r = self.client.get(reverse("helpdesk:ticket_detail", args=[self.other.pk]))
            self.assertEqual(r.status_code, 200, u.username)

    def test_only_the_people_involved_can_answer(self):
        url = reverse("helpdesk:ticket_detail", args=[self.other.pk])
        before = TicketMessage.objects.filter(ticket=self.other).count()
        self.client.force_login(self.leader)                    # not involved in this one
        self.client.post(url, {"body": "hello"})
        self.assertEqual(TicketMessage.objects.filter(ticket=self.other).count(), before)
        for u in (self.stranger, self.ops):                      # the requester and the department's staff
            self.client.force_login(u)
            self.client.post(url, {"body": f"hello from {u.username}"})
        self.assertEqual(TicketMessage.objects.filter(ticket=self.other).count(), before + 2)

    def test_an_onlooker_gets_no_reply_box(self):
        self.client.force_login(self.leader)
        r = self.client.get(reverse("helpdesk:ticket_detail", args=[self.other.pk]))
        self.assertFalse(r.context["can_reply"])
        self.assertContains(r, "للمشاهدة فقط")
