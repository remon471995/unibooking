from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.installments import due_installments, installment_recipients, scope_q
from core.models import Notification, Payment, Team, TeamMembership, UniBookingCard, HotelBooking

User = get_user_model()


def make_user(username, role="agent", department="", superuser=False):
    u = User.objects.create_user(username, password="x", is_superuser=superuser, is_staff=superuser)
    prof = u.profile            # created by the accounts signal
    prof.role, prof.department = role, department
    prof.save()
    return User.objects.get(pk=u.pk)   # drop the cached profile


class InstallmentVisibilityTests(TestCase):
    def setUp(self):
        self.agent = make_user("agent1")
        self.other_agent = make_user("agent2")            # same team
        self.leader = make_user("leader", "leader")
        self.supervisor = make_user("supervisor", "supervisor")
        self.stranger_agent = make_user("agent_x")          # other team
        self.stranger_leader = make_user("leader_x", "leader")
        self.data_entry = make_user("de", "data_entry")
        self.accounts = make_user("acc", "agent", department="accounts")
        self.manager = make_user("mgr", "sales_manager")
        self.admin_role = make_user("adm", "admin")
        self.root = make_user("root", superuser=True)
        self.inactive = make_user("gone", "data_entry")
        User.objects.filter(pk=self.inactive.pk).update(is_active=False)

        self.team = Team.objects.create(name="A", leader=self.leader, supervisor=self.supervisor)
        self.team_x = Team.objects.create(name="X", leader=self.stranger_leader)
        for u in (self.agent, self.other_agent):
            TeamMembership.objects.create(team=self.team, user=u)
        TeamMembership.objects.create(team=self.team_x, user=self.stranger_agent)

        self.card = UniBookingCard.objects.create(
            customer_name="Ali", mobile="1", nationality="EG", country="EG",
            created_by=self.agent, team=self.team,
        )
        self.booking = HotelBooking.objects.create(
            card=self.card, sell=Decimal("1000"), net=Decimal("800"),
        )
        self.due = timezone.localdate() + timedelta(days=2)

    def _installment(self, paid="100", due=None):
        return Payment.objects.create(
            booking_hotel=self.booking, method="cash", paid_amount=Decimal(paid),
            sell_price=Decimal("1000"), net_price=Decimal("800"), installment_date=due or self.due,
        )

    def test_who_sees_the_installment(self):
        self._installment()
        # leaders and supervisors see every team's installments, not only their own
        should_see = [self.agent, self.leader, self.supervisor, self.stranger_leader, self.data_entry,
                      self.accounts, self.manager, self.admin_role, self.root]
        should_not = [self.other_agent, self.stranger_agent]
        for u in should_see:
            self.assertEqual(len(due_installments(u, 5)), 1, f"{u.username} must see it")
        for u in should_not:
            self.assertEqual(due_installments(u, 5), [], f"{u.username} must NOT see it")

    def test_scope_q_filters_bookings_and_payments(self):
        p = self._installment()
        self.assertIsNone(scope_q(self.data_entry))
        self.assertTrue(HotelBooking.objects.filter(scope_q(self.leader)).exists())
        self.assertFalse(HotelBooking.objects.filter(scope_q(self.other_agent)).exists())
        self.assertTrue(Payment.objects.filter(scope_q(self.agent, "booking_hotel__"), pk=p.pk).exists())
        self.assertTrue(Payment.objects.filter(scope_q(self.stranger_leader, "booking_hotel__"), pk=p.pk).exists())
        self.assertFalse(Payment.objects.filter(scope_q(self.stranger_agent, "booking_hotel__"), pk=p.pk).exists())

    def test_notifications_go_to_the_same_people(self):
        self._installment()
        notified = set(Notification.objects.values_list("to_user__username", flat=True))
        expected = {"agent1", "leader", "leader_x", "supervisor", "de", "acc", "mgr", "adm", "root"}
        self.assertEqual(notified, expected)

    def test_recipients_and_visibility_agree(self):
        """The notification list and the board filter must describe the same people."""
        self._installment()
        recipients = {u.username for u in installment_recipients(self.card)}
        seeing = {u.username for u in User.objects.filter(is_active=True) if due_installments(u, 5)}
        self.assertEqual(recipients, seeing)

    def test_notifying_twice_does_not_duplicate(self):
        p = self._installment()
        before = Notification.objects.count()
        p.save()
        self.assertEqual(Notification.objects.count(), before)

    def test_fully_paid_booking_is_not_an_installment(self):
        self._installment(paid="1000")
        self.assertEqual(due_installments(self.agent, 5), [])
        self.assertEqual(Notification.objects.count(), 0)

    def test_installment_outside_the_window_is_not_listed(self):
        self._installment(due=timezone.localdate() + timedelta(days=30))
        self.assertEqual(due_installments(self.agent, 5), [])
