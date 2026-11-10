"""„Verslanir“: ókeyptar hugmyndir eftir búð, eða eftir staðsetningu búðanna. Samsvarar `shopHtml`.

Hver ókeypt hugmynd er sín lína með sínum gátreit, undir sinni búð. Þegar hugmynd er keypt
hverfur hún af listanum en aðrar hugmyndir sömu gjafar haldast inni. Gjöf án hugmynda er ein
lína sem merkir gjöfina sjálfa keypta.
"""

from dataclasses import dataclass, field

from apps.core.text import is_sort_key

from ..models import Gift, Idea, Location, Season, Store
from .queries import season_gifts


@dataclass(frozen=True)
class ShopItem:
    gift: Gift
    idea: Idea | None = None  # None = gjöf án hugmynda
    only: bool = True  # eina opna lína gjafarinnar: áætlun gjafarinnar á við línuna

    @property
    def amount(self) -> int | None:
        """Verð hugmyndar; annars áætlun gjafar ef línan er sú eina sem gjöfin á eftir."""
        if self.idea and self.idea.price is not None:
            return self.idea.price
        return self.gift.plan if self.only else None

    @property
    def link(self) -> str:
        return (self.idea.link if self.idea else "") or self.gift.link


@dataclass
class StoreGroup:
    store: Store | None  # None = búð óákveðin
    items: list[ShopItem] = field(default_factory=list)

    @property
    def plan(self) -> int:
        return sum(item.amount or 0 for item in self.items)

    @property
    def gift_count(self) -> int:
        return len({item.gift.pk for item in self.items})


@dataclass
class LocationGroup:
    location: Location | None  # None = staðsetning óákveðin
    stores: list[StoreGroup] = field(default_factory=list)

    @property
    def gift_count(self) -> int:
        return len({item.gift.pk for s in self.stores for item in s.items})


def _store_sort(group: StoreGroup):
    # Búðir í stafrófsröð, búðarlausar línur síðast
    return (group.store is None, is_sort_key(group.store.name) if group.store else ())


def shop_items(gift: Gift) -> list[tuple[Store | None, ShopItem]]:
    """Opnar línur gjafar ásamt búð hverrar.

    Gjöf merkt keypt án keyptrar hugmyndar (gátreiturinn á listanum) er öll keypt. Hugmynd án
    búðar fer undir búðir gjafarinnar ef engin hugmynd hennar hefur búð (eldri gögn).
    """
    ideas = list(gift.ideas.all())
    if not ideas:
        if gift.bought:
            return []
        return [(store, ShopItem(gift)) for store in list(gift.stores.all()) or [None]]
    if gift.bought and not any(i.picked for i in ideas):
        return []
    # Frátekið: einhver annar ætlar að kaupa það, svo það er ekki á innkaupalista heimilisins
    open_ideas = [i for i in ideas if not i.picked and not i.reserved]
    fallback = [] if any(i.store for i in ideas) else list(gift.stores.all())
    only = len(open_ideas) == 1 and not gift.bought
    out = []
    for idea in open_ideas:
        item = ShopItem(gift, idea, only)
        for store in [idea.store] if idea.store else fallback or [None]:
            out.append((store, item))
    return out


def by_store(season: Season, gifts: list[Gift] | None = None) -> list[StoreGroup]:
    groups: dict[int | None, StoreGroup] = {}
    for gift in gifts if gifts is not None else season_gifts(season):
        for store, item in shop_items(gift):
            key = store.pk if store else None
            groups.setdefault(key, StoreGroup(store)).items.append(item)
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
