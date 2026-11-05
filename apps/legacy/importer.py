"""Innflutningur JSON-afrits úr gamla appinu (gjafalistinn/index.html, v2-snið).

Reglurnar úr `splitStoreLinks` og `tidyStores` eru endurteknar hér svo eldri afrit
hreinsist eins og þau gerðu við hleðslu í gamla appinu.
"""

import datetime
from dataclasses import dataclass, field

from django.db import transaction

from apps.core.text import fold_key, normalize, split_list
from apps.gifts.models import Gift, Group, Idea, IdeaGiver, Location, Person, Season, Store
from apps.gifts.services import people, stores
from apps.households.models import Household

# Gildi í búðardálki Excel-skjalsins sem eru í raun keyptar gjafir
NOT_STORES = {
    "jola keanu": ["jóla Keanu"],
    "ur, bok": ["úr", "bók"],
    "spidermanur, bok": ["spidermanúr", "bók"],
    "svefngrima silki": ["svefngríma silki"],
    "skartgripaskrin, ferða": ["ferðaskartgripaskrín"],
    "mini le creuset": ["mini Le Creuset"],
    "levi's peysa": ["Levi's peysa"],
}
STORE_NAMES = [
    "Elko", "Hagkaup", "Epal", "Boozt", "Salka", "Líf og list",
    "Vínbúðin", "IngaElín", "Joe Boxer", "Minigarðurinn",
]  # fmt: skip
STORE_ALIASES = {"vinbuð": "Vínbúðin", "internetið": "Netverslun"}
FROM_US = people.FROM_US
VALID_GROUPS = {value for value, _ in Group.choices}


_is_url = stores.is_url
_store_from_url = stores.store_from_url


