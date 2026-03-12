# apps/core/templatetags/now.py
from datetime import datetime

from django import template

register = template.Library()


@register.simple_tag
def now():
    return datetime.now()
