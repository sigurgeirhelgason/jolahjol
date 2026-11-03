from django import template

from apps.core.money import format_kr, signed_kr

register = template.Library()


@register.filter
def kr(value):
    return format_kr(value)


@register.filter
def signed(value):
    return signed_kr(value or 0)
