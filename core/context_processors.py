from django.db.models import Q
from core.models import Notification
from core.permissions import is_sales_side, sees_installments, sees_review, sees_performance


def notifications_context(request):
    if not request.user.is_authenticated:
        return {}
    qs = Notification.objects.filter(
        Q(to_user=request.user) | Q(to_superusers=True),
        is_read=False
    ).order_by('-created_at')[:10]
    u = request.user
    return {
        "nav_notifications": qs,
        # menu visibility: sales-only items are hidden from CS / Operations / FFT / Quotation staff
        "is_sales_side": is_sales_side(u),
        "sees_installments": sees_installments(u),
        "sees_review": sees_review(u),
        "sees_performance": sees_performance(u),
    }
