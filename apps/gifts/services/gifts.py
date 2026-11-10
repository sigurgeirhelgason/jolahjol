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


# Keypt hugmynd og „Tilbúið“ eru óháð: hugmynd getur verið keypt án þess að allt sé komið handa
# viðkomandi. Aðeins notandinn merkir gjöfina tilbúna (gátreiturinn „Tilbúið“, mark_bought).


def pick_idea(idea: Idea, amount: int | None = None) -> Idea:
    """Hugmynd merkt keypt. Gjöfin verður ekki „Tilbúið“ við það."""
    idea.picked = True
    if amount is not None:
        idea.price = amount
    idea.save()
    return idea


def unpick_idea(idea: Idea) -> Idea:
    """Hætt við keypta hugmynd. „Tilbúið“ á gjöfinni helst óbreytt."""
    idea.picked = False
    idea.save()
    return idea


def remove_idea(idea: Idea) -> None:
    idea.delete()


def remove_wish(idea: Idea) -> None:
    """Viðtakandinn fjarlægir eigin hugmynd. Sé hún keypt, frátekin eða komin með gefanda hverfur
    hún bara hjá honum (hættir að vera ósk), svo kaup og rukkun hinna haldist."""
    if idea.picked or idea.reserved or idea.giver_links.exists():
        idea.wish = False
        idea.save(update_fields=["wish"])
    else:
        idea.delete()


def add_ideas(gift: Gift, text: str, *, wish: bool = False) -> list[Idea]:
    """„sokkar, spil“ → tvær hugmyndir aftast.

    Hugmynd sem gjöfin hefur þegar (há- og lágstafir skipta ekki máli) bætist ekki við aftur,
    svo tvísending (t.d. Enter og blur) býr ekki til tvítekningu. `wish`: viðtakandinn skráir
    sjálfur (services/privacy.py).
    """
    # Viðtakandinn ber sig aðeins saman við eigin óskir: annars félli hugmynd hans út ef einhver
    # annar hefði skráð það sama, og hann vissi þá hvað hann fær (services/privacy.py)
    ideas = [i for i in gift.ideas.all() if i.wish] if wish else list(gift.ideas.all())
    seen = {normalize(i.text) for i in ideas}
    texts = []
    for t in (t.strip() for t in text.split(",")):
        if t and normalize(t) not in seen:
            seen.add(normalize(t))
            texts.append(t)
    start = gift.ideas.count()
    return [
        Idea.objects.create(gift=gift, text=t, position=start + i, wish=wish) for i, t in enumerate(texts)
    ]


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
def sync_ideas(gift: Gift, texts: list[str], *, wish: bool = False) -> None:
    """Gjafaglugginn: listinn „hugmyndir“ kemur í heild; óbreyttar hugmyndir halda vali og verði.

    Hugmyndir sem viðtakandinn skráði sjálfur (óskir) eru ekki í listanum og haldast óbreyttar:
    aðeins hann breytir þeim (services/privacy.py). Nýr texti sem er eins og ósk bætist ekki við.
    """
    ideas = list(gift.ideas.all())
    wishes = {normalize(i.text) for i in ideas if i.wish}
    old = {normalize(i.text): i for i in ideas if not i.wish}
    keep = []
    for position, text in enumerate(t.strip() for t in texts if t.strip()):
        if normalize(text) in wishes:
            continue
        idea = old.pop(normalize(text), None)
        if idea:
            idea.text, idea.position = text, position
            idea.save(update_fields=["text", "position"])
        else:
            idea = Idea.objects.create(gift=gift, text=text, position=position, wish=wish)
        keep.append(idea)
    for idea in old.values():
        remove_idea(idea)


@transaction.atomic
def ensure_christmas_gift(person: Person, year: int | None = None) -> Gift:
    """Jólagjöf einstaklings á árinu (þessu ári ef ekkert er gefið); árið og gjöfin verða til ef þarf.

    Notað þegar notandi tengist einstaklingi, svo línan hans og „+ Ósk“ séu tilbúin strax.
    """
    year = year or timezone.localdate().year
    season, _ = Season.objects.get_or_create(household=person.household, year=year)
    gift = Gift.objects.alive().christmas().filter(season=season, person=person).first()
    if gift:
        return gift
    last = season.gifts.christmas().order_by("-position").values_list("position", flat=True).first()
    return Gift.objects.create(season=season, person=person, position=(last or 0) + 1)


def soft_delete(gift: Gift) -> Gift:
    gift.deleted_at = timezone.now()
    gift.save(update_fields=["deleted_at", "updated_at"])
    return gift


def restore(gift: Gift) -> Gift:
    """„Afturkalla“. Ef önnur gjöf til sama einstaklings varð til á meðan er ekki hægt að endurheimta."""
    if Gift.objects.alive().filter(season=gift.season, person=gift.person, occasion=gift.occasion).exists():
        raise ValueError("Önnur gjöf til sama einstaklings er til")
    gift.deleted_at = None
    gift.save(update_fields=["deleted_at", "updated_at"])
    return gift


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " og " + names[-1]


def who_gives(names: list[str]) -> str:
    """„Ragnhildur gefur“, „Amma Jóa og Afi gefa“; tómt ef enginn gefandi.

    Nafnið stendur í nefnifalli, svo enginn freistist til að skrifa „frá Ragnhildi“ í gefendareitinn.
    """
    if not names:
        return ""
    return f"{_and(names)} {'gefur' if len(names) == 1 else 'gefa'}"


