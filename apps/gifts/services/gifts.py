"""Aðgerðir á gjöfum og hugmyndum. Samsvarar keypt-flæðinu (`askPrice`/`finishPrice`) og `saveIdea`."""

import datetime
import secrets
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


@transaction.atomic
def unpick_idea(idea: Idea, *, release_wish: bool = True) -> Idea:
    """Hætt við keypta hugmynd. „Tilbúið“ á gjöfinni helst óbreytt.

    `release_wish`: afrit af ósk losar hana ef það er ekki lengur í notkun (`untake`).
    """
    idea.picked = False
    idea.save()
    if release_wish:
        untake(idea)
    return idea


# ---------- Ósk annars keypt eða tekin frá: afrit sem heimilið á ----------
#
# Dísa skráði „trefill“ (ósk). Þegar Jói hakar við hana eða tekur hana frá verður til afrit sem
# heimilið á og breytir að vild (texti, búð, verð …); óskin sjálf verður falin og frátekin, svo hún
# hverfur af opna óskalistanum. Dísa sér óskina sína áfram og ekkert um stöðuna (privacy.py).
# Sama mynstur og þegar hugmynd er tekin af óskalista í öðru heimili (wishlists.claim).
# Afritið helst tengt á meðan það er í notkun (`in_use`); annars losnar óskin og birtist aftur
# (`untake`), t.d. þegar hakið er tekið af eða afritinu eytt.


def can_take(idea: Idea) -> bool:
    """Laus ósk (hvorki keypt, frátekin né falin) sem heimilið getur tekið."""
    return idea.wish and not (idea.picked or idea.reserved or idea.hidden)


@transaction.atomic
def take_wish(idea: Idea) -> Idea:
    """Afrit af óskinni sem heimilið á; óskin verður falin og frátekin. Skilar afritinu.

    Gefendur sem voru komnir á óskina fylgja afritinu (kaupunum). Hafi önnur beiðni (tvísmellt,
    tveir í einu) tekið hana á meðan beðið var eftir læsingunni kemur afritið sem varð til þá.
    """
    idea = Idea.objects.select_for_update(of=("self",)).select_related("gift__season").get(pk=idea.pk)
    if not can_take(idea):
        household_id = idea.gift.season.household_id
        return idea.copies.filter(gift__season__household_id=household_id).first() or idea
    secret = secrets.token_urlsafe(24)
    copy = Idea.objects.create(
        gift_id=idea.gift_id,
        text=idea.text,
        note=idea.note,
        link=idea.link,
        store_id=idea.store_id,
        price=idea.price,
        for_other=idea.for_other,
        position=idea.position,
        source=idea,
        # Sama leyndarmál og á óskinni: þannig veit afritið hvort frátekningin er enn þess
        reservation_secret=secret,
    )
    idea.giver_links.update(idea=copy)
    idea.hidden = True
    idea.for_other = False
    idea.reserved = True
    idea.reserved_at = timezone.now()
    idea.reservation_secret = secret
    idea.save(update_fields=["hidden", "for_other", "reserved", "reserved_at", "reservation_secret"])
    return copy


def is_own_copy(idea: Idea) -> bool:
    """Afrit af ósk í sama heimili (ekki af óskalista í öðru heimili)."""
    source = idea.source
    return source is not None and source.gift.season.household_id == idea.gift.season.household_id


def in_use(copy: Idea) -> bool:
    """Afrit sem heimilið notar: keypt, frátekið, með gefanda eða keypt fyrir annan."""
    return copy.picked or copy.reserved or copy.for_other or copy.giver_links.exists()


def _free_wish(copy: Idea, *, keep_price: bool = False) -> Idea | None:
    """Óskin sem afrit í sama heimili tók birtist aftur og frátekningin fellur niður.

    Tengingin er `copy.source` (sama heimili), ekki leyndarmálið, svo óskin getur ekki setið föst
    falin þótt frátekning afritsins hafi verið hreinsuð. Keypt ósk (eldri gögn) er látin vera.
    """
    source = Idea.objects.select_for_update().filter(pk=copy.source_id).first()
    if source is None or source.picked:
        return None
    source.hidden = False
    source.reserved = False
    source.reserved_by = None
    source.reserved_at = None
    source.reservation_secret = ""
    fields = ["hidden", "reserved", "reserved_by", "reserved_at", "reservation_secret"]
    if keep_price and copy.price != source.price:
        source.price = copy.price  # verðið sem heimilið fann tapast ekki
        fields.append("price")
    source.save(update_fields=fields)
    return source


