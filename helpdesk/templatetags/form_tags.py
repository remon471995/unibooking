from django import template

register = template.Library()

@register.filter(name="add_class")
def add_class(field, css):
    """
    مثال الاستخدام في التمبلت:
    {{ form.subject|add_class:"hd-input" }}
    """
    return field.as_widget(attrs={"class": css})
