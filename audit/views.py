from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils.dateparse import parse_date

from core.views_review import can_review

from .models import AuditLog


def _check(user):
    # نفس صلاحية شاشة المراجعة: أدمن / مدير مبيعات / داتا انتري
    if not can_review(user):
        raise PermissionDenied


def _paginate(request, qs, per_page):
    page = Paginator(qs, per_page).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page, params.urlencode()


@login_required
def audit_list(request):
    _check(request.user)
    qs = AuditLog.objects.all()

    q = (request.GET.get("q") or "").strip()
    model = request.GET.get("model") or ""
    action = request.GET.get("action") or ""
    card = (request.GET.get("card") or "").strip()
    d_from = parse_date(request.GET.get("date_from") or "")
    d_to = parse_date(request.GET.get("date_to") or "")

    if q:
        from django.db.models import Q
        qs = qs.filter(Q(user_repr__icontains=q) | Q(object_repr__icontains=q) | Q(object_id=q))
    if model:
        qs = qs.filter(model=model)
    if action:
        qs = qs.filter(action=action)
    if card.isdigit():
        qs = qs.filter(card_id=int(card))
    if d_from:
        qs = qs.filter(created_at__date__gte=d_from)
    if d_to:
        qs = qs.filter(created_at__date__lte=d_to)

    page, querystring = _paginate(request, qs, 50)
    return render(request, "audit/audit_list.html", {
        "page": page, "querystring": querystring,
        "models": AuditLog.objects.values_list("model", "model_label").distinct().order_by("model_label"),
        "actions": AuditLog.ACTIONS,
        "f": {"q": q, "model": model, "action": action, "card": card,
              "date_from": request.GET.get("date_from", ""), "date_to": request.GET.get("date_to", "")},
    })


@login_required
def card_history(request, card_id):
    _check(request.user)
    qs = AuditLog.objects.filter(card_id=card_id)
    page, querystring = _paginate(request, qs, 100)
    return render(request, "audit/card_history.html", {
        "page": page, "querystring": querystring, "card_id": card_id,
    })
