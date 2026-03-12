import json

from django import template

register = template.Library()


@register.filter
def to_json(value):
    """
    Convert Python object to JSON string with proper double quotes.
    """
    if value is None:
        return "{}"
    return json.dumps(value, indent=2, ensure_ascii=False)
