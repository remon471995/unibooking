"""Team numbers for the dashboards. Profit = sell - net, by booking date (same basis as the performance page).

Which team (and so which leader / supervisor) gets a sale
---------------------------------------------------------
Sales are credited by MONTH, not by the day of the booking.  Everything an agent sold in a month counts for
the team he is in at the END of that month (today, for the current month).  So when an agent is moved to
another team in the middle of the month, the new team - and its leader and supervisor - gets his whole
month from day 1, and the old team keeps none of it.  A person who is in no team at the end of the month
counts for the last team he had during that month.  A leader / supervisor reads his numbers through the team
he leads / supervises, so he gets the team's whole month in the same way.
"""
import calendar
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from core.models import FlightBooking, HotelBooking, OtherBooking, TargetCycle, TeamMembership, TeamTarget

D0 = Decimal("0.00")
_SUM = lambda f: Coalesce(Sum(f), D0, output_field=DecimalField(max_digits=14, decimal_places=2))
_SOURCES = ((HotelBooking, "sell", "net"), (FlightBooking, "sell_price", "net_price"), (OtherBooking, "sell_price", "net_price"))


def month_bounds(day):
    last = calendar.monthrange(day.year, day.month)[1]
    return day.replace(day=1), day.replace(day=last)


def current_cycle(day, create=False):
    first, last = month_bounds(day)
    if create:
        cycle, _ = TargetCycle.objects.get_or_create(
            year=day.year, month=day.month, defaults={"start_date": first, "end_date": last}
        )
        return cycle
    return TargetCycle.objects.filter(year=day.year, month=day.month).first()


def month_team_map(day, today=None):
    """{user_id: team_id} = the team each person counts for in the month of `day`.

    It is the team he belongs to at the end of that month (`today` for the current month); if he has no team
    then, the last team he belonged to during the month.  People with no membership at all are not in the
    map: the caller falls back to the team stored on the card."""
    first, last = month_bounds(day)
    cutoff = max(min(last, today or timezone.localdate()), first)
    rows = (
        TeamMembership.objects
        .filter(start_date__lte=cutoff)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=first))
        .order_by("start_date", "id")                 # the latest membership wins
        .values_list("user_id", "team_id")
    )
    return dict(rows)


def team_totals(date_from=None, date_to=None, card_user_ids=None):
    """{team_id or None: {"sell", "net", "count"}}; each booking goes to the month team of its agent."""
    out = defaultdict(lambda: {"sell": D0, "net": D0, "count": 0})
    maps = {}
    for model, sell_f, net_f in _SOURCES:
        qs = model.objects.all()
        if date_from:
            qs = qs.filter(booking_date__gte=date_from)
        if date_to:
            qs = qs.filter(booking_date__lte=date_to)
        if card_user_ids is not None:
            qs = qs.filter(card__created_by_id__in=card_user_ids)
        rows = qs.values("card__team_id", "card__created_by_id", mon=TruncMonth("booking_date")).annotate(
            s=_SUM(sell_f), n=_SUM(net_f), c=Count("id"))
        for r in rows:
            mon = r["mon"]
            if mon is None:
                team_id = r["card__team_id"]
            else:
                tm = maps.get((mon.year, mon.month))
                if tm is None:
                    tm = maps[(mon.year, mon.month)] = month_team_map(mon)
                team_id = tm.get(r["card__created_by_id"], r["card__team_id"])
            d = out[team_id]
            d["sell"] += r["s"]
            d["net"] += r["n"]
            d["count"] += r["c"]
    return out


def month_progress(day):
    """{team_id: {"target", "achieved", "pct"}} for the month of `day`."""
    first, last = month_bounds(day)
    cycle = current_cycle(day)
    targets = {}
    if cycle:
        targets = {t.team_id: t.target_amount for t in TeamTarget.objects.filter(cycle=cycle)}
    totals = team_totals(first, last)
    res = {}
    for team_id in set(targets) | {k for k in totals if k is not None}:
        achieved = totals[team_id]["sell"] - totals[team_id]["net"] if team_id in totals else D0
        target = targets.get(team_id, D0)
        pct = int(achieved * 100 / target) if target else None
        res[team_id] = {"target": target, "achieved": achieved, "pct": pct}
    return res


def month_matrix(day):
    """{(team_id|None, user_id): {"sell","net","count"}} for the month of `day`.
    The whole month of an agent is under the team he is in at the end of the month (see month_team_map)."""
    first, last = month_bounds(day)
    team_of_user = month_team_map(day)
    out = defaultdict(lambda: {"sell": D0, "net": D0, "count": 0})
    for model, sell_f, net_f in _SOURCES:
        qs = model.objects.filter(booking_date__gte=first, booking_date__lte=last)
        for r in qs.values("card__team_id", "card__created_by_id").annotate(s=_SUM(sell_f), n=_SUM(net_f), c=Count("id")):
            team_id = team_of_user.get(r["card__created_by_id"], r["card__team_id"])
            d = out[(team_id, r["card__created_by_id"])]
            d["sell"] += r["s"]
            d["net"] += r["n"]
            d["count"] += r["c"]
    return out


def profit_of(d):
    return (d["sell"] - d["net"]) if d else D0


def pct(achieved, target):
    return int(achieved * 100 / target) if target else None
