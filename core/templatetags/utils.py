from django import template
register = template.Library()

@register.filter
def model_name(obj):
    return obj.__class__.__name__.lower()
