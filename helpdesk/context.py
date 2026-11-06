def dept_context(request):
    """Which departments the signed-in user may write to / open the inbox of (used by the helpdesk top bar)."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from .permissions import allowed_department_slugs, inbox_slugs
    return {"hd_write_slugs": allowed_department_slugs(user), "hd_inbox_slugs": inbox_slugs(user)}
