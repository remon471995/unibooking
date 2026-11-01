"""Who can see / edit what, based on the team structure.

Agent -> Team leader -> Supervisor -> Sales manager (+ admin).
Viewing cards is open to every signed-in employee. Editing a card is allowed for its owner
and for everyone above the owner in the hierarchy.
"""
from django.db.models import Q
from django.utils import timezone

from .models import Team, TeamMembership

MANAGER_ROLES = {"admin", "sales_manager"}


def role_of(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if user.is_superuser:
        return "admin"
    prof = getattr(user, "profile", None)
    if prof and prof.role:
        return prof.role
    emp = getattr(user, "employee_profile", None)
    if emp and emp.role == "sales_manager":
        return "sales_manager"
    return "agent"


def is_manager(user):
    return role_of(user) in MANAGER_ROLES


def current_memberships(team_ids=None):
    today = timezone.localdate()
    qs = TeamMembership.objects.filter(start_date__lte=today).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today)
    )
    if team_ids is not None:
        qs = qs.filter(team_id__in=list(team_ids))
    return qs


def team_of(user):
    m = current_memberships().filter(user=user).select_related("team").first()
    return m.team if m else None


def manageable_user_ids(user):
    """None = everyone (sales manager / admin). Otherwise the set of user ids this user may manage."""
    if is_manager(user):
        return None
    ids = {user.id}
    led = list(Team.objects.filter(leader=user, is_active=True).values_list("id", flat=True))
    sup = Team.objects.filter(supervisor=user, is_active=True)
    sup_ids = list(sup.values_list("id", flat=True))
    ids |= set(current_memberships(led + sup_ids).values_list("user_id", flat=True))
    ids |= set(sup.exclude(leader__isnull=True).values_list("leader_id", flat=True))
    return ids


def can_edit_card(user, card):
    """Owner and everyone above the owner today, plus the leader / supervisor of the team the card was
    created in (so cards of an agent who left the team or the company are never orphaned)."""
    ids = manageable_user_ids(user)
    if ids is None or card.created_by_id in ids:
        return True
    team = getattr(card, "team", None)
    return bool(team and user.id in (team.leader_id, team.supervisor_id))
