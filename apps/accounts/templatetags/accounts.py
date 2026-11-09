from allauth.account.utils import get_next_redirect_url
from django import template
from django.conf import settings
from django.shortcuts import resolve_url

register = template.Library()


@register.simple_tag(takes_context=True)
def next_url(context) -> str:
    """?next= ef hún er örugg (sama vefur), annars forsíðan. Fyrir tengla eins og „Sleppa“."""
    return get_next_redirect_url(context["request"]) or resolve_url(settings.LOGIN_REDIRECT_URL)
