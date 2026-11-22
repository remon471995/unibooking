"""مين يشوف الملاحظات الداخلية: كاتبها + أعضاء نفس القسم/الفريق (CS أو Operations أو FFT أو Quotation) + المدراء (أدمن / سيلز مانجر).
باقي الموظفين (حتى لو القسم التاني على نفس التذكرة) مايشوفوهاش، والأجنت اللي فتح الطلب برضه لأ.
"""
from django.db.models import Q

from .models import Department, DepartmentMembership
from .permissions import _is_manager


def user_dept_ids(user):
    """أقسام المستخدم: عضويته الفعّالة + الأقسام اللي هو مديرها."""
    if not user or not getattr(user, "is_authenticated", False):
        return set()
    ids = set(DepartmentMembership.objects.filter(user=user, is_active=True).values_list("department_id", flat=True))
    ids |= set(Department.objects.filter(manager=user).values_list("id", flat=True))
    return ids


def can_see_note(user, msg):
    """هل المستخدم يقدر يشوف الرسالة دي؟ (الرسائل العادية للكل، الملاحظة الداخلية بالقاعدة فوق)."""
    if not msg.is_internal_note:
        return True
    if _is_manager(user):
        return True
    if msg.sender_id is None:
        return False
    if msg.sender_id == user.id:
        return True
    return bool(user_dept_ids(user) & user_dept_ids(msg.sender))


def filter_visible_messages(user, qs):
    """بيشيل من الـ queryset الملاحظات الداخلية اللي المستخدم مالوش حق يشوفها."""
    if _is_manager(user):
        return qs
    peer_ids = {user.id}
    dept_ids = user_dept_ids(user)
    if dept_ids:
        peer_ids |= set(DepartmentMembership.objects.filter(
            department_id__in=dept_ids, is_active=True).values_list("user_id", flat=True))
        peer_ids |= set(Department.objects.filter(
            id__in=dept_ids, manager__isnull=False).values_list("manager_id", flat=True))
    return qs.filter(Q(is_internal_note=False) | Q(sender_id__in=peer_ids))
