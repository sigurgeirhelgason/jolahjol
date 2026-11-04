"""Búðir og staðsetningar. Samsvarar `canonStore`, `renameStore`, `setLocs` og `storesOf`."""

import re

from django.db import transaction

from apps.core.text import fold_key, is_sort_key, split_list
from apps.households.models import Household

from ..models import Gift, Location, Store

# Staðir sem eru alltaf í boði í búðarglugganum, í þessari röð (eins og LOCATIONS í gamla appinu).
# Location verður ekki til fyrr en staðurinn er valinn fyrir búð.
DEFAULT_LOCATIONS = ["Kringlan", "Smáralind", "Skeifan", "Glerártorg", "Laugavegur"]


def location_choices(household: Household) -> list[str]:
    """Sjálfgefnir staðir fyrst, svo aðrir staðir heimilisins í stafrófsröð (án tvítekninga)."""
    defaults = {fold_key(n) for n in DEFAULT_LOCATIONS}
    others = [loc.name for loc in Location.objects.filter(household=household) if loc.key not in defaults]
    return DEFAULT_LOCATIONS + sorted(others, key=is_sort_key)


def is_url(value: str | None) -> bool:
    return bool(re.match(r"^https?://", value or "", re.IGNORECASE))


def store_from_url(url: str) -> str:
    """https://www.elko.is/vara → „Elko“. Samsvarar `storeFromUrl`."""
    host = re.sub(r"^https?://(www\.)?", "", url, flags=re.IGNORECASE).split("/")[0].split(".")[0]
    return host[:1].upper() + host[1:]


def get_or_create_store(household: Household, name: str) -> Store | None:
    """Búð eftir nafni; Elkó og Elko eru sama búðin og fyrsti rithátturinn heldur sér."""
    name = (name or "").strip()
    if not name:
        return None
    store, _ = Store.objects.get_or_create(household=household, key=fold_key(name), defaults={"name": name})
    return store


def get_or_create_location(household: Household, name: str) -> Location:
    location, _ = Location.objects.get_or_create(
        household=household, key=fold_key(name), defaults={"name": name.strip()}
    )
    return location


def set_locations(store: Store, names: list[str] | str) -> None:
    """Setur staðsetningar búðar; tekur lista eða kommuaðskilinn streng („Kringlan, Smáralind“)."""
    if isinstance(names, str):
        names = split_list(names)
    store.locations.set([get_or_create_location(store.household, n) for n in names])


def find_conflict(store: Store, new_name: str) -> Store | None:
    """Önnur búð sem heitir nú þegar `new_name` (þá þarf að spyrja um sameiningu)."""
    return (
        Store.objects.filter(household=store.household, key=fold_key(new_name)).exclude(pk=store.pk).first()
    )


@transaction.atomic
def rename_or_merge(store: Store, new_name: str) -> Store:
    """Endurnefnir búð í öllum árum. Ef nafnið er til sameinast búðirnar, staðsetningar líka.

    Skilar búðinni sem heldur áfram. Viðmótið spyr notandann fyrst ef `find_conflict` finnur búð.
    """
    new_name = new_name.strip()
    if not new_name or new_name == store.name:
        return store
    target = find_conflict(store, new_name)
    if target is None:
        store.name = new_name
        store.save()
        return store
    target.locations.add(*store.locations.all())
    store.ideas.update(store=target)
    for gift in Gift.objects.filter(stores=store):
        gift.stores.add(target)
    store.delete()
    return target


def stores_of(gift: Gift) -> list[Store]:
    """Búðir gjafar koma úr hugmyndunum; búð á gjöfinni sjálfri er varaleið."""
    from_ideas = [i.store for i in gift.ideas.all() if i.store]
    stores = from_ideas or list(gift.stores.all())
    unique = {s.pk: s for s in stores}
    return sorted(unique.values(), key=lambda s: is_sort_key(s.name))
