"""Aðgerðir á gjöfum og hugmyndum. Samsvarar keypt-flæðinu (`askPrice`/`finishPrice`) og `saveIdea`."""

from django.db import transaction
from django.utils import timezone

from apps.core.text import normalize

from ..models import Gift, Idea, IdeaGiver, Person
from .pricing import actual_price


def needs_price(gift: Gift) -> bool:
    """Gjöf merkt keypt án þekkts verðs: viðmótið spyr hvað hún kostaði."""
    return gift.bought and actual_price(gift) is None


@transaction.atomic
def mark_bought(gift: Gift, amount: int | None = None) -> Gift:
    """Gátreiturinn „Keypt“. Upphæð bætist við áður skráða upphæð („+2000“-hegðunin)."""
    gift.bought = True
    if amount is not None:
        gift.manual_price = (gift.manual_price or 0) + amount
    gift.save()
    return gift


@transaction.atomic
def mark_unbought(gift: Gift) -> Gift:
    gift.bought = False
    gift.manual_price = None
    gift.save()
    return gift


@transaction.atomic
def pick_idea(idea: Idea, amount: int | None = None) -> Idea:
    """Hugmynd merkt keypt; gjöfin telst þá keypt."""
    idea.picked = True
    if amount is not None:
        idea.price = amount
    idea.save()
    if not idea.gift.bought:
        idea.gift.bought = True
        idea.gift.save(update_fields=["bought", "updated_at"])
    return idea


@transaction.atomic
def unpick_idea(idea: Idea) -> Idea:
    """Hætt við keypta hugmynd; gjöfin er ekki lengur keypt ef engin önnur er það."""
    idea.picked = False
    idea.save()
    gift = idea.gift
    if not gift.ideas.filter(picked=True).exists():
        gift.bought = False
        gift.save(update_fields=["bought", "updated_at"])
    return idea


@transaction.atomic
def remove_idea(idea: Idea) -> None:
    gift = idea.gift
    was_picked = idea.picked
    idea.delete()
    if was_picked and not gift.ideas.filter(picked=True).exists():
        gift.bought = False
        gift.save(update_fields=["bought", "updated_at"])


def add_ideas(gift: Gift, text: str) -> list[Idea]:
    """„sokkar, spil“ → tvær hugmyndir aftast."""
    texts = [t.strip() for t in text.split(",") if t.strip()]
    start = gift.ideas.count()
    return [Idea.objects.create(gift=gift, text=t, position=start + i) for i, t in enumerate(texts)]


@transaction.atomic
def set_givers(idea: Idea, people: list[Person]) -> None:
    """Setur gefendur hugmyndar; heldur `share` og `paid` þeirra sem halda áfram.

    Hugmynd án gefenda er frá okkur og getur því ekki verið keypt fyrir annan.
    """
    keep = {p.pk for p in people}
    idea.giver_links.exclude(person_id__in=keep).delete()
    existing = set(idea.giver_links.values_list("person_id", flat=True))
    IdeaGiver.objects.bulk_create(IdeaGiver(idea=idea, person=p) for p in people if p.pk not in existing)
    if not people and idea.for_other:
        idea.for_other = False
        idea.save(update_fields=["for_other"])


@transaction.atomic
def sync_ideas(gift: Gift, texts: list[str]) -> None:
    """Gjafaglugginn: listinn „hugmyndir“ kemur í heild; óbreyttar hugmyndir halda vali og verði."""
    old = {normalize(i.text): i for i in gift.ideas.all()}
    keep = []
    for position, text in enumerate(t.strip() for t in texts if t.strip()):
        idea = old.pop(normalize(text), None)
        if idea:
            idea.text, idea.position = text, position
            idea.save(update_fields=["text", "position"])
        else:
            idea = Idea.objects.create(gift=gift, text=text, position=position)
        keep.append(idea)
    for idea in old.values():
        remove_idea(idea)


def soft_delete(gift: Gift) -> Gift:
    gift.deleted_at = timezone.now()
    gift.save(update_fields=["deleted_at", "updated_at"])
    return gift


def restore(gift: Gift) -> Gift:
    """„Afturkalla“. Ef önnur gjöf til sama einstaklings varð til á meðan er ekki hægt að endurheimta."""
    if Gift.objects.alive().filter(season=gift.season, person=gift.person).exists():
        raise ValueError("Önnur gjöf til sama einstaklings er til")
    gift.deleted_at = None
    gift.save(update_fields=["deleted_at", "updated_at"])
    return gift


def gift_text(gift: Gift) -> str:
    """Valdar hugmyndir (annars allar) með gefendum: „púsl (frá Ömmu Jóu), bók“."""
    ideas = list(gift.ideas.all())
    picked = [i for i in ideas if i.picked]
    parts = []
    for idea in picked or ideas:
        names = [link.person.name for link in idea.giver_links.all()]
        parts.append(idea.text + (f" (frá {' og '.join(names)})" if names else ""))
    return ", ".join(parts)