def _parts(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def tidy(data: dict) -> dict:
    """`splitStoreLinks` + `tidyStores`: lagar eldri gögn á sama hátt og gamla appið."""
    gifts = [g for y in data["years"].values() for g in y["gifts"]]
    for g in gifts:
        if g.get("from"):
            for idea in g["ideas"]:
                idea.setdefault("from", g["from"])
            del g["from"]
        if "link" not in g:
            g["link"] = g.get("store", "") if _is_url(g.get("store")) else ""
            if g["link"]:
                g["store"] = _store_from_url(g["link"])
    for g in gifts:
        items = NOT_STORES.get(fold_key(g.get("store")))
        if not items:
            continue
        pick = g.get("bought") and not any(i.get("picked") for i in g["ideas"])
        for text in items:
            hit = next((i for i in g["ideas"] if fold_key(i["text"]) == fold_key(text)), None)
            if hit:
                hit["picked"] = hit.get("picked") or pick
            else:
                g["ideas"].append({"text": text, "picked": pick})
        g["store"] = ""
    # Algengasti rithátturinn vinnur nema búðin sé á listanum yfir rétt nöfn
    counts: dict[str, dict[str, int]] = {}
    for g in gifts:
        for name in _parts(g.get("store")) + [i["store"].strip() for i in g["ideas"] if i.get("store")]:
            counts.setdefault(fold_key(name), {}).setdefault(name, 0)
            counts[fold_key(name)][name] += 1
    canon = {fold_key(n): n for n in STORE_NAMES}
    for key, names in counts.items():
        canon.setdefault(key, STORE_ALIASES.get(key) or max(names.items(), key=lambda kv: kv[1])[0])
    canon.update(STORE_ALIASES)
    canon.update({fold_key(n): n for n in data.get("storeNames") or []})
    data["_canon"] = canon
    return data


@dataclass
class ImportReport:
    seasons: int = 0
    gifts: int = 0
    ideas: int = 0
    people: int = 0
    stores: int = 0
    merged_gifts: list[str] = field(default_factory=list)
    skipped_gifts: int = 0
    new_givers: list[str] = field(default_factory=list)


class LegacyImporter:
    def __init__(self, household: Household, data: dict):
        if data.get("version") != 2 or "years" not in data:
            raise ValueError("Aðeins v2-afrit úr gamla appinu eru studd")
        self.household = household
        self.data = tidy(data)
        self.canon: dict[str, str] = self.data["_canon"]
        self.report = ImportReport()
        self.people: dict[str, Person] = {}
        self._stores: dict[str, Store] = {}

    def store(self, name: str) -> Store | None:
        name = (name or "").strip()
        if not name:
            return None
        key = fold_key(name)
        if key not in self._stores:
            self._stores[key] = stores.get_or_create_store(self.household, self.canon.get(key, name))
        return self._stores[key]

    @transaction.atomic
    def run(self) -> ImportReport:
        self._import_people()
        for year, season_data in sorted(self.data["years"].items()):
            self._import_season(int(year), season_data)
        self._import_locations()
        self.report.stores = len(self._stores)
        self.report.new_givers = sorted(
            p.name for p in Person.objects.filter(household=self.household).exclude(gifts__isnull=False)
        )
        return self.report

    def _import_people(self):
        for row in self.data.get("people", []):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            person, created = Person.objects.get_or_create(
                household=self.household,
                key=normalize(name),
                defaults={
                    "name": name,
                    "group": row.get("group") if row.get("group") in VALID_GROUPS else Group.ANNAD,
                    "birthday": _date(row.get("birthday")),
                    "give_christmas": row.get("giveChristmas") is not False,
                    "give_birthday": bool(row.get("giveBirthday")),
                },
            )
            self.people[row["id"]] = person
            self.report.people += created

    def _import_season(self, year: int, season_data: dict):
        season, _ = Season.objects.get_or_create(
            household=self.household, year=year, defaults={"budget": season_data.get("budget") or 0}
        )
        self.report.seasons += 1
        for position, row in enumerate(season_data.get("gifts", [])):
            person = self.people.get(row.get("personId"))
            if person is None:
                self.report.skipped_gifts += 1  # ónefnd lína
                continue
            existing = Gift.objects.alive().christmas().filter(season=season, person=person).first()
            gift = Gift.objects.create(
                season=season,
                person=person,
                plan=row.get("plan"),
                bought=bool(row.get("bought")),
                link=row["link"] if _is_url(row.get("link")) and len(row["link"]) <= 500 else "",
                position=position,
                deleted_at=datetime.datetime.now(datetime.UTC) if existing else None,
            )
            self._import_ideas(gift, row)
            # Raunverð kom úr hugmyndunum ef einhver keypt (eigin) hugmynd hafði verð; annars úr g.price
            if (
                gift.bought
                and not gift.ideas.filter(picked=True, price__isnull=False, for_other=False).exists()
            ):
                gift.manual_price = row.get("price")
                gift.save(update_fields=["manual_price"])
            if existing:
                self._merge_duplicate(gift, existing)
            else:
                self.report.gifts += 1

    def _import_ideas(self, gift: Gift, row: dict):
        ideas = row.get("ideas") or []
        if not any(i.get("store") for i in ideas):
            gift.stores.set([s for s in (self.store(n) for n in _parts(row.get("store"))) if s])
        for position, item in enumerate(ideas):
            giver_name = (item.get("from") or "").strip()
            givers = [] if not giver_name or normalize(giver_name) in FROM_US else [giver_name]
            idea = Idea.objects.create(
                gift=gift,
                text=item["text"][:200],
                note=item.get("note") or "",
                store=self.store(item.get("store")),
                link=item["link"] if _is_url(item.get("link")) and len(item["link"]) <= 500 else "",
                price=item.get("price") or None,
                picked=bool(item.get("picked")),
                for_other=bool(item.get("forOther")) and bool(givers),
                position=position,
            )
            for name in givers:
                person = people.find_or_create(self.household, name)
                IdeaGiver.objects.create(
                    idea=idea, person=person, paid=bool(item.get("paid")) and idea.for_other
                )
            self.report.ideas += 1

    def _merge_duplicate(self, duplicate: Gift, gift: Gift):
        """Gamla appið leyfði tvær gjafir til sama einstaklings sama ár; þær sameinast.

        Skráð verð (án hugmyndaverðs) færist á hugmynd svo ekkert tapist í raunverði.
        """
        for g in (gift, duplicate):
            if g.bought and g.manual_price:
                target = g.ideas.filter(picked=True, price__isnull=True).first()
                if target is None:
                    target = Idea.objects.create(gift=g, text="(áður skráð verð)", picked=True)
                target.price, g.manual_price = g.manual_price, None
                target.save(update_fields=["price"])
                g.save(update_fields=["manual_price"])
        start = gift.ideas.count()
        for i, idea in enumerate(duplicate.ideas.all()):
            idea.gift, idea.position = gift, start + i
            idea.save(update_fields=["gift", "position"])
        gift.stores.add(*duplicate.stores.all())
        gift.plan = ((gift.plan or 0) + (duplicate.plan or 0)) or None
        gift.bought = gift.bought or duplicate.bought
        gift.save()
        duplicate.delete()
        self.report.merged_gifts.append(f"{gift.person.name} ({gift.season.year})")

    def _import_locations(self):
        for key, locs in (self.data.get("locations") or {}).items():
            store = self._stores.get(key) or Store.objects.filter(household=self.household, key=key).first()
            if store is None:
                continue
            names = split_list(locs) if isinstance(locs, str) else locs
            stores.set_locations(store, names)


def _date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


@transaction.atomic
def clear_household(household: Household) -> None:
    """Fyrir --replace: hreinsar öll gjafagögn heimilisins (aðild og notendur standa)."""
    Gift.objects.filter(season__household=household).delete()
    Season.objects.filter(household=household).delete()
    Person.objects.filter(household=household).delete()
    Store.objects.filter(household=household).delete()
    Location.objects.filter(household=household).delete()
