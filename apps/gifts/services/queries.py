"""Sameiginlegar fyrirspurnir sem sækja allt sem þjónusturnar þurfa í fáum köllum."""

from django.db.models import Prefetch, QuerySet

from ..models import Gift, Idea, IdeaGiver, Season


def with_details(gifts: QuerySet[Gift]) -> QuerySet[Gift]:
    ideas = Idea.objects.select_related("store", "reserved_by").prefetch_related(
        Prefetch("giver_links", queryset=IdeaGiver.objects.select_related("person"))
    )
    return gifts.select_related("person", "season").prefetch_related(
        Prefetch("ideas", queryset=ideas), "stores__locations", "ideas__store__locations"
    )


def season_gifts(season: Season) -> list[Gift]:
    return list(with_details(season.gifts.alive()))
