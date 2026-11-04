"""Aðgerðir á gjöfum og hugmyndum. Samsvarar keypt-flæðinu (`askPrice`/`finishPrice`) og `saveIdea`."""

import datetime
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.core.text import normalize

from ..models import Gift, Idea, IdeaGiver, Person, Season
from . import people, stores
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
    """„sokkar, spil“ → tvær hugmyndir aftast.

    Hugmynd sem gjöfin hefur þegar (há- og lágstafir skipta ekki máli) bætist ekki við aftur,
    svo tvísending (t.d. Enter og blur) býr ekki til tvítekningu.
    """
    seen = {normalize(i.text) for i in gift.ideas.all()}
    texts = []
    for t in (t.strip() for t in text.split(",")):
        if t and normalize(t) not in seen:
            seen.add(normalize(t))
            texts.append(t)
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


# ---------- Gluggarnir: gjöf og hugmynd ----------


@dataclass(frozen=True)
class GiftData:
    name: str
    group: str
    plan: int | None
    ideas: list[str]
    store: str
    link: str


@transaction.atomic
def save_gift(season: Season, gift: Gift | None, data: GiftData) -> Gift:
    """Gjafaglugginn: ný gjöf eða breyting. Samsvarar `giftForm` submit.

    Kastar ValueError ef viðtakandinn á þegar (aðra) gjöf þetta ár.
    """
    household = season.household
    if gift is None:
        person = people.find_or_create(household, data.name, data.group)
        if Gift.objects.alive().filter(season=season, person=person).exists():
            raise ValueError(f"„{person.name}“ er þegar á listanum þetta ár")
        last = season.gifts.order_by("-position").values_list("position", flat=True).first()
        gift = Gift.objects.create(season=season, person=person, position=(last or 0) + 1)
    else:
        person = people.resolve_recipient(gift, data.name)
    if person.group != data.group:
        person.group = data.group
        person.save(update_fields=["group"])

    sync_ideas(gift, data.ideas)
    store_name = data.store or (stores.store_from_url(data.link) if stores.is_url(data.link) else "")
    store = stores.get_or_create_store(household, store_name)
    gift.stores.set([store] if store else [])
    gift.link = data.link
    gift.plan = data.plan
    gift.save()
    return gift


@dataclass(frozen=True)
class IdeaData:
    text: str
    givers: list[str]
    for_other: bool
    paid: bool
    note: str
    store: str
    locations: str
    price: int | None
    link: str
    picked: bool


@transaction.atomic
def save_idea(idea: Idea, data: IdeaData) -> Idea:
    """Hugmyndaglugginn. Samsvarar `saveIdea`.

    „Keypt fyrir annan“ krefst gefanda og verðinu er skipt jafnt á gefendur. „Greitt“ gildir
    um alla gefendur hugmyndarinnar (hver gefandi er merktur sér undir Rukkun).
    """
    gift = idea.gift
    household = gift.season.household
    idea.text = data.text.strip()
    idea.note = data.note.strip()
    idea.link = data.link.strip()
    idea.price = data.price
    store_name = data.store or (stores.store_from_url(idea.link) if stores.is_url(idea.link) else "")
    idea.store = stores.get_or_create_store(household, store_name)
    if idea.store:
        stores.set_locations(idea.store, data.locations)

    givers = people.givers_from_names(household, data.givers)
    idea.for_other = data.for_other and bool(givers)
    idea.save()
    set_givers(idea, givers)

    # Verðinu er alltaf skipt jafnt á gefendur (share=None); sjá pricing.split_shares
    for link in idea.giver_links.select_related("person"):
        link.share = None
        link.paid = idea.for_other and data.paid
        link.save(update_fields=["share", "paid"])

    if data.picked and not idea.picked:
        pick_idea(idea)
        if not gift.link and idea.link:
            gift.link = idea.link
            gift.save(update_fields=["link", "updated_at"])
    elif not data.picked and idea.picked:
        unpick_idea(idea)
    return idea


@dataclass(frozen=True)
class PersonData:
    name: str
    group: str
    birthday: datetime.date | None
    give_christmas: bool
    give_birthday: bool
    plan: int | None
    ideas: list[str]


@transaction.atomic
def add_person(season: Season, data: PersonData) -> tuple[Person, Gift | None]:
    """„Bæta við aðila“: einstaklingur með fæðingardegi og hvaða gjafir hann fær.

    Með „Gef jólagjafir“ fer hann á jólalista ársins (með áætlun og hugmyndum). Sé
    einstaklingurinn til (t.d. gefandi eða frá fyrri árum) eru upplýsingar hans uppfærðar.
    Kastar ValueError ef hann er þegar á lista ársins.
    """
    person = people.find_or_create(season.household, data.name, data.group)
    if data.give_christmas and Gift.objects.alive().filter(season=season, person=person).exists():
        raise ValueError(f"„{person.name}“ er þegar á listanum þetta ár")
    person.group = data.group
    person.birthday = data.birthday
    person.give_christmas = data.give_christmas
    person.give_birthday = data.give_birthday
    person.save()
    if not data.give_christmas:
        return person, None
    last = season.gifts.order_by("-position").values_list("position", flat=True).first()
    gift = Gift.objects.create(season=season, person=person, plan=data.plan, position=(last or 0) + 1)
    sync_ideas(gift, data.ideas)
    return person, gift
