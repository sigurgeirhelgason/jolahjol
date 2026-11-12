"""Óskalistar: opinn hlekkur á hugmyndir eins einstaklings, og frátekning án innskráningar.

Opna síðan sýnir aðeins hugmyndir einstaklingsins á yfirstandandi ári. Hvorki nöfn annarra,
upphæðir sem hafa verið greiddar, rukkun né hver tók frá birtast þar.
"""

import secrets
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.core.text import normalize
from apps.gifts.models import Gift, Group, Idea, IdeaGiver, Person, Season
from apps.gifts.services.privacy import is_linked
from apps.households.models import Household

from .models import WishlistShare


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
    """Hugmyndir einstaklingsins á yfirstandandi ári, í röð listans.

    Sé einstaklingurinn notandi í heimilinu birtast aðeins óskirnar sem hann skráði sjálfur:
    hann gæti opnað hlekkinn sjálfur (services/privacy.py).
    """
    season = current_season(share.person.household)
    if season is None:
        return None, []
    gift = Gift.objects.alive().christmas().filter(season=season, person=share.person).first()
    if gift is None:
        return season, []
    ideas = gift.ideas.select_related("store").order_by("position", "id")
    if is_linked(share.person):
        ideas = ideas.filter(wish=True)
    return season, list(ideas)


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
def reserve(share: WishlistShare, idea_id: int, name: str) -> Reservation:
    name = name.strip()[:100]
    if not normalize(name):
        raise WishlistError("Skrifaðu nafnið þitt svo fjölskyldan viti hver tók frá.")
    idea = _idea_for_share(share, idea_id, lock=True)
    if is_taken(idea):
        raise WishlistError("Einhver var á undan þér og hefur þegar tekið þetta frá.")
    added = _reserve_as(idea, name)
    return Reservation(idea.pk, idea.reservation_secret, added)


@transaction.atomic
def cancel(share: WishlistShare, reservation: Reservation) -> None:
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


def _idea_for_share(share: WishlistShare, idea_id: int, *, lock=False) -> Idea:
    """Hugmynd sem tilheyrir einstaklingi hlekksins á yfirstandandi ári; annars WishlistError."""
    season, ideas = visible_ideas(share)
    if idea_id not in {i.pk for i in ideas}:
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
    source_ids = {g.person.source_id for g in wanted}
    shared = set(
        WishlistShare.objects.filter(person_id__in=source_ids, revoked_at__isnull=True).values_list(
            "person_id", flat=True
        )
    )
    sources = {p.pk: p for p in Person.objects.filter(pk__in=shared)}
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
        Idea.objects.filter(gift__in=source_gifts.values()).select_related("store").order_by("position", "id")
    ):
        ideas.setdefault(idea.gift_id, []).append(idea)
    linked = set(Membership.objects.filter(person_id__in=sources).values_list("person_id", flat=True))

    out: dict[int, list[Idea]] = {}
    for gift in wanted:
        source = sources.get(gift.person.source_id)
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
            person = find_or_create(household, name, group if group in Group.values else Group.ANNAD)
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
    """„Hætta að fylgja“. Hugmyndir sem voru teknar (afrit) haldast."""
    person.source = None
    person.save(update_fields=["source"])


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
