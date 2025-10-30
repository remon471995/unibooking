from django import template

register = template.Library()


@register.filter
def as_widget(field, attrs=None):
    base = {"class": "w-full border rounded-md px-3 py-2"}
    if attrs and isinstance(attrs, dict):
        base.update(attrs)
    return field.as_widget(attrs=base)


@register.filter
def ta_attrs(field):
    return field.as_widget(
        attrs={"class": "w-full border rounded-md px-3 py-2", "rows": 4}
    )
