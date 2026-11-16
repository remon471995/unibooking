"""تسجيل تلقائي لأي إنشاء/تعديل/حذف على الحجوزات والدفعات والكروت.

ملاحظة: التعديلات الجماعية بـ queryset.update() أو bulk_create/bulk_update مابتعديش على signals،
فمش هتتسجل. استخدم .save() في الأكواد اللي بتغيّر فلوس.
"""
import datetime
import ipaddress
import logging
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.db.models.signals import post_save, pre_delete, pre_save
from django.utils import timezone

from .middleware import get_current_request
from .models import AuditLog

logger = logging.getLogger(__name__)

# (app_label, ModelName) — زوّد أي موديل عايز تتابعه هنا
AUDITED_MODELS = [
    ("core", "UniBookingCard"),
    ("core", "HotelBooking"),
    ("core", "Payment"),
    ("core", "FlightBooking"),
    ("core", "FlightPayment"),
    ("core", "OtherBooking"),
    ("core", "OtherPayment"),
    ("core", "BookingAdjustment"),
    ("core", "BookingAmendment"),
]


# ---------------------------------------------------------------- helpers
def _tracked_fields(model):
    return [
        f for f in model._meta.concrete_fields
        if not f.primary_key
        and not getattr(f, "auto_now", False)
        and not getattr(f, "auto_now_add", False)
    ]


def _norm(field, value):
    """تحويل القيمة لنص ثابت للمقارنة والعرض."""
    if value is None or value == "":
        return None
    # ملفات
    if hasattr(value, "storage") and hasattr(value, "name"):
        return value.name or None
    if isinstance(value, bool):
        return "نعم" if value else "لا"
    if isinstance(value, (Decimal, float)):
        try:
            d = Decimal(str(value))
        except InvalidOperation:
            return str(value)
        s = f"{d:f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s
    if isinstance(value, datetime.datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if field.choices:
        try:
            return str(dict(field.flatchoices).get(value, value))
        except TypeError:
            pass
    return str(value)


def _snapshot_new(instance, fields):
    return {f.name: _norm(f, getattr(instance, f.attname)) for f in fields}


def _snapshot_old(instance, fields):
    row = (
        type(instance)._base_manager.filter(pk=instance.pk)
        .values(*[f.attname for f in fields]).first()
    )
    if row is None:
        return None
    return {f.name: _norm(f, row[f.attname]) for f in fields}


def _card_id(obj):
    if obj.__class__.__name__ == "UniBookingCard":
        return obj.pk
    cid = getattr(obj, "card_id", None)
    if cid:
        return cid
    for f in obj._meta.concrete_fields:
        if f.is_relation and f.many_to_one:
            try:
                rel = getattr(obj, f.name)
            except Exception:
                continue
            cid = getattr(rel, "card_id", None)
            if cid:
                return cid
    return None


def _actor():
    req = get_current_request()
    if req is None:
        return None, None, None
    user = getattr(req, "user", None)
    if user is not None and not getattr(user, "is_authenticated", False):
        user = None
    ip = None
    raw = req.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or req.META.get("REMOTE_ADDR", "")
    try:
        ip = str(ipaddress.ip_address(raw))
    except ValueError:
        ip = None
    name = ""
    if user is not None:
        name = (user.get_full_name() or user.get_username())[:150]
    return user, name, ip


def _write(instance, action, changes):
    try:
        user, name, ip = _actor()
        meta = instance._meta
        try:
            rep = str(instance)[:255]
        except Exception:
            rep = ""
        AuditLog.objects.create(
            user=user, user_repr=name or "", action=action,
            model=meta.object_name, model_label=str(meta.verbose_name)[:100],
            object_id=str(instance.pk), object_repr=rep,
            card_id=_card_id(instance), changes=changes, ip=ip,
        )
    except Exception:  # السجل ماينفعش يبوّظ عملية الحفظ نفسها
        logger.exception("audit: failed to write log")


def _labels(fields):
    return {f.name: str(f.verbose_name) for f in fields}


# ---------------------------------------------------------------- handlers
def _on_pre_save(sender, instance, raw=False, **kwargs):
    if raw:
        return
    instance._audit_old = None
    if instance.pk and not instance._state.adding:
        try:
            instance._audit_old = _snapshot_old(instance, _tracked_fields(sender))
        except Exception:
            logger.exception("audit: failed to read old values")


def _on_post_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    fields = _tracked_fields(sender)
    labels = _labels(fields)
    new = _snapshot_new(instance, fields)
    if created:
        changes = {k: {"label": labels[k], "old": None, "new": v} for k, v in new.items() if v is not None}
        _write(instance, AuditLog.ACTION_CREATE, changes)
        return
    old = getattr(instance, "_audit_old", None)
    if old is None:
        return
    changes = {
        k: {"label": labels[k], "old": old.get(k), "new": v}
        for k, v in new.items() if old.get(k) != v
    }
    if changes:
        _write(instance, AuditLog.ACTION_UPDATE, changes)


def _on_pre_delete(sender, instance, **kwargs):
    fields = _tracked_fields(sender)
    labels = _labels(fields)
    old = _snapshot_new(instance, fields)
    changes = {k: {"label": labels[k], "old": v, "new": None} for k, v in old.items() if v is not None}
    _write(instance, AuditLog.ACTION_DELETE, changes)


def connect_signals():
    for app_label, model_name in AUDITED_MODELS:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            logger.warning("audit: model %s.%s not found", app_label, model_name)
            continue
        uid = f"audit-{app_label}-{model_name}"
        pre_save.connect(_on_pre_save, sender=model, dispatch_uid=uid + "-pre")
        post_save.connect(_on_post_save, sender=model, dispatch_uid=uid + "-post")
        pre_delete.connect(_on_pre_delete, sender=model, dispatch_uid=uid + "-del")
