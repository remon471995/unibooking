from django.db.models import Q
from core.models import Notification
from core.permissions import is_sales_side, sees_installments, sees_review, sees_performance


def _review_pending(user):
    if not sees_review(user):
        return 0
    try:
        from core.views_review import pending_review_count
        return pending_review_count()
    except Exception:
        return 0


def notifications_context(request):
    if not request.user.is_authenticated:
        return {}
    # تنبيهات "للسوبر يوزر" بتظهر للسوبر يوزر بس (غيره مايقدرش يعلّمها مقروءة فكانت بتفضل عنده)
    cond = Q(to_user=request.user)
    if request.user.is_superuser:
        cond |= Q(to_superusers=True)
    unread = Notification.objects.filter(cond, is_read=False)
    u = request.user
    return {
        "nav_notifications": unread.order_by('-created_at')[:10],
        "nav_unread_count": unread.count(),
        # menu visibility: sales-only items are hidden from CS / Operations / FFT / Quotation staff
        "is_sales_side": is_sales_side(u),
        "sees_installments": sees_installments(u),
        "sees_review": sees_review(u),
        "sees_performance": sees_performance(u),
        # the number of items waiting for the data entry (shown next to "المراجعة" in the menu)
        "rv_pending": _review_pending(u),
    }
