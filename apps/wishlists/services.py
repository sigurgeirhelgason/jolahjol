"""Óskalistar: opinn hlekkur á hugmyndir eins einstaklings (eða alls heimilisfólksins), og
frátekning án innskráningar.

Opna síðan sýnir aðeins hugmyndir einstaklingsins á yfirstandandi ári. Hvorki nöfn annarra,
upphæðir sem hafa verið greiddar, rukkun né hver tók frá birtast þar.
"""

import datetime
import secrets
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy

from apps.core.text import normalize
from apps.gifts.models import Family, Gift, Group, Idea, IdeaGiver, Person, Season
from apps.gifts.services.privacy import is_linked
from apps.households.models import Household

from .models import HouseholdShare, WishlistShare, WishRequest


class WishlistError(Exception):
    """Aðgerð sem ekki gengur upp; skilaboðin eru birt á opnu síðunni."""


def current_season(household: Household) -> Season | None:
    """Ár þessa árs ef það er til, annars nýjasta árið (sama regla og gjafalistinn)."""
    seasons = household.seasons.all()
    return seasons.filter(year=timezone.localdate().year).first() or seasons.order_by("-year").first()


def active_share(person: Person) -> WishlistShare | None:
    return person.wishlist_shares.filter(revoked_at__isnull=True).order_by("-created_at").first()


def get_active(token: str) -> WishlistShare | None:
    return (
        WishlistShare.objects.select_related("person__household")
        .filter(token=token, revoked_at__isnull=True)
        .first()
    )


@transaction.atomic
def create_share(person: Person, by) -> WishlistShare:
    """Nýr hlekkur; eldri hlekkir einstaklingsins hætta að virka."""
    person.wishlist_shares.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
    return WishlistShare.objects.create(person=person, created_by=by)


def revoke(person: Person) -> None:
    person.wishlist_shares.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())


def visible_ideas(share: WishlistShare) -> tuple[Season | None, list[Idea]]:
    return person_ideas(share.person)


def person_ideas(person: Person) -> tuple[Season | None, list[Idea]]:
    """Hugmyndir einstaklingsins á yfirstandandi ári, í röð listans.

    Sé einstaklingurinn notandi í heimilinu birtast aðeins óskirnar sem hann skráði sjálfur:
    hann gæti opnað hlekkinn sjálfur (services/privacy.py).
    """
    season = current_season(person.household)
    if season is None:
        return None, []
    gift = Gift.objects.alive().christmas().filter(season=season, person=person).first()
    if gift is None:
        return season, []
    ideas = gift.ideas.visible().select_related("store").order_by("position", "id")
    if is_linked(person):
        ideas = ideas.filter(wish=True)
    return season, list(ideas)


def share_people(share: "WishlistShare | HouseholdShare") -> list[Person]:
    """Fólkið sem hlekkurinn sýnir: einn einstaklingur, eða heimilisfólkið."""
    if isinstance(share, HouseholdShare):
        return home_people(share.household)
    return [share.person]


def is_taken(idea: Idea) -> bool:
    """Frátekið eða keypt: opna síðan sýnir bara „Frátekið“, ekki hver eða hvers vegna."""
    return idea.picked or idea.reserved


@dataclass(frozen=True)
class Reservation:
    """Það sem tæki þess sem tók frá geymir (undirritað cookie) til að geta hætt við."""

    idea_id: int
    secret: str
    added_giver: bool  # var gefandinn búinn til við frátekningu (þá fjarlægður ef hætt er við)


def _reserve_as(idea: Idea, name: str) -> bool:
    """Merkir (læsta) hugmynd frátekna í nafni `name`, sem verður gefandi í heimili hennar.

    Nafnið er borið saman við fólk heimilisins, svo „amma jóa“ verði Amma Jóa; annars nýr gefandi.
    Skilar því hvort gefandinn var settur á hugmyndina núna.
    """
    household = idea.gift.season.household
    person = Person.objects.filter(household=household, key=normalize(name)).first()
    if person is None:
        person = Person.objects.create(household=household, name=name, group=Group.ANNAD)
    _link, added = IdeaGiver.objects.get_or_create(idea=idea, person=person)
    idea.reserved = True
    idea.reserved_by = person
    idea.reserved_at = timezone.now()
    idea.reservation_secret = secrets.token_urlsafe(24)
    idea.save(update_fields=["reserved", "reserved_by", "reserved_at", "reservation_secret"])
    return added


