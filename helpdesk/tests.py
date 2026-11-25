from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Notification
from helpdesk.models import Department, DepartmentMembership, Ticket, TicketMessage
from helpdesk.unread import mark_ticket_read, unread_ticket_ids

User = get_user_model()


class NewMessageTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user("sales", password="x")
        self.ops = User.objects.create_user("ops", password="x")
        self.cs = User.objects.create_user("cs", password="x")
        self.dept = Department.objects.create(name="Operations", slug="operations")
        DepartmentMembership.objects.create(department=self.dept, user=self.ops)
        self.t = Ticket.objects.create(subject="X", department=self.dept, requester=self.sales, assigned_to=self.ops)
        TicketMessage.objects.create(ticket=self.t, sender=self.sales, body="hello")      # the opening message
        mark_ticket_read(self.ops, self.t)
        mark_ticket_read(self.sales, self.t)
        Notification.objects.all().delete()

    def _say(self, user, body="reply"):
        return TicketMessage.objects.create(ticket=self.t, sender=user, body=body)

    def test_a_reply_is_new_for_the_other_side_only(self):
        self._say(self.ops)
        self.assertEqual(unread_ticket_ids(self.sales), {self.t.pk})
        self.assertEqual(unread_ticket_ids(self.ops), set())
        self.assertTrue(Notification.objects.filter(to_user=self.sales, is_read=False).exists())

    def test_the_inbox_badge_and_the_new_marker(self):
        self._say(self.ops)
        self.client.force_login(self.sales)
        r = self.client.get(reverse("helpdesk:my_inbox"))
        self.assertEqual(r.context["hd_mine"], 1)
        self.assertIn(self.t.pk, r.context["new_ids"])
        self.assertContains(r, "جديد")

    def test_opening_the_request_clears_the_badge_and_the_bell(self):
        self._say(self.ops)
        self.client.force_login(self.sales)
        self.client.get(reverse("helpdesk:ticket_detail", args=[self.t.pk]))
        self.assertEqual(unread_ticket_ids(self.sales), set())
        self.assertFalse(Notification.objects.filter(to_user=self.sales, is_read=False).exists())

    def test_somebody_from_another_department_who_wrote_is_told_too(self):
        self._say(self.cs, "from CS")                  # CS is neither the requester nor the owner
        Notification.objects.all().delete()
        self._say(self.sales, "customer answered")
        self.assertTrue(Notification.objects.filter(to_user=self.cs).exists())
        self.assertIn(self.t.pk, unread_ticket_ids(self.cs))

    def test_your_own_message_is_never_new_for_you(self):
        self._say(self.sales)
        self.assertEqual(unread_ticket_ids(self.sales), set())
        self.assertFalse(Notification.objects.filter(to_user=self.sales).exists())


class ClosedTicketsAreHiddenTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user("sales", password="x")
        self.ops = User.objects.create_user("ops", password="x")
        self.dept = Department.objects.create(name="Operations", slug="operations")
        DepartmentMembership.objects.create(department=self.dept, user=self.ops)
        self.open = Ticket.objects.create(subject="open one", department=self.dept, requester=self.sales,
                                          assigned_to=self.ops, status="in_progress")
        self.done = Ticket.objects.create(subject="done one", department=self.dept, requester=self.sales,
                                          assigned_to=self.ops, status="resolved")
        self.cancelled = Ticket.objects.create(subject="cancelled one", department=self.dept, requester=self.sales,
                                               assigned_to=self.ops, status="cancelled")

    def _ids(self, url_name, user, *args, **params):
        self.client.force_login(user)
        r = self.client.get(reverse(url_name, args=args), params)
        return {t.pk for t in r.context["tickets"]}

    def test_my_inbox(self):
        self.assertEqual(self._ids("helpdesk:my_inbox", self.sales), {self.open.pk})
        self.assertEqual(self._ids("helpdesk:my_inbox", self.sales, status="resolved"), {self.done.pk})
        self.assertEqual(self._ids("helpdesk:my_inbox", self.sales, status="closed"), {self.cancelled.pk})

    def test_department_inbox(self):
        self.assertEqual(self._ids("helpdesk:department_inbox", self.ops, "operations"), {self.open.pk})
        self.assertEqual(self._ids("helpdesk:department_inbox", self.ops, "operations", status="resolved"), {self.done.pk})

    def test_dashboard(self):
        self.assertEqual(self._ids("helpdesk:dashboard", self.sales), {self.open.pk})
        self.assertEqual(self._ids("helpdesk:dashboard", self.sales, status="resolved"), {self.done.pk})

    def test_a_closed_request_never_counts_as_new(self):
        TicketMessage.objects.create(ticket=self.done, sender=self.ops, body="late reply")
        self.assertNotIn(self.done.pk, unread_ticket_ids(self.sales))
