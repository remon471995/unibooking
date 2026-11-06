from __future__ import annotations
from django.contrib.auth import get_user_model
from .models import Ticket, Department, DepartmentMembership

User = get_user_model()

def is_dept_member(user: User, department) -> bool:
    """
    يتحقق إن المستخدم عضو فعّال بالقسم، أو هو مدير القسم، أو سوبر يوزر.
    """
    if not user.is_authenticated:
        return False
        
    if user.is_superuser:
        return True
        
    # التحقق إن كان هو مدير القسم المباشر (إضافة للأداء)
    if department.manager_id == user.id:
        return True
        
    return DepartmentMembership.objects.filter(
        user=user, department=department, is_active=True
    ).exists()

def is_dept_leader(user: User, department) -> bool:
    """
    يتحقق إن المستخدم قائد (Leader) في القسم، أو مدير القسم نفسه.
    """
    if not user.is_authenticated:
        return False
        
    if user.is_superuser:
        return True
        
    # المدير يعتبر قائد تلقائياً
    if department.manager_id == user.id:
        return True
        
    return DepartmentMembership.objects.filter(
        user=user, department=department, is_active=True,
        role=DepartmentMembership.Role.LEADER
    ).exists()

def can_view_ticket(user: User, ticket: Ticket) -> bool:
    """
    صلاحية عرض التذكرة:
    1. السوبر يوزر.
    2. أطراف التذكرة (الطالب أو المسؤول).
    3. المراقبون (Watchers).
    4. أعضاء القسم المختص.
    """
    if not user.is_authenticated:
        return False
        
    if user.is_superuser:
        return True
        
    # التحقق من الطالب أو المسؤول باستخدام ID لسرعة الأداء
    if ticket.requester_id == user.id or ticket.assigned_to_id == user.id:
        return True
        
    # a request CS forwarded to Operations / FFT is also visible to the CS team that owns the original
    if ticket.parent_id and is_dept_member(user, ticket.parent.department):
        return True

    # the requester's team leader / supervisor and sales managers follow their people's requests
    from core.permissions import manageable_user_ids
    ids = manageable_user_ids(user)
    if ids is None or ticket.requester_id in ids:
        return True

    # السماح للمراقبين (CC)
    if ticket.watchers.filter(pk=user.pk).exists():
        return True
        
    # السماح لأعضاء القسم
    return is_dept_member(user, ticket.department)

def can_reply_ticket(user: User, ticket: Ticket) -> bool:
    """
    صلاحية الرد: نفس صلاحيات المشاهدة.
    (أي شخص يقدر يشوف التذكرة، يقدر يرد عليها)
    """
    return can_view_ticket(user, ticket)


# ---------------------------------------------------------------------------
# Who talks to whom
#   sales  -> CS and Quotation only
#   CS     -> everybody (it forwards to Operations / FFT and relays their answer back to sales)
#   Operations / FFT / Quotation staff -> CS
#   managers / admin -> everybody
# ---------------------------------------------------------------------------
def member_slugs(user) -> set:
    if not user.is_authenticated:
        return set()
    return set(DepartmentMembership.objects.filter(user=user, is_active=True).values_list("department__slug", flat=True))


def _is_manager(user) -> bool:
    from core.permissions import is_manager
    return user.is_superuser or is_manager(user)


def allowed_department_slugs(user) -> set:
    if _is_manager(user):
        return set(Department.objects.filter(is_active=True).values_list("slug", flat=True))
    mine = member_slugs(user)
    if "cs" in mine:
        return set(Department.objects.filter(is_active=True).values_list("slug", flat=True))
    if mine:
        return {"cs"}
    return {"cs", "quotation"}


def inbox_slugs(user) -> set:
    if _is_manager(user):
        return set(Department.objects.filter(is_active=True).values_list("slug", flat=True))
    return member_slugs(user)


def can_forward(user, ticket: Ticket) -> bool:
    """Only CS (and managers) forward a sales request to Operations / FFT."""
    if ticket.department.slug != "cs":
        return False
    return _is_manager(user) or "cs" in member_slugs(user)


def can_see_internal(user, ticket: Ticket) -> bool:
    """Internal notes are for the department's staff, never for the agent who opened the request."""
    if _is_manager(user) or is_dept_member(user, ticket.department):
        return True
    return bool(ticket.parent_id and is_dept_member(user, ticket.parent.department))
