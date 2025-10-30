# accounts/decorators.py
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied

def superuser_check(user):
    """Checks if the user is a superuser."""
    if user.is_authenticated and user.is_superuser:
        return True
    # Optional: Raise PermissionDenied for better error handling/logging
    # raise PermissionDenied 
    return False

# The actual decorator
super_required = user_passes_test(superuser_check)

# Optional: Decorator for Leaders/Managers (if needed elsewhere)
def manager_or_leader_check(user):
    """Checks if the user is a superuser, manager, or leader."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    # Assumes 'role' is on the UserProfile model linked via user.profile
    profile = getattr(user, 'profile', None)
    if profile and profile.role in ['MANAGER', 'LEADER']:
        return True
    return False

manager_or_leader_required = user_passes_test(manager_or_leader_check)