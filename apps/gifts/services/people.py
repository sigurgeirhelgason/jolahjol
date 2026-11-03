"""Einstaklingar sem viðtakendur og gefendur. Samsvarar `resolveName`, `renamePerson` og `fromList`."""

from django.db import transaction
from django.db.models import Case, IntegerField, Value, When

from apps.core.text import normalize
from apps.households.models import Household

from ..models import Gift, Group, Idea, IdeaGiver, Person


def find_or_create(household: Household, name: str, group: str = Group.ANNAD) -> Person:
    """Einstaklingur eftir nafni (há- og lágstafir skipta ekki máli). Nýr fer í `group`.

    Nýr gefandi verður sjálfkrafa falinn sem viðtakandi, því hann á enga gjöf.
    """
    person, _ = Person.objects.get_or_create(
        household=household, key=normalize(name), defaults={"name": name.strip(), "group": group}
    )
    return person


def search(household: Household, query: str, limit: int = 8) -> list[Person]:
    """Tillögur fyrir sjálfvirka útfyllingu: nöfn sem byrja á leitinni fyrst, svo sem innihalda hana."""
    q = normalize(query)
    people = Person.objects.filter(household=household)
    if q:
        people = people.filter(key__contains=q)
    people = people.annotate(
        starts=Case(When(key__startswith=q, then=Value(0)), default=Value(1), output_field=IntegerField())
    )
    return list(people.order_by("starts", "key")[:limit])


def find_conflict(person: Person, new_name: str) -> Person | None:
    return (
        Person.objects.filter(household=person.household, key=normalize(new_name))
        .exclude(pk=person.pk)
        .first()
    )


@transaction.atomic
def merge(source: Person, target: Person) -> Person:
    """Færir allt frá `source` yfir á `target` og eyðir `source`.

    Eigi bæði gjöf sama ár sameinast hugmyndirnar í gjöf `target`.
    """
    for gift in Gift.objects.filter(person=source).select_related("season"):
        existing = Gift.objects.alive().filter(person=target, season=gift.season).first()
        if existing and gift.deleted_at is None:
            gift.ideas.update(gift=existing)
            existing.stores.add(*gift.stores.all())
            existing.plan = (existing.plan or 0) + (gift.plan or 0) or None
            existing.bought = existing.bought or gift.bought
            existing.save()
            gift.delete()
        else:
            gift.person = target
            gift.save(update_fields=["person"])
    for link in IdeaGiver.objects.filter(person=source):
        if IdeaGiver.objects.filter(idea=link.idea, person=target).exists():
            link.delete()
        else:
            link.person = target
            link.save(update_fields=["person"])
    Idea.objects.filter(reserved_by=source).update(reserved_by=target)
    source.delete()
    return target


@transaction.atomic
def rename(person: Person, new_name: str, *, merge_into_existing: bool = False) -> Person:
    """Endurnefnir í öllum árum. Ef nafnið er til þarf `merge_into_existing` (viðmótið spyr fyrst)."""
    new_name = new_name.strip()
    if not new_name or new_name == person.name:
        return person
    other = find_conflict(person, new_name)
    if other is None:
        person.name = new_name
        person.save()
        return person
    if not merge_into_existing:
        raise ValueError(f"„{other.name}“ er þegar til")
    return merge(person, other)
