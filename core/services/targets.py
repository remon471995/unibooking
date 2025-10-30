from decimal import Decimal
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce

from core.models import TargetCycle, StaffTarget, LeaderTarget, BookingAdjustment

# عدّل الاستيراد حسب مكان موديلات الحجوزات عندك:
from core.models import HotelBooking, FlightBooking, OtherBooking  # أو من app أخرى

CANCELLED_STATUSES = {"cancelled", "void", "refunded"}

# الحقل الزمني المعتمد للحساب = تاريخ الحجز
DATE_FIELD_MAP = {
    HotelBooking: "booking_date",
    FlightBooking: "booking_date",
    OtherBooking: "booking_date",
}

def _cycle_range(cycle: TargetCycle):
    return cycle.start_date, cycle.end_date

def _date_filter(field: str, start, end):
    return {f"{field}__date__gte": start, f"{field}__date__lte": end}

def _base_total(model, cycle: TargetCycle, employee_id: int) -> Decimal:
    start, end = _cycle_range(cycle)
    date_field = DATE_FIELD_MAP.get(model, "booking_date")
    agg = (
        model.objects
        .filter(card__created_by_id=employee_id)
        .exclude(status__in=CANCELLED_STATUSES)
        .filter(**_date_filter(date_field, start, end))
        .annotate(profit=Coalesce(F("sell"), 0) - Coalesce(F("net"), 0))
        .aggregate(total=Coalesce(Sum("profit"), 0))
    )
    return Decimal(agg["total"] or 0)

def _adjustments_for(employee_id: int, cycle: TargetCycle) -> Decimal:
    start, end = _cycle_range(cycle)
    base_filter = Q(card__created_by_id=employee_id)

    h_ids = list(HotelBooking.objects.filter(base_filter).values_list("id", flat=True))
    f_ids = list(FlightBooking.objects.filter(base_filter).values_list("id", flat=True))
    o_ids = list(OtherBooking.objects.filter(base_filter).values_list("id", flat=True))

    q = Q()
    if h_ids: q |= Q(booking_type="hotel", booking_id__in=h_ids)
    if f_ids: q |= Q(booking_type="flight", booking_id__in=f_ids)
    if o_ids: q |= Q(booking_type="other", booking_id__in=o_ids)
    if not q:
        return Decimal("0")

    # current => حسب created_at خلال مدى الدورة، أو cycle==الدورة
    adj_qs = BookingAdjustment.objects.filter(q).filter(
        Q(apply_in_cycle="current", created_at__date__gte=start, created_at__date__lte=end) |
        Q(cycle=cycle)
    )
    res = adj_qs.aggregate(total=Coalesce(Sum("amount"), 0))["total"]
    return Decimal(res or 0)

def employee_achieved_profit(employee_id: int, cycle: TargetCycle) -> Decimal:
    base = (
        _base_total(HotelBooking, cycle, employee_id)
        + _base_total(FlightBooking, cycle, employee_id)
        + _base_total(OtherBooking, cycle, employee_id)
    )
    adj = _adjustments_for(employee_id, cycle)
    return (base + adj).quantize(Decimal("0.01"))

def commission_rate_and_amount(achieved: Decimal, st: StaffTarget):
    """نطبّق أعلى نسبة وصلها على كامل الربح (flat)."""
    rate = Decimal("0")
    if achieved >= st.thr3:
        rate = st.rate3
    elif achieved >= st.thr2:
        rate = st.rate2
    elif achieved >= st.thr1:
        rate = st.rate1
    amount = (achieved * rate / Decimal("100")).quantize(Decimal("0.01"))
    return rate, amount

def leader_achieved_profit(leader_id: int, cycle: TargetCycle) -> Decimal:
    staff_ids = StaffTarget.objects.filter(cycle=cycle, leader_id=leader_id).values_list("employee_id", flat=True)
    total = Decimal("0")
    for emp_id in staff_ids:
        total += employee_achieved_profit(emp_id, cycle)
    return total.quantize(Decimal("0.01"))
