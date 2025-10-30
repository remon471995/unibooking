from __future__ import annotations
from django.contrib.auth import get_user_model
from .models import Ticket, DepartmentMembership

User = get_user_model()

def is_dept_member(user: User, department) -> bool:
    """يتحقق إن المستخدم عضو فعّال بالقسم (أو سوبر يوزر)."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return DepartmentMembership.objects.filter(
        user=user, department=department, is_active=True
    ).exists()

def is_dept_leader(user: User, department) -> bool:
    """قائد قسم (أو سوبر يوزر)."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return DepartmentMembership.objects.filter(
        user=user, department=department, is_active=True,
        role=DepartmentMembership.Role.LEADER
    ).exists()

def can_view_ticket(user: User, ticket: Ticket) -> bool:
    """صلاحية عرض التذكرة: الطالب/المعين/عضو القسم/سوبر."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if ticket.requester_id == user.id or ticket.assigned_to_id == user.id:
        return True
    return is_dept_member(user, ticket.department)

def can_reply_ticket(user: User, ticket: Ticket) -> bool:
    """صلاحية الرد: الطالب نفسه، أو عضو/قائد القسم، أو سوبر."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or ticket.requester_id == user.id:
        return True
    return is_dept_member(user, ticket.department)
