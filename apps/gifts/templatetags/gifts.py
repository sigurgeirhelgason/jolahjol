from django import template
from django.utils.translation import gettext as _

from apps.core.money import format_kr
from apps.gifts.models import GROUP_ICONS, Group

register = template.Library()


def _names(people) -> str:
    names = [p.name for p in people]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " " + _("og") + " " + names[-1]


@register.filter
def giver_names(idea) -> str:
    """„Amma Jóa og Afi“ (úr prefetch, ekkert nýtt kall)."""
    return _names(link.person for link in idea.giver_links.all())


@register.filter
def idea_title(idea) -> str:
    """Tooltip á hugmynd: texti · frá … · keypt fyrir annan · lýsing · búð."""
    links = list(idea.giver_links.all())
    parts = [idea.text]
    if links:
        parts.append(_("frá %(names)s") % {"names": _names(link.person for link in links)})
    if idea.for_other:
        paid = links and all(link.paid for link in links)
        parts.append(_("keypt fyrir annan, greitt") if paid else _("keypt fyrir annan, ógreitt"))
    if idea.price:
        parts.append(format_kr(idea.price))
    if idea.note:
        parts.append(idea.note)
    if idea.store:
        parts.append(idea.store.name)
    return " · ".join(parts)


@register.filter
def all_paid(idea) -> bool:
    links = list(idea.giver_links.all())
    return bool(links) and all(link.paid for link in links)


@register.filter
def locations_title(store) -> str:
    return ", ".join(loc.name for loc in store.locations.all())


@register.filter
def group_icon(value) -> str:
    return GROUP_ICONS.get(value, "")


@register.filter
def group_label(value) -> str:
    """Stutt heiti flokks í yfirliti („Vinna“ í stað „Vinna & skóli“)."""
    from apps.gifts.listing import GROUP_SHORT

    return str(GROUP_SHORT.get(value) or Group(value).label)


@register.filter
def get(mapping, key):
    return mapping.get(key)


@register.filter
def gift_summary(gift) -> str:
    """Valdar hugmyndir (annars allar) með gefendum: „púsl (frá Ömmu Jóu), bók“."""
    from apps.gifts.services.gifts import gift_text

    return gift_text(gift)
