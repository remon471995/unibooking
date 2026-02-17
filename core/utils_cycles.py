# core/utils_cycles.py
from datetime import date
from calendar import monthrange
from django.utils import timezone
from .models import TargetCycle

def _first_last_day(y: int, m: int):
    return date(y, m, 1), date(y, m, monthrange(y, m)[1])

def get_cycle_for_date(d: date, auto_create: bool = True) -> TargetCycle | None:
    c = TargetCycle.objects.filter(year=d.year, month=d.month).first()
    if c:
        return c
    if not auto_create:
        return None
    start, end = _first_last_day(d.year, d.month)
    return TargetCycle.objects.create(year=d.year, month=d.month, start_date=start, end_date=end, locked=False)

def cycle_from_booking_accounting(accounting_date):
    return get_cycle_for_date(accounting_date or timezone.localdate(), auto_create=True)