@transaction.atomic
def reserve(share: "WishlistShare | HouseholdShare", idea_id: int, name: str) -> Reservation:
    name = name.strip()[:100]
    if not normalize(name):
        raise WishlistError("Skrifaðu nafnið þitt svo fjölskyldan viti hver tók frá.")
    idea = _idea_for_share(share, idea_id, lock=True)
    if is_taken(idea):
        raise WishlistError("Einhver var á undan þér og hefur þegar tekið þetta frá.")
    added = _reserve_as(idea, name)
    return Reservation(idea.pk, idea.reservation_secret, added)


@transaction.atomic
def cancel(share: "WishlistShare | HouseholdShare", reservation: Reservation) -> None:
    """Hætt við frá sama tæki. Aðeins ef leyndarmálið passar (annars gerist ekkert)."""
    idea = _idea_for_share(share, reservation.idea_id, lock=True)
    if not idea.reservation_secret or not secrets.compare_digest(idea.reservation_secret, reservation.secret):
        raise WishlistError("Þessi frátekning er ekki lengur til.")
    if reservation.added_giver and idea.reserved_by_id:
        IdeaGiver.objects.filter(idea=idea, person_id=idea.reserved_by_id).delete()
    clear_reservation(idea)


def clear_reservation(idea: Idea) -> None:
    """Heimilið fjarlægir frátekningu (gefandinn helst á hugmyndinni)."""
    idea.reserved = False
    idea.reserved_by = None
    idea.reserved_at = None
    idea.reservation_secret = ""
    idea.save(update_fields=["reserved", "reserved_by", "reserved_at", "reservation_secret"])


def _idea_for_share(share: "WishlistShare | HouseholdShare", idea_id: int, *, lock=False) -> Idea:
    """Hugmynd sem tilheyrir fólki hlekksins á yfirstandandi ári; annars WishlistError."""
    ids = {i.pk for person in share_people(share) for i in person_ideas(person)[1]}
    if idea_id not in ids:
        raise WishlistError("Þessi hugmynd er ekki á listanum lengur.")
    qs = Idea.objects.select_for_update() if lock else Idea.objects
    return qs.get(pk=idea_id)


# ---------- Fylgja óskalista úr öðru heimili ----------
#
# Dísa frænka fær hlekkinn á óskalista Siggu frá Jóa og Önnu og bætir Siggu á sitt eigið Jólahjól.
# Einstaklingurinn hjá Dísu fær `source` = Sigga hjá Jóa og Önnu. Þá birtast hugmyndir þeirra á
# línu Siggu hjá Dísu (sama jólaár) á meðan þær eru hvorki keyptar né fráteknar og Sigga á virkan
# hlekk. Hugmyndir Dísu sjást aldrei hjá Jóa og Önnu. Taki Dísa hugmynd (keypt eða frátekið) verður
# hún frátekin hjá Jóa og Önnu í nafni Dísu og afrit verður til hjá Dísu (`Idea.source`).


def source_share(person: Person) -> WishlistShare | None:
    """Virkur hlekkur uppsprettunnar sem `person` fylgir (None ef engin eða hlekknum var lokað)."""
    return active_share(person.source) if person.source_id else None


