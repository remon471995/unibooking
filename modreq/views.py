from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from core.views_review import can_review

from . import services


@login_required
@require_POST
def approve(request, pk):
    if not can_review(request.user):
        return HttpResponseForbidden("غير مسموح")
    ok, msg = services.approve(pk, request.user)
    (messages.success if ok else messages.error)(request, msg)
    return redirect("review_queue")


@login_required
@require_POST
def return_(request, pk):
    if not can_review(request.user):
        return HttpResponseForbidden("غير مسموح")
    ok, msg = services.return_request(pk, request.user, request.POST.get("note"))
    (messages.success if ok else messages.error)(request, msg)
    return redirect("review_queue")
