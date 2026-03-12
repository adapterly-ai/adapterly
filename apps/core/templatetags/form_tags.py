# apps/common/templatetags/form_tags.py
from django import template

register = template.Library()


@register.filter
def add_class(field, css):
    attrs = field.field.widget.attrs.copy()
    # keep existing class(es)
    if "class" in attrs:
        attrs["class"] += f" {css}"
    else:
        attrs["class"] = css
    return field.as_widget(attrs=attrs)