def shared_people(person_ids) -> tuple[set[int], set[int]]:
    """(eigin hlekkur, hlekkur heimilisins): þeir af `person_ids` sem eiga virkan eigin óskalista,
    og þeir sem eru í flokki heimilisins þegar heimilið á virkan hlekk á óskalista heimilisins.

    Hlekkur heimilisins gildir aðeins fyrir þá sem fylgja í gegnum heimilið (Person.family_follow):
    loki Dísa eigin hlekk Sigga hættir Gunna, sem fylgdi honum ein og sér, að sjá hugmyndirnar.
    """
    own = WishlistShare.objects.filter(person_id__in=person_ids, revoked_at__isnull=True)
    home = _home(Person.objects.filter(pk__in=person_ids)).filter(
        household__wishlist_shares__revoked_at__isnull=True
    )
    return set(own.values_list("person_id", flat=True)), set(home.values_list("pk", flat=True))


def gift_feeds(gifts) -> dict[int, list[Idea]]:
    """Hugmyndir af óskalistum sem birtast á línum `gifts`: {gift_id: [hugmyndir]}.

    Aðeins jólagjafir einstaklinga sem fylgja óskalista (Person.source), sama jólaár og
    óskalistinn sýnir, það sem opna síðan sýnir (óskir einar ef uppsprettan er sjálf notandi),
    hvorki keypt né frátekið, og ekki það sem gjöfin hefur þegar tekið (afrit með `source`).
    Allt sótt í einu lagi fyrir listann: fáeinar fyrirspurnir, óháð fjölda lína.
    """
    from apps.households.models import Membership

    wanted = [g for g in gifts if g.person.source_id and g.occasion == "jol"]
    if not wanted:
        return {}
    own_shared, home_shared = shared_people({g.person.source_id for g in wanted})
    sources = {p.pk: p for p in Person.objects.filter(pk__in=own_shared | home_shared)}
    # Ár hvers heimilis eftir sömu reglu og current_season: þetta ár ef það er til, annars nýjasta
    this_year = timezone.localdate().year
    current: dict[int, Season] = {}
    for season in Season.objects.filter(household_id__in={p.household_id for p in sources.values()}):
        best = current.get(season.household_id)
        if best is None or (best.year != this_year and (season.year == this_year or season.year > best.year)):
            current[season.household_id] = season
    source_gifts = {
        g.person_id: g
        for g in Gift.objects.alive().christmas().filter(person_id__in=sources, season__in=current.values())
    }
    ideas: dict[int, list[Idea]] = {}
    for idea in (
        Idea.objects.visible()
        .filter(gift__in=source_gifts.values())
        .select_related("store")
        .order_by("position", "id")
    ):
        ideas.setdefault(idea.gift_id, []).append(idea)
    linked = set(Membership.objects.filter(person_id__in=sources).values_list("person_id", flat=True))

    out: dict[int, list[Idea]] = {}
    for gift in wanted:
        source_id = gift.person.source_id
        allowed = source_id in own_shared or (gift.person.family_follow and source_id in home_shared)
        source = sources.get(source_id) if allowed else None
        source_gift = source_gifts.get(source.pk) if source else None
        if source_gift is None or current[source.household_id].year != gift.season.year:
            out[gift.pk] = []
            continue
        taken = {i.source_id for i in gift.ideas.all() if i.source_id}
        out[gift.pk] = [
            i
            for i in ideas.get(source_gift.pk, [])
            if not is_taken(i) and i.pk not in taken and (i.wish or source.pk not in linked)
        ]
    return out


def feed_idea(gift: Gift, idea_id: int) -> Idea | None:
    """Hugmynd `idea_id` ef hún er á línu `gift` núna (ekki tekin), annars None."""
    return next((i for i in gift_feeds([gift]).get(gift.pk, []) if i.pk == idea_id), None)


