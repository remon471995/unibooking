from django import template

from .. import services

register = template.Library()


@register.inclusion_tag("modreq/_banner.html")
def modreq_banner(kind, booking_id):
    """بانر على صفحات الدفع والتعديل: طلب بانتظار الاعتماد أو مرجوع."""
    return services.state_for(kind, booking_id)