@transaction.atomic
def untake(copy: Idea) -> None:
    """Afrit af ósk sem er ekki lengur í notkun: óskin losnar og birtist aftur.

    Afriti sem heimilið hefur ekki breytt (`edited`) er eytt (annars væri sama hugmyndin tvisvar)
    og verðið fer á óskina. Breytt afrit helst sem hugmynd heimilisins, ótengt óskinni. Breyting
    viðtakandans á óskinni (`source_changed`) gerir afritið ekki „breytt“. Afrit í notkun helst.
    """
    if not copy.pk or not copy.source_id or in_use(copy) or not is_own_copy(copy):
        return
    source = _free_wish(copy, keep_price=not copy.edited)
    if source is None:
        return
    if not copy.edited:
        copy.delete()
    else:
        copy.source = None
        copy.source_changed = False
        copy.reservation_secret = ""
        copy.save(update_fields=["source", "source_changed", "reservation_secret"])


@transaction.atomic
def remove_idea(idea: Idea) -> None:
    """Eyðir hugmynd. Sé hún afrit af ósk í sama heimili birtist óskin aftur; sé hún tekin af
    óskalista í öðru heimili fellur frátekningin þar niður."""
    from apps.wishlists.services import release

    if idea.source_id and is_own_copy(idea):
        _free_wish(idea, keep_price=True)
    else:
        release(idea)
    idea.delete()


def remove_wish(idea: Idea) -> None:
    """Viðtakandinn fjarlægir eigin hugmynd.

    Sé hún keypt eða með gefanda (eða frátekin af opnum óskalista) hverfur hún bara hjá honum
    (hættir að vera ósk), svo kaup og rukkun hinna haldist. Tekin ósk (falin; afritið heldur
    kaupunum) og ósk sem heimilið faldi með × er eytt.
    """
    if idea.picked or idea.giver_links.exists() or (idea.reserved and not idea.hidden):
        idea.wish = False
        idea.hidden = False  # nú hugmynd heimilisins: hún á að sjást þar
        idea.save(update_fields=["wish", "hidden"])
    else:
        idea.delete()


def can_hide(idea: Idea) -> bool:
    """Heimilið má fela ósk (× á línunni) á meðan hún er hvorki keypt, frátekin né með gefanda:
    þá hefur hún engin áhrif á verð, rukkun eða innkaup."""
    return idea.wish and not (idea.picked or idea.reserved or idea.giver_links.exists())


@transaction.atomic
def hide_wish(idea: Idea, hidden: bool = True) -> None:
    """× á ósk annars: hún hverfur hjá heimilinu en viðtakandinn sér hana áfram (Idea.hidden).

    `hidden=False` („Afturkalla“) birtir hana aftur, en aðeins ef hún var falin með × (ekki tekin).
    Staðan er athuguð undir læsingu: einhver gæti verið að taka hana eða taka hana frá á meðan.
    """
    locked = Idea.objects.select_for_update().get(pk=idea.pk)
    if hidden and not can_hide(locked):
        raise ValueError("Ekki hægt að fela ósk sem er keypt, frátekin eða með gefanda")
    if not hidden and (not locked.hidden or locked.reserved or locked.picked):
        raise ValueError("Óskin var tekin: hún birtist ekki aftur svona")
    idea.hidden = locked.hidden = hidden
    locked.save(update_fields=["hidden"])


def add_ideas(gift: Gift, text: str, *, wish: bool = False) -> list[Idea]:
    """„sokkar, spil“ → tvær hugmyndir aftast.

    Hugmynd sem gjöfin hefur þegar (há- og lágstafir skipta ekki máli) bætist ekki við aftur,
    svo tvísending (t.d. Enter og blur) býr ekki til tvítekningu. `wish`: viðtakandinn skráir
    sjálfur (services/privacy.py).
    """
    # Viðtakandinn ber sig aðeins saman við eigin óskir: annars félli hugmynd hans út ef einhver
    # annar hefði skráð það sama, og hann vissi þá hvað hann fær (services/privacy.py)
    # Faldar óskir: viðtakandinn sér þær (bætir þeim ekki við aftur), heimilið ekki
    ideas = list(gift.ideas.filter(wish=True)) if wish else list(gift.ideas.visible())
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
    wishes = {normalize(i.text) for i in ideas if i.wish and not i.hidden}
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