@transaction.atomic
def follow(share: WishlistShare, household: Household, *, person=None, name="", group=Group.ANNAD) -> Person:
    """Dísa bætir Siggu á sitt Jólahjól: ný manneskja (`name`, `group`) eða einhver sem er til.

    Hver óskalisti tengist mest einum einstaklingi í hverju heimili. Uppsprettan er læst svo
    tvísending (eða tveir flipar) geti ekki tengt hann tvisvar.
    """
    from apps.gifts.services.gifts import ensure_christmas_gift
    from apps.gifts.services.people import find_or_create

    source = Person.objects.select_for_update().select_related("household").get(pk=share.person_id)
    if household.pk == source.household_id:
        raise WishlistError("Þessi einstaklingur er nú þegar á þessum lista.")
    already = Person.objects.filter(household=household, source=source).first()
    if person is None:
        name = name.strip()[:100]
        if not normalize(name):
            raise WishlistError("Skrifaðu nafnið sem á að birtast á listanum þínum.")
        if already is None:
            # Ekki „Heimilið“: þar er heimilisfólkið sjálft, ekki einhver úr öðru heimili
            valid = group in Group.values and group != Group.HEIMILI
            person = find_or_create(household, name, group if valid else Group.ANNAD)
    elif person.household_id != household.pk:
        raise WishlistError("Þessi einstaklingur er ekki á listanum þínum.")
    if already is not None and (person is None or person.pk != already.pk):
        raise WishlistError(f"„{already.name}“ á listanum þínum fylgir nú þegar þessum óskalista.")
    if person.source_id and person.source_id != source.pk:
        raise WishlistError(f"„{person.name}“ fylgir nú þegar öðrum óskalista.")
    person.source = source
    person.save(update_fields=["source"])
    season = current_season(source.household)
    if person.give_christmas and season is not None:
        ensure_christmas_gift(person, season.year)
    return person


def unfollow(person: Person) -> None:
    """„Hætta að fylgja“. Hugmyndir sem voru teknar (afrit) haldast.

    Í heimili sem er fylgt fer hann úr flokki þess (í sinn fyrri flokk) og bætist ekki aftur við.
    """
    person.source = None
    person.family = None
    person.family_follow = False
    person.save(update_fields=["source", "family", "family_follow"])


def following(user, source: Person) -> list[Person]:
    """Einstaklingar í heimilum notandans sem fylgja `source` nú þegar."""
    return list(
        Person.objects.filter(source=source, household__memberships__user=user).select_related("household")
    )


def member_names(household: Household) -> list[str]:
    """Nöfn notenda heimilis, í þeirri röð sem þeir bættust við.

    Aðeins skráð nöfn (notandans, eða einstaklingsins sem hann er tengdur): netfang birtist
    aldrei, því nöfnin sjást á opnu síðunni og í öðrum heimilum.
    """
    from apps.households.models import Membership

    names: list[str] = []
    for m in Membership.objects.filter(household=household).select_related("user", "person").order_by("pk"):
        name = (m.user.name or "").strip() or (m.person.name if m.person else "")
        if name and name not in names:
            names.append(name)
    return names


def follower_names(person: Person) -> list[str]:
    """„Á lista hjá: Dísa, Gunna“: notendur í heimilum sem fylgja óskalista `person`
    (nafn heimilisins ef enginn þar hefur skráð nafn)."""
    names: set[str] = set()
    for household in Household.objects.filter(people__source=person).distinct():
        names.update(member_names(household) or [household.name])
    return sorted(names)


def claimer_name(user, household: Household) -> str:
    """Nafnið sem frátekning af óskalista fær hjá hinu heimilinu: nafn notandans, annars
    einstaklingsins sem hann er í heimilinu, annars nafn heimilisins (aldrei netfang)."""
    from apps.households.models import Membership

    if (user.name or "").strip():
        return user.name.strip()
    membership = Membership.objects.filter(user=user, household=household).select_related("person").first()
    if membership and membership.person:
        return membership.person.name
    return household.name


def _claim_giver_name(idea: Idea, name: str, claimer_household: Household) -> str:
    """Rekst nafnið á heimilisfólk uppsprettunnar eða viðtakandann sjálfan (t.d. heitir Dísa
    líka Anna) bætist heimili hennar við, svo frátekningin lendi ekki á röngum einstaklingi."""
    from apps.households.models import Membership

    clash = Person.objects.filter(household=idea.gift.season.household, key=normalize(name)).first()
    if clash and (clash.pk == idea.gift.person_id or Membership.objects.filter(person=clash).exists()):
        return f"{name} ({claimer_household.name})"[:100]
    return name


