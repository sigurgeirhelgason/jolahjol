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
def can_hide(idea) -> bool:
    """× á ósk annars á listanum: sama regla og þjónninn (gifts.can_hide)."""
    from apps.gifts.services.gifts import can_hide as rule

    return rule(idea)


@register.filter
def giver_names(idea) -> str:
    """„Amma Jóa og Afi“ (úr prefetch, ekkert nýtt kall)."""
    return _names(link.person for link in idea.giver_links.all())


@register.filter
def gives_text(idea) -> str:
    """„Ragnhildur gefur gjöfina“ / „Amma Jóa og Afi gefa gjöfina“ (tómt ef frá okkur)."""
    from apps.gifts.services.gifts import gives_phrase

    return gives_phrase([link.person.name for link in idea.giver_links.all()])


@register.filter
def idea_title(idea) -> str:
    """Tooltip á hugmynd: texti · frá … · keypt fyrir annan · lýsing · búð."""
    links = list(idea.giver_links.all())
    parts = [idea.text]
    if links:
        parts.append(gives_text(idea))
    if idea.for_other:
        paid = links and all(link.paid for link in links)
        parts.append(_("keypt fyrir annan, greitt") if paid else _("keypt fyrir annan, ógreitt"))
    if idea.reserved and not idea.picked:
        if idea.reserved_by:
            parts.append(_("frátekið af %(name)s") % {"name": idea.reserved_by.name})
        else:
            parts.append(_("frátekið"))
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
def in_set(value, collection) -> bool:
    """`{% with hidden=person.pk|in_set:hidden_people %}`; `in` dugar aðeins í {% if %}."""
    return bool(collection) and value in collection


def _peek_labels() -> list[str]:
    return [
        _("Bannað að kíkja! 🎅"),
        _("Gluggagægir, farðu frá! 👀"),
        _("Leyndó 🤫"),
        _("Jólasveinninn einn veit 🎁"),
        _("Kertasníkir faldi þetta 🕯️"),
        _("Pakkað inn og falið 🎄"),
    ]


@register.filter
def peek_label(person_id) -> str:
    """Texti yfir falinni línu (augað við nafnið); alltaf sá sami fyrir sama einstakling."""
    labels = _peek_labels()
    return labels[int(person_id or 0) % len(labels)]


@register.filter
def gift_summary(gift) -> str:
    """Valdar hugmyndir (annars allar) með gefendum: „púsl (Amma Jóa gefur), bók“."""
    from apps.gifts.services.gifts import gift_text

    return gift_text(gift)
