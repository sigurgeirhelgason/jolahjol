"""Sameiginlegar fyrirspurnir sem sækja allt sem þjónusturnar þurfa í fáum köllum."""

from django.db.models import Prefetch, QuerySet

from ..models import Gift, Idea, IdeaGiver, Season


def with_details(gifts: QuerySet[Gift]) -> QuerySet[Gift]:
    """Gjafir með öllu sem listinn þarf. `gift.ideas.all()` sleppir földum óskum (Idea.hidden);
    viðtakandinn sjálfur sér þær í `wishes_of(gift)`."""
    ideas = (
        Idea.objects.visible()
        .select_related("store", "reserved_by", "source")
        .prefetch_related(Prefetch("giver_links", queryset=IdeaGiver.objects.select_related("person")))
    )
    # Faldar óskir eru fáar; viðtakandinn sér þær á eigin línu (wishes_of)
    hidden_wishes = (
        Idea.objects.filter(wish=True, hidden=True)
        .select_related("store")
        .prefetch_related("store__locations")
    )
    return gifts.select_related("person", "season", "person__source__household").prefetch_related(
        Prefetch("ideas", queryset=ideas),
        Prefetch("ideas", queryset=hidden_wishes, to_attr="hidden_wishes"),
        "stores__locations",
        "ideas__store__locations",
    )


def wishes_of(gift: Gift) -> list[Idea]:
    """Óskir viðtakandans eins og hann sér þær: líka þær sem heimilið faldi."""
    if hasattr(gift, "hidden_wishes"):
        wishes = [i for i in gift.ideas.all() if i.wish] + gift.hidden_wishes
        return sorted(wishes, key=lambda i: (i.position, i.pk))
    return list(gift.ideas.filter(wish=True).select_related("store").order_by("position", "id"))


def season_gifts(season: Season) -> list[Gift]:
    """Jólagjafir ársins (listinn, Verslanir, Rukkun, yfirlit). Afmælisgjafir: services/birthdays.py."""
    return list(with_details(season.gifts.alive().christmas()))
