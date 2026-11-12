"""Jólaár: stofnun nýs árs og saga einstaklings. Samsvarar `newYearBtn` og `historyOf`."""

from dataclasses import dataclass

from django.db import transaction

from apps.households.models import Household

from ..models import Gift, Idea, Person, Season
from .gifts import gift_text
from .queries import with_details


@transaction.atomic
def new_season(household: Household, year: int, copy_from: Season | None = None) -> Season:
    """Nýtt ár. Með `copy_from` fylgja viðtakendur (sem gefa jólagjafir), áætlun og viðmið."""
    season, created = Season.objects.get_or_create(
        household=household, year=year, defaults={"budget": copy_from.budget if copy_from else 0}
    )
    # Árið gæti hafa orðið til vegna afmælisgjafar; jólin eru þá samt ný
    fresh = created or not season.gifts.christmas().exists()
    if fresh and copy_from:
        if not created and not season.budget:
            season.budget = copy_from.budget
            season.save(update_fields=["budget"])
        for position, gift in enumerate(copy_from.gifts.alive().christmas().select_related("person")):
            if gift.person.give_christmas:
                Gift.objects.create(season=season, person=gift.person, plan=gift.plan, position=position)
    return season


@dataclass(frozen=True)
class HistoryEntry:
    year: int
    gift: Gift
    text: str


def history(person: Person, before_year: int | None = None) -> list[HistoryEntry]:
    """Fyrri gjafir, nýjasta fyrst."""
    gifts = with_details(Gift.objects.alive().filter(person=person)).order_by("-season__year")
    if before_year is not None:
        gifts = gifts.filter(season__year__lt=before_year)
    return [HistoryEntry(g.season.year, g, gift_text(g)) for g in gifts]


@transaction.atomic
def delete_season(season: Season) -> int:
    """Eyðir jólaári og gjöfum þess (líka eyddum). Fólk og búðir haldast. Skilar fjölda gjafa."""
    from apps.wishlists.services import release_copies

    count = season.gifts.alive().count()
    release_copies(Idea.objects.filter(gift__season=season))
    season.gifts.all().delete()
    season.delete()
    return count
