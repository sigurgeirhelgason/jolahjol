"""Einstaklingar sem viðtakendur og gefendur. Samsvarar `resolveName`, `renamePerson` og `fromList`."""

from django.db import transaction
from django.db.models import Case, IntegerField, Value, When

from apps.core.text import normalize
from apps.households.models import Household

from ..models import Gift, Group, Idea, IdeaGiver, Person

# „frá okkur“ þýðir engir gefendur; þessi nöfn verða aldrei að einstaklingum
FROM_US = {"okkur", "við", "frá okkur", "við öll"}


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


def givers_from_names(household: Household, names: list[str]) -> list[Person]:
    """Gefendur úr nöfnum í gefendareitnum, í sömu röð og án tvítekninga.

    Nafn sem er ekki til verður að einstaklingi sem er bara gefandi (falinn sem viðtakandi).
    """
    out: dict[str, Person] = {}
    for name in names:
        key = normalize(name)
        if key and key not in FROM_US and key not in out:
            out[key] = find_or_create(household, name)
    return list(out.values())


def is_shared(person: Person, except_gift: Gift | None = None) -> bool:
    """Er einstaklingurinn notaður annars staðar en í `except_gift` (önnur ár, gefandi, frátekning)?"""
    gifts = Gift.objects.filter(person=person)
    if except_gift is not None:
        gifts = gifts.exclude(pk=except_gift.pk)
    return (
        gifts.exists()
        or IdeaGiver.objects.filter(person=person).exists()
        or Idea.objects.filter(reserved_by=person).exists()
    )


@transaction.atomic
def resolve_recipient(gift: Gift, name: str) -> Person:
    """Nafni viðtakanda breytt í gjafaglugganum. Samsvarar `resolveName`.

    - Nafn annars einstaklings: gjöfin færist á hann.
    - Annars er einstaklingurinn endurnefndur, nema hann sé notaður annars staðar
      (t.d. gjafir fyrri ára). Þá er þetta nýr viðtakandi, ekki nafnabreyting.
    """
    current = gift.person
    name = name.strip()
    if normalize(name) == current.key:
        if name != current.name:
            current.name = name
            current.save()
        return current
    other = Person.objects.filter(household=current.household, key=normalize(name)).first()
    if other and Gift.objects.alive().filter(season=gift.season, person=other).exclude(pk=gift.pk).exists():
        raise ValueError(f"„{other.name}“ er þegar á listanum þetta ár")
    if other is None and not is_shared(current, except_gift=gift):
        current.name = name
        current.save()
        return current
    target = other or Person.objects.create(household=current.household, name=name, group=current.group)
    gift.person = target
    gift.save(update_fields=["person", "updated_at"])
    if not is_shared(current):
        current.delete()
    return target


@transaction.atomic
def update_details(person: Person, *, group, birthday, give_christmas, give_birthday) -> Person:
    person.group = group
    person.birthday = birthday
    person.give_christmas = give_christmas
    person.give_birthday = give_birthday
    person.save(update_fields=["group", "birthday", "give_christmas", "give_birthday"])
    return person


def for_people_page(household: Household) -> list[Person]:
    """„Fólk & Fjölskylda“: þau sem fá gjafir eða eru með afmæli skráð.

    Gefendur sem hafa aldrei fengið gjöf (t.d. Amma Jóa sem gefandi) birtast ekki hér.
    """
    from django.db.models import Exists, OuterRef, Q

    live = Gift.objects.filter(person=OuterRef("pk"), deleted_at__isnull=True)
    return list(
        Person.objects.filter(household=household)
        .filter(Q(Exists(live)) | Q(birthday__isnull=False) | Q(give_birthday=True))
        .order_by("key")
    )