@transaction.atomic
def claim(gift: Gift, idea_id: int, name: str) -> Idea:
    """Dísa tekur hugmynd af óskalistanum: frátekin hjá Jóa og Önnu í nafni Dísu (aldrei keypt þar)
    og afrit verður til hjá Dísu, frátekið. Skilar afritinu; keypt-flæðið tekur svo við ef þarf."""
    from apps.gifts.services import stores

    if feed_idea(gift, idea_id) is None:
        raise WishlistError("Einhver var á undan þér, eða hugmyndin er ekki lengur á óskalistanum.")
    # Aðeins hugmyndin sjálf læst (búðin er valfrjáls tenging og má ekki læsa)
    idea = (
        Idea.objects.select_for_update(of=("self",))
        .select_related("gift__season__household", "store")
        .get(pk=idea_id)
    )
    if is_taken(idea):
        raise WishlistError("Einhver var á undan þér og hefur þegar tekið þetta frá.")
    mine = gift.season.household
    added = _reserve_as(idea, _claim_giver_name(idea, name.strip()[:100] or mine.name, mine))
    store = stores.get_or_create_store(mine, idea.store.name) if idea.store else None
    return Idea.objects.create(
        gift=gift,
        text=idea.text,
        note=idea.note,
        link=idea.link,
        store=store,
        price=idea.price,
        position=gift.ideas.count(),
        source=idea,
        source_added_giver=added,
        reserved=True,
        reserved_at=timezone.now(),
        # Sama leyndarmál og á upprunanum: þannig veit afritið hvort frátekningin er enn hennar
        reservation_secret=idea.reservation_secret,
    )


def release(copy: Idea) -> None:
    """Afrit tekið af eða eytt: frátekningin á upprunanum fellur niður ef hún er enn þess sem tók
    hana (sama leyndarmál) og hugmyndin hefur ekki verið keypt þar. Gefandinn fer aðeins af ef
    takan bjó hann til (ekki t.d. ef hann var þar fyrir í púkki)."""
    if not copy.source_id or not copy.reservation_secret:
        return
    idea = Idea.objects.select_for_update().filter(pk=copy.source_id).first()
    if idea is None or idea.picked or idea.reservation_secret != copy.reservation_secret:
        return
    if copy.source_added_giver and idea.reserved_by_id:
        IdeaGiver.objects.filter(idea=idea, person_id=idea.reserved_by_id).delete()
    clear_reservation(idea)


def release_copies(ideas) -> None:
    """Á undan fjöldaeyðingu (heimili, ár): losar frátekningar afrita svo þær sitji ekki eftir."""
    for copy in ideas.filter(source__isnull=False).exclude(reservation_secret=""):
        release(copy)


# ---------- Óskabeiðni: einstaklingurinn skrifar sjálfur óskirnar sínar ----------
#
# Jói og Anna vilja vita hvað Dísa frænka vill. Þau búa til hlekk í glugga Dísu, velja hvað hann
# lifir lengi og senda henni. Dísa skrifar óskirnar sínar á jólagjöf sína á lista Jóa og Önnu
# (`Idea.wish`) án innskráningar. Hún sér aðeins óskirnar sínar, aldrei hvort þær hafa verið
# keyptar eða teknar frá, og ekkert annað af listanum (sama regla og services/privacy.py).

# Hvað hlekkurinn lifir: {gildi: (dagar, heiti)}; „jol“ er fram yfir aðfangadag
LIFETIMES = {
    "1": (1, gettext_lazy("Virkar í 1 dag")),
    "3": (3, gettext_lazy("Virkar í 3 daga")),
    "7": (7, gettext_lazy("Virkar í 1 viku")),
    "14": (14, gettext_lazy("Virkar í 2 vikur")),
    "30": (30, gettext_lazy("Virkar í 1 mánuð")),
    "jol": (None, gettext_lazy("Virkar fram að jólum")),
}
DEFAULT_LIFETIME = "7"


