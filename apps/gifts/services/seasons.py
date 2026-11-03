"""Jólaár: stofnun nýs árs og saga einstaklings. Samsvarar `newYearBtn` og `historyOf`."""

from dataclasses import dataclass

from django.db import transaction

from apps.households.models import Household

from ..models import Gift, Person, Season
from .gifts import gift_text
from .queries import with_details


@transaction.atomic
def new_season(household: Household, year: int, copy_from: Season | None = None) -> Season:
    """Nýtt ár. Með `copy_from` fylgja viðtakendur (sem gefa jólagjafir), áætlun og viðmið."""
    season, created = Season.objects.get_or_create(
        household=household, year=year, defaults={"budget": copy_from.budget if copy_from else 0}
    )
    if created and copy_from:
        for position, gift in enumerate(copy_from.gifts.alive().select_related("person")):
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
