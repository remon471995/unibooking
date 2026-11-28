from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .history import booking_history
from .views_review import KINDS


@login_required
def booking_history_view(request, kind, pk):
    if kind not in KINDS:
        from django.http import Http404
        raise Http404
    cfg = KINDS[kind]
    booking = get_object_or_404(cfg["booking"].objects.select_related("card__created_by"), pk=pk)
    return render(request, "core/booking_history.html", {
        "kind": kind, "label": cfg["label"], "booking": booking, "card": booking.card,
        "events": booking_history(kind, booking),
    })
