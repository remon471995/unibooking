from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils.dateparse import parse_date

from .permissions import sees_all_bookings
from .reconcile import reconcile


@login_required
def reconcile_view(request):
    if not sees_all_bookings(request.user):
        return HttpResponseForbidden("🚫 صفحة المطابقة للي بيشوف كل الحجوزات.")
    q_from = (request.GET.get("from") or "").strip()
    q_to = (request.GET.get("to") or "").strip()
    data = reconcile(parse_date(q_from) if q_from else None, parse_date(q_to) if q_to else None)
    return render(request, "core/reconcile.html", {**data, "q_from": q_from, "q_to": q_to})