def christmas_year(now=None) -> int:
    """Næstu jól: þetta ár til og með aðfangadegi, annars næsta ár."""
    today = timezone.localdate(now)
    return today.year if today <= datetime.date(today.year, 12, 24) else today.year + 1


def expiry(lifetime: str, now=None):
    """Hvenær hlekkur með `lifetime` (lykill í LIFETIMES) hættir að virka.

    „Fram að jólum“: til loka aðfangadags (næstu jól ef þau eru liðin í ár).
    """
    now = now or timezone.now()
    days, _label = LIFETIMES.get(lifetime, LIFETIMES[DEFAULT_LIFETIME])
    if days is not None:
        return now + datetime.timedelta(days=days)
    end = datetime.datetime.combine(datetime.date(christmas_year(now), 12, 25), datetime.time.min)
    return timezone.make_aware(end)


def _live_requests(now=None):
    now = now or timezone.now()
    return WishRequest.objects.filter(revoked_at__isnull=True, expires_at__gt=now)


def active_request(person: Person) -> WishRequest | None:
    """Nýjasti óútrunni hlekkurinn. `closed`: virkar ekki á meðan gjöfin í ár er eydd."""
    request = _live_requests().filter(person=person).order_by("-created_at").first()
    if request is not None:
        request.closed = _gift_deleted(person)
    return request


def _gift_deleted(person: Person) -> bool:
    """Heimilið eyddi jólagjöf einstaklingsins fyrir næstu jól og bjó ekki til aðra."""
    gifts = Gift.objects.christmas().filter(person=person, season__year=christmas_year())
    return gifts.filter(deleted_at__isnull=False).exists() and not gifts.alive().exists()


def get_request(token: str) -> WishRequest | None:
    """Virkur hlekkur. Einstaklingur sem er orðinn notandi í heimilinu skráir sjálfur í appinu,
    svo eldri hlekkur hans hættir að virka (glugginn sýnir hann ekki lengur til að loka).

    Hafi heimilið eytt jólagjöf hans (og ekki búið til aðra) hættir hlekkurinn líka að virka:
    annars yrði ný gjöf til og „Afturkalla“ á þeirri eyddu virkaði ekki.
    """
    request = (
        _live_requests()
        .select_related("person__household")
        .filter(token=token, person__memberships__isnull=True)
        .first()
    )
    if request is None or _gift_deleted(request.person):
        return None
    return request


@transaction.atomic
def create_request(person: Person, by, lifetime: str) -> WishRequest:
    """Nýr hlekkur; eldri hlekkir einstaklingsins hætta að virka."""
    revoke_request(person)
    return WishRequest.objects.create(person=person, created_by=by, expires_at=expiry(lifetime))


def revoke_request(person: Person) -> None:
    person.wish_requests.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())


def _request_gift(request: WishRequest) -> Gift | None:
    """Jólagjöf einstaklingsins fyrir næstu jól (eftir aðfangadag: næsta ár, ekki liðin jól)."""
    return (
        Gift.objects.alive()
        .christmas()
        .filter(season__household=request.person.household, season__year=christmas_year())
        .filter(person=request.person)
        .first()
    )


def _wishes(gift: Gift | None):
    if gift is None:
        return Idea.objects.none()
    return (
        gift.ideas.filter(wish=True)
        .select_related("store", "gift__season")
        .prefetch_related("store__locations")
        .order_by("position", "id")
    )


def own_wishes(request: WishRequest) -> list[Idea]:
    """Óskirnar sem einstaklingurinn hefur skráð sjálfur fyrir næstu jól. Ekkert um stöðu þeirra."""
    return list(_wishes(_request_gift(request)))


def wish_row(request: WishRequest) -> dict:
    """Línan á opnu síðunni, eins og eigin lína á gjafalistanum (gifts/partials/wish_row.html)."""
    gift = _request_gift(request)
    return {"name": request.person.name, "gift": gift, "wishes": list(_wishes(gift))}


