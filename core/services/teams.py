"""Team numbers for the dashboards. Profit = sell - net, by booking date (same basis as the performance page)."""
import calendar
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, DecimalField, Sum
from django.db.models.functions import Coalesce

from core.models import FlightBooking, HotelBooking, OtherBooking, TargetCycle, TeamTarget

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


def team_totals(date_from=None, date_to=None, card_user_ids=None):
    """{team_id or None: {"sell", "net", "count"}} grouped by the team stored on each card."""
    out = defaultdict(lambda: {"sell": D0, "net": D0, "count": 0})
    for model, sell_f, net_f in _SOURCES:
        qs = model.objects.all()
        if date_from:
            qs = qs.filter(booking_date__gte=date_from)
        if date_to:
            qs = qs.filter(booking_date__lte=date_to)
        if card_user_ids is not None:
            qs = qs.filter(card__created_by_id__in=card_user_ids)
        for r in qs.values("card__team_id").annotate(s=_SUM(sell_f), n=_SUM(net_f), c=Count("id")):
            d = out[r["card__team_id"]]
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