def and_join(names: list[str]) -> str:
    """["Jói", "Anna", "Gunna"] → „Jói, Anna og Gunna“."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " og " + names[-1]


def who_gives(names: list[str]) -> str:
    """„Ragnhildur gefur“, „Amma Jóa og Afi gefa“; tómt ef enginn gefandi.

    Nafnið stendur í nefnifalli, svo enginn freistist til að skrifa „frá Ragnhildi“ í gefendareitinn.
    """
    if not names:
        return ""
    return f"{and_join(names)} {'gefur' if len(names) == 1 else 'gefa'}"


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
    before = _wish_content(idea)
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
    idea.source_changed = False  # heimilið hefur séð afritið og vistað
    if idea.source_id and not keep_content and _edited(before, idea, auto_store=not data.store):
        idea.edited = True
    idea.save()
    set_givers(idea, givers)

    # Verðinu er alltaf skipt jafnt á gefendur (share=None); sjá pricing.split_shares
    for link in idea.giver_links.select_related("person"):
        link.share = None
        link.paid = idea.for_other and data.paid
        link.save(update_fields=["share", "paid"])

    # Afrit af ósk losnar aðeins þegar allt er vistað: Frátekið af og Keypt á í sömu vistun
    # má ekki losa óskina á milli skrefa
    if data.reserved != idea.reserved:
        set_reserved(idea, data.reserved, release_wish=False)
    if data.picked and not idea.picked:
        pick_idea(idea)
        if not gift.link and idea.link:
            gift.link = idea.link
            gift.save(update_fields=["link", "updated_at"])
    elif not data.picked and idea.picked:
        unpick_idea(idea, release_wish=False)
    untake(idea)
    return idea


@transaction.atomic
def set_reserved(idea: Idea, reserved: bool, *, release_wish: bool = True) -> Idea:
    """Rofinn „Frátekið“. Af tekið: frátekning af óskalista fellur niður en gefandinn helst.

    `release_wish`: eins og í `unpick_idea`.
    """
    if reserved:
        idea.reserved = True
        idea.reserved_at = idea.reserved_at or timezone.now()
        idea.save(update_fields=["reserved", "reserved_at"])
    else:
        from apps.wishlists.services import release

        # Tekin af óskalista í öðru heimili og ekki keypt: losnar þar líka. Afrit af ósk í sama
        # heimili losnar aðeins í `untake` (þegar það er ekki lengur í notkun).
        if not idea.picked and not is_own_copy(idea):
            release(idea)
        idea.reserved = False
        idea.reserved_by = None
        idea.reserved_at = None
        # Keypt afrit af óskalista heldur leyndarmálinu: það tengir það frátekningunni á
        # upprunanum, svo hún losni ef afritið er síðar afkeypt og eytt. Afrit af ósk í sama
        # heimili heldur því alltaf: `untake` losar óskina með því (og hreinsar það).
        if not (idea.source_id and (idea.picked or is_own_copy(idea))):
            idea.reservation_secret = ""
        idea.save(update_fields=["reserved", "reserved_by", "reserved_at", "reservation_secret"])
        if release_wish:
            untake(idea)
    return idea


def save_wish(idea: Idea, *, text: str, note: str, link: str, store: str = "") -> Idea:
    """Óskaglugginn: viðtakandinn breytir eigin ósk (staða gjafarinnar er leynd fyrir honum).

    Búð eins og í hugmyndaglugganum: sé hún ekki gefin kemur hún úr hlekknum (elko.is → Elko).
    """
    before = _wish_content(idea)
    old_link = idea.link
    idea.text = text.strip()
    idea.note = note.strip()
    idea.link = link.strip()
    # Búð úr hlekknum aðeins þegar nýr hlekkur er skráður: annars má hreinsa búðina
    if not store.strip() and idea.link != old_link and stores.is_url(idea.link):
        store = stores.store_from_url(idea.link)
    idea.store = stores.get_or_create_store(idea.gift.season.household, store)
    idea.save(update_fields=["text", "note", "link", "store"])
    if _wish_content(idea) != before:
        idea.copies.update(source_changed=True)  # sá sem keypti eða tók frá sér að óskinni var breytt
    return idea


def _wish_content(idea: Idea) -> dict:
    return {"text": idea.text, "note": idea.note, "link": idea.link, "store": idea.store_id}


def _edited(before: dict, idea: Idea, *, auto_store: bool) -> bool:
    """Breytti heimilið efni afritsins? Búð sem kom sjálfkrafa úr hlekknum (búðarreitur tómur en
    búð til eftir vistun) telst ekki með; búð sem var hreinsuð eða skrifuð inn telst breyting."""
    after = _wish_content(idea)
    if any(after[k] != before[k] for k in ("text", "note", "link")):
        return True
    if after["store"] == before["store"]:
        return False
    return not (auto_store and after["store"] is not None)


def set_wish_store(idea: Idea, name: str) -> Idea:
    """„+ Búð“ á eigin ósk (línan „Ég“ og óskabeiðnin)."""
    store = stores.get_or_create_store(idea.gift.season.household, name[:100])
    if store and store.pk != idea.store_id:
        idea.store = store
        idea.save(update_fields=["store"])
        idea.copies.update(source_changed=True)
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
