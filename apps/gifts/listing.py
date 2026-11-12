"""Það sem gjafalistinn sýnir: flokkar, línur, síur og yfirlit.

Samsvarar `listHtml`, `giftRow`, `renderSummary`, `renderHeader` og `treeSvg` í gamla
appinu. Hér er aðeins framsetning; reglurnar sjálfar eru í `services/`.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlencode

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from django.utils.translation import ngettext

from apps.core.money import format_kr
from apps.core.text import fold_key, is_sort_key
from apps.wishlists import services as wishlist_services

from .models import GROUP_ICONS, Gift, Group, Person, Season, Store
from .services.gifts import gift_text
from .services.pricing import actual_price, giver_breakdown
from .services.privacy import EVERYONE, Viewer
from .services.queries import season_gifts, with_details
from .services.stores import stores_of
from .services.summary import SeasonSummary, season_summary

# ---------- Síur og röðun (GET-færibreytur, svo hægt sé að deila slóð og nota bakkhnapp) ----------

FILTERS = {"allt": _l("Allur listinn"), "eftir": _l("Eftir að kaupa"), "keypt": _l("Klárað & keypt")}
SORTS = {
    "upprunaleg": _l("Upprunaleg röð"),
    "nafn": _l("Nafn"),
    "aaetlun": _l("Hæsta áætlun"),
    "stada": _l("Ókeypt fyrst"),
}
ALL_STORES = "*"
NO_STORE = "-"


@dataclass(frozen=True)
class ListState:
    filter: str = "allt"
    q: str = ""
    store: str = ALL_STORES  # fold_key búðar, ALL_STORES eða NO_STORE
    sort: str = "upprunaleg"

    @classmethod
    def from_params(cls, params) -> "ListState":
        f = params.get("syna", "allt")
        s = params.get("rod", "upprunaleg")
        return cls(
            filter=f if f in FILTERS else "allt",
            q=(params.get("leit") or "").strip()[:100],
            store=(params.get("bud") or ALL_STORES).strip()[:100],
            sort=s if s in SORTS else "upprunaleg",
        )

    @property
    def filtering(self) -> bool:
        return self.filter != "allt" or bool(self.q) or self.store != ALL_STORES

    def query(self, **changes) -> str:
        """Querystring fyrir þessa stöðu (sjálfgefin gildi sleppt), t.d. fyrir flipa síunnar."""
        values = {"syna": self.filter, "leit": self.q, "bud": self.store, "rod": self.sort, **changes}
        defaults = {"syna": "allt", "leit": "", "bud": ALL_STORES, "rod": "upprunaleg"}
        kept = {k: v for k, v in values.items() if v != defaults[k]}
        return "?" + urlencode(kept) if kept else ""


# ---------- Línur ----------


@dataclass
class Row:
    gift: Gift
    stores: list[Store]
    history: list[tuple[int, str]]
    price: int | None
    breakdown: list[tuple[Person | None, int]] | None
    # Gjöf handa þeim sem skoðar: aðeins nafn og óskir hans sjálfs birtast (services/privacy.py)
    secret: bool = False
    # Nafnið sem sá sem skoðar sér (hans eigið nafn á hans eigin línu)
    name: str = ""
    # Hugmyndir af óskalista einstaklings í öðru heimili sem hann fylgir (Person.source); teljast
    # ekki með fyrr en þær eru teknar (verða þá hugmyndir hér, sjá wishlists/services.claim)
    feed: list = field(default_factory=list)

    @property
    def feed_from(self) -> str:
        """Heimilið sem óskalistinn kemur frá, t.d. „Laugavegur 4“."""
        source = self.gift.person.source
        return source.household.name if source else ""

    @property
    def person(self) -> Person:
        return self.gift.person

    @property
    def wishes(self):
        return [i for i in self.gift.ideas.all() if i.wish]

    @property
    def gift_stores(self) -> list[Store]:
        """Búðir sem eiga ekki heima á neinni hugmynd (búð á gjöfinni sjálfri, eldri gögn).

        Búð hugmyndar birtist í línu hugmyndarinnar; þessar birtast neðst.
        """
        if any(i.store_id for i in self.gift.ideas.all()):
            return []
        return self.stores

    @property
    def over_plan(self) -> int | None:
        plan, price = self.gift.plan, self.price
        if price is None or plan is None or price <= plan:
            return None
        return price - plan

    @property
    def breakdown_total(self) -> int:
        return self.price if self.price is not None else sum(n for _, n in self.breakdown or [])

    @property
    def history_line(self) -> str:
        return " · ".join(f"{y}: {t}" for y, t in self.history[:2])

    @property
    def history_title(self) -> str:
        return "\n".join(f"{y}: {t}" for y, t in self.history)


def _row(gift: Gift, histories: dict[int, list], viewer: Viewer = EVERYONE, feeds=None) -> Row:
    name = viewer.display_name(gift.person)
    if viewer.is_secret(gift):
        return Row(gift, [], [], None, None, secret=True, name=name)
    if feeds is None:
        feeds = wishlist_services.gift_feeds([gift])
    feed = feeds.get(gift.pk, [])
    return Row(
        gift=gift,
        stores=stores_of(gift),
        history=histories.get(gift.person_id, []),
        price=actual_price(gift),
        breakdown=giver_breakdown(gift),
        name=name,
        feed=feed,
    )


def histories(season: Season, person_ids, viewer: Viewer = EVERYONE) -> dict[int, list[tuple[int, str]]]:
    """Fyrri gjafir hvers einstaklings (nýjasta fyrst), sóttar í einu lagi fyrir allan listann."""
    gifts = with_details(
        Gift.objects.alive()
        .christmas()
        .filter(
            season__household_id=season.household_id, season__year__lt=season.year, person_id__in=person_ids
        )
    ).order_by("-season__year")
    out: dict[int, list] = defaultdict(list)
    for gift in viewer.visible(gifts):
        text = gift_text(gift) or ", ".join(s.name for s in stores_of(gift)) or "—"
        out[gift.person_id].append((gift.season.year, text))
    return out


def histories_bought(household, person_ids, viewer: Viewer = EVERYONE) -> dict[int, list[tuple[int, str]]]:
    """Keyptar gjafir hvers einstaklings öll ár (nýjasta fyrst), fyrir „Fólk“."""
    gifts = with_details(
        Gift.objects.alive()
        .christmas()
        .filter(season__household=household, person_id__in=person_ids, bought=True)
    ).order_by("-season__year")
    out: dict[int, list] = defaultdict(list)
    for gift in viewer.visible(gifts):
        out[gift.person_id].append((gift.season.year, gift_text(gift) or "—"))
    return out


def build_row(gift: Gift, viewer: Viewer = EVERYONE) -> Row:
    gift = with_details(Gift.objects.filter(pk=gift.pk)).get()
    return _row(gift, histories(gift.season, [gift.person_id], viewer), viewer)


def matches(row: Row, state: ListState) -> bool:
    gift = row.gift
    if row.secret:
        # Staðan er leynd: línan birtist aðeins á öllum listanum, og leit nær bara í nafn og óskir
        if state.filter != "allt" or state.store != ALL_STORES:
            return False
        q = fold_key(state.q)
        return not q or any(q in fold_key(v) for v in [row.name, *(i.text for i in row.wishes)])
    if state.filter == "eftir" and gift.bought or state.filter == "keypt" and not gift.bought:
        return False
    if state.store == NO_STORE and row.stores:
        return False
    if state.store not in (ALL_STORES, NO_STORE) and not any(s.key == state.store for s in row.stores):
        return False
    if state.q:
        # fold_key: „elko“ finnur Elkó og „asdis“ finnur Ásdísi
        q = fold_key(state.q)
        values = [gift.person.name, *(s.name for s in row.stores)]
        for idea in gift.ideas.all():
            values.append(idea.text)
            values.extend(link.person.name for link in idea.giver_links.all())
        if not any(q in fold_key(v) for v in values):
            return False
    return True


# Leynd lína raðast eins og hún væri án áætlunar og ókeypt, svo röðin segi ekkert um hana
_SORT_KEYS = {
    "nafn": lambda r: is_sort_key(r.name or r.person.name),
    "aaetlun": lambda r: -(0 if r.secret else r.gift.plan or 0),
    "stada": lambda r: not r.secret and r.gift.bought,
}


# ---------- Flokkar ----------

# Flokkurinn „Ég“ efst: lína þess sem skoðar (hjá öðrum er hún í sínum venjulega flokki)
MINE = "eg"


@dataclass
class Section:
    group: str
    label: str
    icon: str
    rows: list[Row]  # þær sem passa við síuna
    count: int
    done: int
    plan: int
    spent: int

    @property
    def dom_id(self) -> str:
        return f"group-{self.group}"

    @property
    def mine(self) -> bool:
        return self.group == MINE


def _section(group: str, label: str, rows: list[Row], shown: list[Row]) -> Section:
    return Section(
        group=group,
        label=label,
        icon=GROUP_ICONS[group],
        rows=shown,
        count=len(rows),
        done=sum(r.gift.bought for r in rows),
        plan=sum(r.gift.plan or 0 for r in rows),
        spent=sum(r.price or 0 for r in rows),
    )


@dataclass
class GiftList:
    season: Season
    state: ListState
    locked: bool
    summary: SeasonSummary
    sections: list[Section]
    store_options: list[tuple[str, str]]  # (gildi, nafn)
    has_undecided: bool
    counts: dict[str, int] = field(default_factory=dict)

    def section(self, group: str) -> Section | None:
        return next((s for s in self.sections if s.group == group), None)

    def find(self, gift: Gift) -> tuple[Section | None, Row | None]:
        """Flokkurinn og línan sem gjöfin birtist í (línan None ef hún passar ekki við síuna)."""
        for s in self.sections:
            for r in s.rows:
                if r.gift.pk == gift.pk:
                    return s, r
        return self.section(gift.person.group), None


def build_list(
    season: Season, state: ListState, *, locked: bool | None = None, viewer: Viewer = EVERYONE
) -> GiftList:
    all_gifts = season_gifts(season)
    gifts = viewer.visible(all_gifts)
    locked = season.is_locked() if locked is None else locked
    hist = histories(season, {g.person_id for g in all_gifts}, viewer)
    feeds = wishlist_services.gift_feeds(all_gifts)  # óskalistar annarra heimila, í einu lagi
    every_row = [_row(g, hist, viewer, feeds) for g in all_gifts]
    rows = [r for r in every_row if not r.secret]

    stores: dict[str, str] = {}
    for r in rows:
        for s in r.stores:
            stores.setdefault(s.key, s.name)
    if state.store not in (ALL_STORES, NO_STORE) and state.store not in stores:
        state = ListState(state.filter, state.q, ALL_STORES, state.sort)

    sections = []
    mine = [r for r in every_row if r.secret and matches(r, state)]
    if mine:
        sections.append(Section(MINE, _("Ég"), "🙋", mine, 0, 0, 0, 0))
    for value, label in Group.choices:
        in_group = [r for r in rows if r.gift.person.group == value]
        shown = [r for r in in_group if matches(r, state)]
        if state.sort in _SORT_KEYS:
            shown.sort(key=_SORT_KEYS[state.sort])
        if state.filtering and not shown:
            continue
        if not in_group and (locked or value == Group.ANNAD):
            continue
        sections.append(_section(value, label, in_group, shown))

    done = sum(r.gift.bought for r in rows)
    return GiftList(
        season=season,
        state=state,
        locked=locked,
        summary=season_summary(season, gifts),
        sections=sections,
        store_options=sorted(stores.items(), key=lambda kv: is_sort_key(kv[1])),
        has_undecided=any(not r.stores for r in rows),
        counts={"allt": len(rows), "eftir": len(rows) - done, "keypt": done},
    )


def section_for(season: Season, group: str, state: ListState, viewer: Viewer = EVERYONE) -> Section | None:
    """Einn flokkur (fyrir OOB-uppfærslu á haus flokksins eftir breytingu í línu)."""
    return build_list(season, state, viewer=viewer).section(group)


# ---------- Hetjuhluti og yfirlit ----------


# Íslensku jólasveinarnir í komuröð: sá fyrsti aðfaranótt 12. desember, sá síðasti aðfaranótt aðfangadags
# (nafn, það sem hann er þekktur fyrir)
YULE_LADS = [
    ("Stekkjarstaur", _l("passið kindurnar!")),
    ("Giljagaur", _l("verjið mjólkurfroðuna!")),
    ("Stúfur", _l("hann er að leita að pönnunni")),
    ("Þvörusleikir", _l("felið sleifarnar!")),
    ("Pottaskefill", _l("skiljið eftir smá í pottinum")),
    ("Askasleikir", _l("kíkið undir rúmið!")),
    ("Hurðaskellir", _l("það verður lítið sofið")),
    ("Skyrgámur", _l("felið skyrið!")),
    ("Bjúgnakrækir", _l("felið bjúgun!")),
    ("Gluggagægir", _l("dragið fyrir gluggana!")),
    ("Gáttaþefur", _l("laufabrauðið ilmar")),
    ("Ketkrókur", _l("passið hangikjötið!")),
    ("Kertasníkir", _l("geymið kertin vel")),
]
FIRST_LAD_DAY = 12  # desember


def yule_lad_text(today: datetime.date) -> str:
    """Niðurtalning þar til jólasveinarnir koma til byggða, svo hver kemur næst.

    Sveinn sem kemur „í nótt“ er sá sem er kominn að morgni næsta dags.
    """
    first = datetime.date(today.year, 12, FIRST_LAD_DAY)
    christmas = datetime.date(today.year, 12, 24)
    if today > christmas:
        return _("Jólin eru liðin")
    if today == christmas:
        return _("Kertasníkir kom í nótt – gleðileg jól")
    tomorrow = today + datetime.timedelta(days=1)
    if tomorrow < first:
        n = (first - today).days
        return ngettext(
            "%(name)s kemur til byggða eftir %(n)s dag",
            "%(name)s kemur til byggða eftir %(n)s daga",
            n,
        ) % {"name": YULE_LADS[0][0], "n": n}
    index = (tomorrow - first).days
    name, quip = YULE_LADS[index]
    return _("Í nótt kemur %(name)s (%(i)s. af 13) – %(quip)s") % {"name": name, "i": index + 1, "quip": quip}


def hero_texts(season: Season, days: int) -> tuple[str, str, str]:
    """(merki, feitletrað, framhald) eftir því hve langt er til jóla."""
    if days >= 0:
        pill = yule_lad_text(datetime.date(season.year, 12, 24) - datetime.timedelta(days=days))
    else:
        pill = _("Jólin eru liðin")
    if days > 1:
        return (
            pill,
            _("Bara %(n)s dagar til jóla") % {"n": days},
            _("höldum góðu yfirliti yfir alla pakkana og gleðina!"),
        )
    if days == 1:
        return pill, _("Jólin koma á morgun!"), _("nú er bara að pakka inn")
    if days == 0:
        return pill, _("Gleðileg jól!"), _("njóttu dagsins")
    return pill, _("Jólin %(year)s") % {"year": season.year}, _("yfirlit yfir gjafirnar það árið")


def _dec(n: float) -> str:
    return f"{n:.1f}".removesuffix(".0").replace(".", ",")


def pace_text(summary: SeasonSummary) -> str | None:
    """„~2 gjafir á dag“ eða „~1 gjöf á 3,5 daga“."""
    if not summary.todo or summary.days_left <= 0:
        return None
    if summary.days_left / summary.todo >= 1:
        return _("~1 gjöf á %(n)s daga") % {"n": _dec(summary.days_left / summary.todo)}
    return _("~%(n)s gjafir á dag") % {"n": _dec(summary.todo / summary.days_left)}


def dash_note(summary: SeasonSummary) -> str:
    if not summary.count:
        return _("Engar gjafir enn – byrjaðu á að bæta við þeirri fyrstu.")
    if not summary.todo:
        return _("Allt klárt – nú er bara að pakka inn! 🎉")
    return ngettext(
        "%(n)s gjöf ókláruð, áætlað %(kr)s í hana.",
        "%(n)s gjafir ókláraðar, áætlað %(kr)s í þær.",
        summary.todo,
    ) % {"n": summary.todo, "kr": format_kr(summary.planned_left)}


GROUP_SHORT = {Group.VINNA: _l("Vinna")}

# Kúlur á jólatrénu: (x, y, litur)
ORNAMENTS = [
    (100, 95, "#8b1e2b"), (110, 120, "#f0bd8b"), (80, 145, "#ffb3ac"), (120, 150, "#8b1e2b"),
    (90, 180, "#f0bd8b"), (135, 185, "#ffdad9"), (65, 200, "#8b1e2b"), (110, 205, "#ffdcbd"),
    (50, 223, "#ffb3ac"), (75, 220, "#8b1e2b"), (100, 230, "#ffdad9"), (125, 218, "#f0bd8b"),
    (150, 222, "#ffdcbd"),
]  # fmt: skip


@dataclass(frozen=True)
class Tree:
    progress: float

    @property
    def fill_y(self) -> float:
        top, bottom = 35, 245
        return round(bottom - (bottom - top) * self.progress, 2)

    @property
    def fill_height(self) -> float:
        return round(245 - self.fill_y + 5, 2)

    @property
    def ornaments(self) -> list[tuple[int, int, str, bool]]:
        return [(x, y, c, y >= self.fill_y) for x, y, c in ORNAMENTS]

    @property
    def lit(self) -> bool:
        return self.progress >= 1

    @property
    def line(self) -> bool:
        return 0 < self.progress < 1
