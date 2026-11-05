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
    """Hugmyndir einstaklingsins á yfirstandandi ári, í röð listans."""
    season = current_season(share.person.household)
    if season is None:
        return None, []
    gift = Gift.objects.alive().christmas().filter(season=season, person=share.person).first()
    if gift is None:
        return season, []
    return season, list(gift.ideas.select_related("store").order_by("position", "id"))


def is_taken(idea: Idea) -> bool:
    """Frátekið eða keypt: opna síðan sýnir bara „Frátekið“, ekki hver eða hvers vegna."""
    return idea.picked or idea.reserved_by_id is not None


@dataclass(frozen=True)
class Reservation:
    """Það sem tæki þess sem tók frá geymir (undirritað cookie) til að geta hætt við."""

    idea_id: int
    secret: str
    added_giver: bool  # var gefandinn búinn til við frátekningu (þá fjarlægður ef hætt er við)


@transaction.atomic
def reserve(share: WishlistShare, idea_id: int, name: str) -> Reservation:
    name = name.strip()[:100]
    if not normalize(name):
        raise WishlistError("Skrifaðu nafnið þitt svo fjölskyldan viti hver tók frá.")
    idea = _idea_for_share(share, idea_id, lock=True)
    if is_taken(idea):
        raise WishlistError("Einhver var á undan þér og hefur þegar tekið þetta frá.")
    household = share.person.household
    # Nafnið borið saman við fólk heimilisins, svo „amma jóa“ verði Amma Jóa; annars nýr gefandi
    person = Person.objects.filter(household=household, key=normalize(name)).first()
    if person is None:
        person = Person.objects.create(household=household, name=name, group=Group.ANNAD)
    link, added = IdeaGiver.objects.get_or_create(idea=idea, person=person)
    idea.reserved_by = person
    idea.reserved_at = timezone.now()
    idea.reservation_secret = secrets.token_urlsafe(24)
    idea.save(update_fields=["reserved_by", "reserved_at", "reservation_secret"])
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
    idea.reserved_by = None
    idea.reserved_at = None
    idea.reservation_secret = ""
    idea.save(update_fields=["reserved_by", "reserved_at", "reservation_secret"])


def _idea_for_share(share: WishlistShare, idea_id: int, *, lock=False) -> Idea:
    """Hugmynd sem tilheyrir einstaklingi hlekksins á yfirstandandi ári; annars WishlistError."""
    season, ideas = visible_ideas(share)
    if idea_id not in {i.pk for i in ideas}:
        raise WishlistError("Þessi hugmynd er ekki á listanum lengur.")
    qs = Idea.objects.select_for_update() if lock else Idea.objects
    return qs.get(pk=idea_id)
