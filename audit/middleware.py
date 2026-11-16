from contextvars import ContextVar

_current_request = ContextVar("audit_current_request", default=None)


def get_current_request():
    return _current_request.get()


class AuditMiddleware:
    """بيحفظ الـ request الحالي عشان نعرف مين المستخدم اللي عمل التعديل.
    لازم يتحط بعد AuthenticationMiddleware في MIDDLEWARE."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            _current_request.reset(token)
