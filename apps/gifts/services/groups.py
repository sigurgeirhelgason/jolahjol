"""Flokkar listans: heimilið sjálft, heimili sem er fylgt og föstu flokkarnir.

Efst er heimilisfólkið (Group.HEIMILI), undir nafni heimilisins, t.d. „Laugavegur 5“. Svo koma
heimili sem heimilið fylgir í heild (Family), hvert undir sínu nafni, og loks Börn, Fjölskylda …

Flokkur er strengur: gildi úr Group, eða „f<id>“ fyrir heimili sem er fylgt. Einstaklingur í
fylgdu heimili á `Person.family`; `Person.group` gildir aðeins þegar hann er ekki í slíku.
"""

from dataclasses import dataclass

from apps.core.text import is_sort_key
from apps.households.models import Household

from ..models import GROUP_ICONS, Family, Group, Person

HOME = Group.HEIMILI
FAMILY_ICON = "🏘️"


@dataclass(frozen=True)
class GroupInfo:
    value: str
    label: str
    icon: str

    @property
    def is_home(self) -> bool:
        return self.value == HOME

    @property
    def is_family(self) -> bool:
        return _family_id(self.value) is not None


def family_value(family_id: int) -> str:
    return f"f{family_id}"


def _family_id(value: str) -> int | None:
    """„f12“ → 12; annað (t.d. „fjolskylda“) → None."""
    if value.startswith("f") and value[1:].isdigit():
        return int(value[1:])
    return None


def value_of(person: Person) -> str:
    """Flokkurinn sem einstaklingurinn birtist í."""
    return family_value(person.family_id) if person.family_id else person.group


def families(household: Household) -> list[Family]:
    return sorted(
        Family.objects.filter(household=household).select_related("source"), key=lambda f: is_sort_key(f.name)
    )


def all_groups(household: Household) -> list[GroupInfo]:
    """Allir flokkar heimilisins í röð listans."""
    out = [GroupInfo(HOME, household.name, GROUP_ICONS[HOME])]
    out += [GroupInfo(family_value(f.pk), f.name, FAMILY_ICON) for f in families(household)]
    out += [GroupInfo(v, str(label), GROUP_ICONS[v]) for v, label in Group.choices if v != HOME]
    return out


def choices(household: Household) -> list[tuple[str, str]]:
    """Fyrir val í formum: (gildi, heiti)."""
    return [(g.value, g.label) for g in all_groups(household)]


def label_of(person: Person) -> str:
    if person.family_id:
        return person.family.name
    if person.group == HOME:
        return person.household.name
    return person.get_group_display()


def parse(household: Household, value: str) -> tuple[str, Family | None] | None:
    """(group, family) fyrir gildi úr formi; None ef gildið er ekki flokkur þessa heimilis."""
    if value in Group.values:
        return value, None
    family_id = _family_id(value)
    if family_id is not None:
        family = Family.objects.filter(pk=family_id, household=household).first()
        if family is not None:
            return Group.FJOLSKYLDA, family
    return None


def assign(person: Person, value: str, *, save=True) -> bool:
    """Setur einstaklinginn í flokkinn `value`. Skilar því hvort eitthvað breyttist.

    Í heimili sem er fylgt helst `group` óbreytt (hann fer þangað aftur ef hætt er að fylgja).
    """
    parsed = parse(person.household, value)
    if parsed is None or value == value_of(person):
        return False
    group, family = parsed
    if family is None:
        person.group = group
    person.family = family
    if save:
        person.save(update_fields=["group", "family"])
    return True


def is_valid(household: Household, value: str) -> bool:
    return parse(household, value) is not None