@transaction.atomic
def add_wishes(request: WishRequest, text: str) -> list[Idea]:
    """„+ Hugmynd“ eins og á gjafalistanum: „sokkar, spil“ verða tvær óskir; tvítekningar hunsaðar.

    Jólagjöfin fyrir næstu jól verður til við fyrstu óskina.
    """
    from apps.gifts.services.gifts import add_ideas, ensure_christmas_gift

    if not any(normalize(t) for t in text.split(",")):
        return []
    # Einstaklingurinn læstur: tvísending býr ekki til tvær gjafir
    person = Person.objects.select_for_update().get(pk=request.person_id)
    # Borið saman við eigin óskir einar: annars kæmi í ljós hvað aðrir hafa skráð (privacy.py)
    return add_ideas(ensure_christmas_gift(person, christmas_year()), text[:1000], wish=True)


def own_wish(request: WishRequest, idea_id: int) -> Idea:
    """Ósk sem einstaklingurinn skráði sjálfur í ár; annars WishlistError."""
    idea = _wishes(_request_gift(request)).filter(pk=idea_id).first()
    if idea is None:
        raise WishlistError("Þessi ósk er ekki á listanum lengur.")
    return idea


def set_store(request: WishRequest, idea_id: int, name: str) -> Idea:
    from apps.gifts.services.gifts import set_wish_store

    return set_wish_store(own_wish(request, idea_id), name)


def delete_wish(request: WishRequest, idea_id: int) -> None:
    """Sé óskin keypt eða frátekin hverfur hún bara hjá honum (gifts.remove_wish)."""
    from apps.gifts.services.gifts import remove_wish

    remove_wish(own_wish(request, idea_id))


# ---------- Óskalisti heimilis: allt heimilisfólkið á einni síðu ----------
#
# Dísa á heimilið „Laugavegur 5“ og þar eru Dísa, Jói, Siggi og Stína í flokki heimilisins. Hún
# sendir ömmu Röggu einn hlekk (HouseholdShare). Amma sér óskir allra og getur tekið frá eins og á
# óskalista eins einstaklings. Hún getur líka bætt heimilinu í heild á sinn lista: þar verður til
# flokkurinn „Laugavegur 5“ (gifts.Family) og hvert þeirra fylgir sínum óskalista (Person.source).
# Bætist einhver síðar við heimilisflokkinn á Laugavegi 5 bætist hann líka við hjá ömmu.


def _home(people):
    return people.filter(group=Group.HEIMILI, family__isnull=True)


def home_people(household: Household) -> list[Person]:
    """Heimilisfólkið sem óskalisti heimilisins sýnir, í stafrófsröð."""
    from apps.core.text import is_sort_key

    people = _home(Person.objects.recipients().filter(household=household))
    return sorted(people, key=lambda p: is_sort_key(p.name))


def active_household_share(household: Household) -> HouseholdShare | None:
    return household.wishlist_shares.filter(revoked_at__isnull=True).order_by("-created_at").first()


def get_household_share(token: str) -> HouseholdShare | None:
    return (
        HouseholdShare.objects.select_related("household")
        .filter(token=token, revoked_at__isnull=True)
        .first()
    )


@transaction.atomic
def create_household_share(household: Household, by) -> HouseholdShare:
    """Nýr hlekkur; eldri hlekkir heimilisins hætta að virka."""
    revoke_household_share(household)
    return HouseholdShare.objects.create(household=household, created_by=by)


def revoke_household_share(household: Household) -> None:
    household.wishlist_shares.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())


def household_follower_names(household: Household) -> list[str]:
    """„Á lista hjá: Ragga“: notendur heimila sem fylgja heimilinu í heild."""
    names: set[str] = set()
    for follower in Household.objects.filter(families__source=household).distinct():
        names.update(member_names(follower) or [follower.name])
    return sorted(names)


def following_household(user, source: Household) -> list[Family]:
    """Heimili notandans sem fylgja `source` nú þegar."""
    return list(
        Family.objects.filter(source=source, household__memberships__user=user).select_related("household")
    )


