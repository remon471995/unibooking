"""A move in the middle of the month must give the new team the agent's WHOLE month."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import HotelBooking, Team, TeamMembership, UniBookingCard
from core.services.teams import month_matrix, month_progress, month_team_map, team_totals

User = get_user_model()


def prev_month_first(back=1):
    d = timezone.localdate().replace(day=1)
    for _ in range(back):
        d = (d - timedelta(days=1)).replace(day=1)
    return d


class MidMonthMoveTests(TestCase):
    def setUp(self):
        self.l1 = User.objects.create_user("l1")
        self.l2 = User.objects.create_user("l2")
        self.s1 = User.objects.create_user("s1")
        self.s2 = User.objects.create_user("s2")
        self.a = User.objects.create_user("agent")
        self.t1 = Team.objects.create(name="T1", leader=self.l1, supervisor=self.s1)
        self.t2 = Team.objects.create(name="T2", leader=self.l2, supervisor=self.s2)

        self.m = prev_month_first(1)                 # a finished month, so the test does not depend on today
        self.older = prev_month_first(2)
        mid = self.m.replace(day=15)
        # in T1 until the 14th of last month, in T2 from the 15th
        TeamMembership.objects.create(team=self.t1, user=self.a, start_date=self.older.replace(day=1), end_date=mid - timedelta(days=1))
        TeamMembership.objects.create(team=self.t2, user=self.a, start_date=mid)

        self.card_old = UniBookingCard.objects.create(customer_name="C1", mobile="1", nationality="EG", country="EG",
                                                      created_by=self.a, team=self.t1)   # made while in T1
        self.card_new = UniBookingCard.objects.create(customer_name="C2", mobile="2", nationality="EG", country="EG",
                                                      created_by=self.a, team=self.t2)   # made after the move

    def _booking(self, card, day, sell, net):
        return HotelBooking.objects.create(card=card, booking_date=day, sell=Decimal(sell), net=Decimal(net))

    def test_whole_month_goes_to_the_new_team(self):
        self._booking(self.card_old, self.m.replace(day=5), "1000", "800")     # before the move
        self._booking(self.card_new, self.m.replace(day=20), "500", "400")     # after the move
        mx = month_matrix(self.m)
        self.assertNotIn((self.t1.id, self.a.id), mx)
        d = mx[(self.t2.id, self.a.id)]
        self.assertEqual(d["sell"] - d["net"], Decimal("300"))                   # 200 + 100, nothing left in T1
        self.assertEqual(d["count"], 2)

    def test_team_totals_and_progress_agree(self):
        self._booking(self.card_old, self.m.replace(day=5), "1000", "800")
        self._booking(self.card_new, self.m.replace(day=20), "500", "400")
        first = self.m
        last = self.m.replace(day=28)
        totals = team_totals(first, last)
        self.assertNotIn(self.t1.id, totals)
        self.assertEqual(totals[self.t2.id]["sell"] - totals[self.t2.id]["net"], Decimal("300"))
        self.assertEqual(totals[self.t2.id]["count"], 2)

    def test_previous_month_stays_with_the_old_team(self):
        """He was only in T1 during the month before the move, so that month is not rewritten."""
        self._booking(self.card_old, self.older.replace(day=10), "700", "500")
        mx = month_matrix(self.older)
        self.assertEqual(mx[(self.t1.id, self.a.id)]["sell"], Decimal("700"))
        self.assertNotIn((self.t2.id, self.a.id), mx)

    def test_range_over_two_months_splits_by_month(self):
        self._booking(self.card_old, self.older.replace(day=10), "700", "500")      # month before: T1
        self._booking(self.card_old, self.m.replace(day=5), "1000", "800")           # month of the move: T2
        totals = team_totals(self.older, self.m.replace(day=28))
        self.assertEqual(totals[self.t1.id]["sell"], Decimal("700"))
        self.assertEqual(totals[self.t2.id]["sell"], Decimal("1000"))

    def test_person_who_left_every_team_keeps_the_last_team_of_the_month(self):
        TeamMembership.objects.filter(team=self.t2, user=self.a).update(end_date=self.m.replace(day=25))
        self.assertEqual(month_team_map(self.m)[self.a.id], self.t2.id)

    def test_agent_without_membership_falls_back_to_the_card_team(self):
        b = User.objects.create_user("nomember")
        card = UniBookingCard.objects.create(customer_name="C3", mobile="3", nationality="EG", country="EG",
                                             created_by=b, team=self.t1)
        self._booking(card, self.m.replace(day=3), "100", "50")
        self.assertIn((self.t1.id, b.id), month_matrix(self.m))

    def test_leader_and_supervisor_read_the_team_whole_month(self):
        """The leader / supervisor numbers come from the team they lead / supervise."""
        self._booking(self.card_old, self.m.replace(day=5), "1000", "800")
        self._booking(self.card_new, self.m.replace(day=20), "500", "400")
        totals = team_totals(self.m, self.m.replace(day=28))
        mine = {t.leader_id: totals[t.id] for t in (self.t1, self.t2) if t.id in totals}
        self.assertEqual(set(mine), {self.l2.id})                                    # new leader has it all
        self.assertEqual(mine[self.l2.id]["sell"], Decimal("1500"))
        sup = {t.supervisor_id: totals[t.id] for t in (self.t1, self.t2) if t.id in totals}
        self.assertEqual(sup[self.s2.id]["sell"], Decimal("1500"))
