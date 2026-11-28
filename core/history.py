"""The whole story of one booking, oldest first: who created it, every payment, every review step (approved /
returned with the reason / fixed / re-sent), unlock and modification requests, and the field-by-field changes."""
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from .models import ReviewLog

LOG_LABELS = {
    "approved": ("✅", "اعتمد الداتا انتري", "ok"),
    "returned": ("↩", "رجّع الداتا انتري للتصحيح", "bad"),
    "fixed": ("🛠", "تصحيح من الأجنت", "info"),
    "resubmitted": ("🔁", "إعادة إرسال للمراجعة", "info"),
    "edited": ("✏", "تعديل بيانات الحجز", "info"),
    "unlock_requested": ("🔓", "طلب فتح للتعديل", "info"),
    "unlock_approved": ("🔓", "اتفتح للتعديل", "ok"),
    "unlock_rejected": ("🔒", "اترفض طلب الفتح", "bad"),
}
MOD_STATUS = {"approved": ("✅", "اعتُمد طلب التعديل", "ok"), "returned": ("↩", "اترجّع طلب التعديل", "bad")}
PAY_STATUS = {"pending": "بانتظار المراجعة", "approved": "معتمدة", "returned": "مرجوعة"}


def _who(user, fallback=""):
    if user:
        return user.get_full_name() or user.get_username()
    return fallback or "—"


def booking_history(kind, booking):
    from .views_review import KINDS, METHOD_LABELS
    cfg = KINDS[kind]
    pays = list(getattr(booking, "payments").order_by("created_at"))
    pay_ids = [p.pk for p in pays]
    events = []

    def add(at, who, icon, title, detail="", tone="info", changes=None):
        if at:
            events.append({"at": at, "who": who or "—", "icon": icon, "title": title, "detail": detail,
                           "tone": tone, "changes": changes or []})

    add(booking.created_at, booking.employee_name or _who(booking.card.created_by), "🆕", f"تم إنشاء حجز {cfg['label']}")
    for p in pays:
        add(p.created_at, p.employee_name, "💳",
            f"دفعة {p.paid_amount} — {METHOD_LABELS.get(p.method, p.method)}",
            f"الحالة الآن: {PAY_STATUS.get(p.review_status, p.review_status)}")

    ct_b = ContentType.objects.get_for_model(booking)
    ct_p = ContentType.objects.get_for_model(cfg["payment"])
    logs = (ReviewLog.objects.filter(Q(content_type=ct_b, object_id=booking.pk)
                                     | Q(content_type=ct_p, object_id__in=pay_ids)).select_related("by"))
    for lg in logs:
        icon, title, tone = LOG_LABELS.get(lg.action, ("•", lg.action, "info"))
        if lg.content_type_id == ct_p.id:
            title = "الدفعة: " + title
        add(lg.at, _who(lg.by), icon, title, lg.note, tone)

    try:
        from modreq.models import ModificationRequest
        for m in ModificationRequest.objects.filter(kind=kind, booking_id=booking.pk):
            parts = [f"{label} {val:+}" for label, val in (("بيع", m.delta_sell), ("نت", m.delta_net), ("مدفوع", m.delta_paid)) if val]
            add(m.created_at, m.requested_by_name or _who(m.requested_by), "🛠", "طلب تعديل",
                " | ".join(parts) + (f" — {m.note}" if m.note else ""))
            if m.status in MOD_STATUS and m.reviewed_at:
                icon, title, tone = MOD_STATUS[m.status]
                add(m.reviewed_at, _who(m.reviewed_by), icon, title, m.review_note, tone)
    except Exception:       # the modification app is optional here
        pass

    try:
        from audit.models import AuditLog
        rows = AuditLog.objects.filter(action="update").filter(
            Q(model=booking._meta.object_name, object_id=str(booking.pk))
            | Q(model=cfg["payment"]._meta.object_name, object_id__in=[str(i) for i in pay_ids]))
        for a in rows:
            ch = [f"{v.get('label', k)}: {v.get('old') if v.get('old') not in (None, '') else '—'} ← "
                  f"{v.get('new') if v.get('new') not in (None, '') else '—'}"
                  for k, v in (a.changes or {}).items() if isinstance(v, dict)]
            if ch:
                add(a.created_at, a.user_repr, "📝", "تغيير في " + (a.model_label or a.model), "", "info", ch)
    except Exception:
        pass

    events.sort(key=lambda e: e["at"])
    return events
