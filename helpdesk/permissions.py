from __future__ import annotations
from django.contrib.auth import get_user_model
from .models import Ticket, DepartmentMembership

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