@transaction.atomic
def follow_household(share: HouseholdShare, household: Household) -> Family:
    """Amma Ragga bætir Laugavegi 5 á sinn lista: flokkurinn verður til og heimilisfólkið bætist í hann."""
    if household.pk == share.household_id:
        raise WishlistError("Þetta er þitt eigið heimili.")
    family, _created = Family.objects.get_or_create(household=household, source=share.household)
    sync_family(family)
    return family


@transaction.atomic
def sync_family(family: Family) -> list[Person]:
    """Heimilisfólk sem hefur ekki enn bæst í flokkinn bætist við (líka þeir sem bættust síðar
    við heimilisflokkinn þar). Aðeins á meðan hlekkurinn er virkur. Skilar þeim sem bættust við.

    Hver bætist aðeins einu sinni við (`seen`): ekki aftur ef amma hætti að fylgja honum.
    """
    family = (
        Family.objects.select_for_update(of=("self",)).select_related("household", "source").get(pk=family.pk)
    )
    if active_household_share(family.source) is None:
        return []
    seen = set(family.seen.values_list("pk", flat=True))
    added = []
    for member in home_people(family.source):
        if member.pk in seen:
            continue
        family.seen.add(member)
        person = _family_person(family, member)
        if person is not None:
            added.append(person)
    return added


def _family_person(family: Family, member: Person) -> Person | None:
    """Einstaklingurinn hjá ömmu sem fylgir `member`: sá sem fylgir honum nú þegar, sá sem heitir
    sama nafni í Fjölskyldu eða Börnum og fylgir engum (Siggi sem amma var með fyrir), eða nýr.

    Aðeins Fjölskylda og Börn: Siggi vinur ömmu (Vinir) á ekki að fá óskalista barnabarnsins.
    """
    from apps.gifts.services.gifts import ensure_christmas_gift
    from apps.households.models import Membership

    household = family.household
    person = Person.objects.filter(household=household, source=member).first()
    already_following = person is not None
    if person is None:
        same_name = Person.objects.filter(household=household, key=normalize(member.name))
        # Ekki notendur hjá ömmu, þótt nafnið sé það sama
        person = (
            same_name.filter(source__isnull=True, family__isnull=True)
            .filter(group__in=[Group.FJOLSKYLDA, Group.BORN])
            .exclude(pk__in=Membership.objects.exclude(person=None).values("person_id"))
            .first()
        )
        if person is None:
            name = member.name if not same_name.exists() else f"{member.name} ({family.name})"[:100]
            person, _created = Person.objects.get_or_create(
                household=household, key=normalize(name), defaults={"name": name, "group": Group.FJOLSKYLDA}
            )
            if person.source_id:
                return None  # nafnið með heimilinu er þegar til og fylgir öðrum (mjög ólíklegt)
    person.source = member
    person.family = family
    # Fylgdi hann þegar (eigin hlekkur) helst sú fylgni ef hætt er að fylgja heimilinu
    person.family_follow = person.family_follow or not already_following
    person.save(update_fields=["source", "family", "family_follow"])
    season = current_season(member.household)
    if person.give_christmas and season is not None:
        ensure_christmas_gift(person, season.year)
    return person


def sync_families(household: Household) -> None:
    """Allir flokkar heimila sem `household` fylgir (kallað þegar listinn er opnaður)."""
    for family in Family.objects.filter(household=household):
        sync_family(family)


@transaction.atomic
def unfollow_family(family: Family) -> None:
    """„Hætta að fylgja heimilinu“: fólkið helst á listanum (í sínum fyrri flokki, Fjölskyldu) en
    fylgir ekki lengur óskalistunum þaðan. Hugmyndir sem voru teknar (afrit) haldast.

    Aðeins fylgni sem heimilið bjó til slitnar (líka hjá þeim sem voru færðir í annan flokk);
    sá sem fylgdi eigin hlekk áður heldur honum.
    """
    Person.objects.filter(
        household=family.household, family_follow=True, source__household=family.source
    ).update(source=None, family_follow=False)
    family.delete()
