"""Reconciliation: are the numbers the reports show consistent with each other?

Per month (by booking date) it shows what the bookings say (sell / net / profit), what has really been collected
(approved payments), what is waiting for the review and what was returned, and it lists the bookings that look wrong."""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, F, Q, Sum

D0 = Decimal("0")
MAX_ISSUES = 200

ISSUE_LABELS = {
    "snapshot": "سعر الدفعة (بيع/نت) مختلف عن سعر الحجز",
    "overpaid": "المدفوع (المعتمد + المنتظر) أكبر من سعر البيع",
    "loss": "سعر البيع أقل من النت",
    "returned_left": "حجز معتمد وفيه دفعة مرجوعة لسه ماتصلّحتش",
    "no_payment": "حجز من أكتر من يوم من غير أي دفعة (مش واصل للمراجعة)",
    "approved_zero": "حجز معتمد وسعر البيع صفر",
}


def reconcile(date_from=None, date_to=None, today=None):
    from django.utils import timezone

    from .views_review import KINDS
    today = today or timezone.localdate()
    months = defaultdict(lambda: {"count": 0, "sell": D0, "net": D0, "paid": D0, "waiting": D0, "returned": D0,
                                  "sell_from_payments": D0})
    issues = defaultdict(list)

    for kind, cfg in KINDS.items():
        sell_f, net_f = cfg["sell"], cfg["net"]
        qs = cfg["booking"].objects.select_related("card")
        if date_from:
            qs = qs.filter(booking_date__gte=date_from)
        if date_to:
            qs = qs.filter(booking_date__lte=date_to)
        qs = qs.annotate(
            n_pay=Count("payments"),
            paid_ok=Sum("payments__paid_amount", filter=Q(payments__review_status="approved")),
            paid_wait=Sum("payments__paid_amount", filter=Q(payments__review_status="pending")),
            paid_ret=Sum("payments__paid_amount", filter=Q(payments__review_status="returned")),
            n_ret=Count("payments", filter=Q(payments__review_status="returned")),
            snap_sell=Sum("payments__sell_price"),
            n_bad_snap=Count("payments", filter=~Q(**{f"payments__sell_price": F(sell_f)}) | ~Q(**{f"payments__net_price": F(net_f)})),
        )
        for b in qs:
            sell, net = getattr(b, sell_f) or D0, getattr(b, net_f) or D0
            ok, wait, ret = b.paid_ok or D0, b.paid_wait or D0, b.paid_ret or D0
            m = months[b.booking_date.strftime("%Y-%m") if b.booking_date else "—"]
            m["count"] += 1; m["sell"] += sell; m["net"] += net
            m["paid"] += ok; m["waiting"] += wait; m["returned"] += ret
            m["sell_from_payments"] += b.snap_sell or D0

            row = {"kind": cfg["label"], "customer": b.card.customer_name, "card_id": b.card_id,
                   "ref": getattr(b, "booking_ref", None) or getattr(b, "voucher_code", None) or f"#{b.pk}",
                   "sell": sell, "net": net, "paid": ok, "waiting": wait}
            if b.n_bad_snap:
                issues["snapshot"].append({**row, "detail": f"{b.n_bad_snap} دفعة"})
            if ok + wait > sell + Decimal("0.01"):
                issues["overpaid"].append({**row, "detail": f"زيادة {ok + wait - sell:.2f}"})
            if sell < net:
                issues["loss"].append({**row, "detail": f"خسارة {net - sell:.2f}"})
            if b.review_status == "approved" and b.n_ret:
                issues["returned_left"].append({**row, "detail": f"{b.n_ret} دفعة"})
            if b.review_status == "approved" and sell == 0:
                issues["approved_zero"].append({**row, "detail": ""})
            if not b.n_pay and b.booking_date and (today - b.booking_date).days >= 1:
                issues["no_payment"].append({**row, "detail": f"من {b.booking_date}"})

    month_rows = []
    for key in sorted(months):
        m = months[key]
        month_rows.append({"month": key, **m, "profit": m["sell"] - m["net"], "remaining": m["sell"] - m["paid"]})
    issue_rows = [{"key": k, "label": ISSUE_LABELS[k], "count": len(v), "rows": v[:MAX_ISSUES]}
                  for k, v in issues.items()]
    issue_rows.sort(key=lambda x: -x["count"])
    totals = {k: sum((r[k] for r in month_rows), D0) for k in ("sell", "net", "profit", "paid", "waiting", "returned", "remaining")}
    totals["count"] = sum(r["count"] for r in month_rows)
    return {"months": month_rows, "issues": issue_rows, "totals": totals}
