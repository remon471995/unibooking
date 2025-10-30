from django.db.models import Q
from core.models import Notification

def notifications_context(request):
    if not request.user.is_authenticated:
        return {}
    qs = Notification.objects.filter(
        Q(to_user=request.user) | Q(to_superusers=True),
        is_read=False
    ).order_by('-created_at')[:10]
    return {"nav_notifications": qs}
