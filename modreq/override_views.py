"""شاشات "طلب تعديل" الجديدة (فندق / طيران / أخرى).

بدل ما نعدّل 3 دوال في core/views.py يدوي، التطبيق ده بيستبدلهم تلقائي وقت تشغيل المشروع
(من apps.py). الفورم والقوالب والروابط هي هي، الفرق الوحيد: الطلب بيتسجّل ويستنى اعتماد
الداتا انتري بدل ما يتنفّذ على الحجز فوراً.

لو شيلت "modreq" من INSTALLED_APPS الشاشات القديمة ترجع زي ما كانت.
"""
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, Sum, Value as V
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render

logger = logging.getLogger(__name__)


def _make_view(kind):
    from core.forms import ModifyAdjustmentForm
    from core.views_review import KINDS

    from .services import submit_modification

    cfg = KINDS[kind]
    template = f"core/{kind}_payment_modify.html"
    done_url = f"{kind}_payment"
    done_kwarg = "pk" if kind == "other" else "booking_pk"   # رابط دفع "أخرى" بيستخدم pk

    @login_required
    def view(request, booking_pk):
        booking = get_object_or_404(cfg["booking"], pk=booking_pk)
        current_paid = booking.payments.aggregate(
            total=Coalesce(
                Sum("paid_amount", output_field=DecimalField(max_digits=12, decimal_places=2)),
                V(0, output_field=DecimalField(max_digits=12, decimal_places=2)),
            )
        )["total"] or Decimal("0.00")
        current_sell = getattr(booking, cfg["sell"]) or Decimal("0.00")
        current_net = getattr(booking, cfg["net"]) or Decimal("0.00")

        def page(form):
            return render(request, template, {
                "booking": booking, "form": form, "current_net": current_net,
                "current_sell": current_sell, "current_paid": current_paid,
            })

        if request.method != "POST":
            return page(ModifyAdjustmentForm(initial={"method": "cash"}))

        form = ModifyAdjustmentForm(request.POST, request.FILES)
        if form.is_valid():
            dnet = form.cleaned_data.get("delta_net") or Decimal("0")
            dsell = form.cleaned_data.get("delta_sell") or Decimal("0")
            if current_net + dnet < 0:
                form.add_error("delta_net", "لا يمكن أن يصبح صافي الشراء أقل من صفر.")
            if current_sell + dsell < 0:
                form.add_error("delta_sell", "لا يمكن أن يصبح سعر البيع أقل من صفر.")
            if not form.errors:
                ok, msg = submit_modification(kind, booking, request.user, form.cleaned_data)
                (messages.success if ok else messages.error)(request, msg)
                return redirect(done_url, **{done_kwarg: booking.pk})
        return page(form)

    view.__name__ = f"{kind}_payment_modify"
    return view


def install():
    """بيستبدل الدوال القديمة في core.views قبل ما core.urls يتحمّل."""
    try:
        import core.views as core_views
        for kind in ("hotel", "flight", "other"):
            setattr(core_views, f"{kind}_payment_modify", _make_view(kind))
    except Exception:
        logger.exception("modreq: failed to install modification views (old behavior stays)")