def gives_phrase(names: list[str]) -> str:
    """„Ragnhildur gefur gjöfina“ (línan á listanum og í Verslunum)."""
    return f"{who_gives(names)} gjöfina" if names else ""


def gift_text(gift: Gift) -> str:
    """Valdar hugmyndir (annars allar) með gefendum: „púsl (Amma Jóa gefur), bók“."""
    ideas = list(gift.ideas.all())
    picked = [i for i in ideas if i.picked]
    parts = []
    for idea in picked or ideas:
        gives = who_gives([link.person.name for link in idea.giver_links.all()])
        parts.append(idea.text + (f" ({gives})" if gives else ""))
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
def save_gift(
    season: Season,
    gift: Gift | None,
    data: GiftData,
    *,
    wish_for: int | None = None,
) -> Gift:
    """Gjafaglugginn: ný gjöf eða breyting. Samsvarar `giftForm` submit.

    `wish_for`: einstaklingur þess sem vistar; nýjar hugmyndir eru óskir ef hann er viðtakandinn.
    Kastar ValueError ef viðtakandinn á þegar (aðra) gjöf þetta ár.
    """
    household = season.household
    if gift is None:
        person = people.find_or_create(household, data.name, data.group)
        if Gift.objects.alive().christmas().filter(season=season, person=person).exists():
            raise ValueError(f"„{person.name}“ er þegar á listanum þetta ár")
        last = season.gifts.christmas().order_by("-position").values_list("position", flat=True).first()
        gift = Gift.objects.create(season=season, person=person, position=(last or 0) + 1)
    else:
        person = people.resolve_recipient(gift, data.name)
    if person.group != data.group:
        person.group = data.group
        person.save(update_fields=["group"])

    sync_ideas(gift, data.ideas, wish=wish_for is not None and person.pk == wish_for)
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
    reserved: bool = False


@transaction.atomic
def save_idea(idea: Idea, data: IdeaData, *, keep_content: bool = False) -> Idea:
    """Hugmyndaglugginn. Samsvarar `saveIdea`.

    „Keypt fyrir annan“ krefst gefanda og verðinu er skipt jafnt á gefendur. „Greitt“ gildir
    um alla gefendur hugmyndarinnar (hver gefandi er merktur sér undir Rukkun).
    """
    gift = idea.gift
    household = gift.season.household
    idea.price = data.price
    # `keep_content`: ósk viðtakanda sem annar vistar. Texti, lýsing, hlekkur og búð eru hans, svo
    # hann sjái aldrei breytingu sem hann gerði ekki sjálfur; aðrir sjá um kaup, verð og gefendur.
    if not keep_content:
        idea.text = data.text.strip()
        idea.note = data.note.strip()
        idea.link = data.link.strip()
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

    if data.reserved != idea.reserved:
        set_reserved(idea, data.reserved)
    if data.picked and not idea.picked:
        pick_idea(idea)
        if not gift.link and idea.link:
            gift.link = idea.link
            gift.save(update_fields=["link", "updated_at"])
    elif not data.picked and idea.picked:
        unpick_idea(idea)
    return idea


def set_reserved(idea: Idea, reserved: bool) -> Idea:
    """Rofinn „Frátekið“. Af tekið: frátekning af óskalista fellur niður en gefandinn helst."""
    if reserved:
        idea.reserved = True
        idea.reserved_at = idea.reserved_at or timezone.now()
        idea.save(update_fields=["reserved", "reserved_at"])
    else:
        idea.reserved = False
        idea.reserved_by = None
        idea.reserved_at = None
        idea.reservation_secret = ""
        idea.save(update_fields=["reserved", "reserved_by", "reserved_at", "reservation_secret"])
    return idea


def save_wish(idea: Idea, *, text: str, note: str, link: str) -> Idea:
    """Óskaglugginn: viðtakandinn breytir eigin ósk (staða gjafarinnar er leynd fyrir honum)."""
    idea.text = text.strip()
    idea.note = note.strip()
    idea.link = link.strip()
    idea.save(update_fields=["text", "note", "link"])
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

    Með „Gef jólagjafir“ fer hann á jólalista ársins (með áætlun og hugmyndum). Nýr
    einstaklingur fær upplýsingarnar úr `data`. Einstaklingur sem er til (t.d. frá fyrri árum
    eða gefandi) heldur sínum flokki, fæðingardegi og afmælisgjöf.
    Kastar ValueError ef hann er þegar á lista ársins.
    """
    household = season.household
    person = Person.objects.filter(household=household, key=normalize(data.name)).first()
    on_list = Gift.objects.alive().christmas().filter(season=season, person=person)
    if person and data.give_christmas and on_list.exists():
        raise ValueError(f"„{person.name}“ er þegar á listanum þetta ár")
    if person is None:
        person = Person.objects.create(
            household=household,
            name=data.name,
            group=data.group,
            birthday=data.birthday,
            give_christmas=data.give_christmas,
            give_birthday=data.give_birthday,
        )
    elif data.give_christmas and not person.give_christmas:
        person.give_christmas = True
        person.save(update_fields=["give_christmas"])
    if not data.give_christmas:
        return person, None
    last = season.gifts.christmas().order_by("-position").values_list("position", flat=True).first()
    gift = Gift.objects.create(season=season, person=person, plan=data.plan, position=(last or 0) + 1)
    sync_ideas(gift, data.ideas)
    return person, gift
