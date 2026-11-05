"""„Verslanir“: ókeyptar gjafir eftir búð, eða eftir staðsetningu búðanna. Samsvarar `shopHtml`."""

from dataclasses import dataclass, field

from apps.core.text import is_sort_key

from ..models import Gift, Location, Season, Store
from .queries import season_gifts
from .stores import stores_of


@dataclass
class StoreGroup:
    store: Store | None  # None = búð óákveðin
    gifts: list[Gift] = field(default_factory=list)

    @property
    def plan(self) -> int:
        return sum(g.plan or 0 for g in self.gifts)


@dataclass
class LocationGroup:
    location: Location | None  # None = staðsetning óákveðin
    stores: list[StoreGroup] = field(default_factory=list)

    @property
    def gift_count(self) -> int:
        return sum(len(s.gifts) for s in self.stores)


def _store_sort(group: StoreGroup):
    # Búðir í stafrófsröð, búðarlausar gjafir síðast
    return (group.store is None, is_sort_key(group.store.name) if group.store else ())


def by_store(season: Season, gifts: list[Gift] | None = None) -> list[StoreGroup]:
    groups: dict[int | None, StoreGroup] = {}
    for gift in gifts if gifts is not None else season_gifts(season):
        if gift.bought:
            continue
        for store in stores_of(gift) or [None]:
            key = store.pk if store else None
            groups.setdefault(key, StoreGroup(store)).gifts.append(gift)
    return sorted(groups.values(), key=_store_sort)


def by_location(season: Season, gifts: list[Gift] | None = None) -> list[LocationGroup]:
    """Búð á fleiri en einum stað birtist undir hverjum þeirra; óákveðin staðsetning síðast."""
    groups: dict[int | None, LocationGroup] = {}
    for store_group in by_store(season, gifts):
        locations = list(store_group.store.locations.all()) if store_group.store else []
        for location in locations or [None]:
            key = location.pk if location else None
            groups.setdefault(key, LocationGroup(location)).stores.append(store_group)
    return sorted(
        groups.values(),
        key=lambda g: (g.location is None, is_sort_key(g.location.name) if g.location else ()),
    )
