import datetime

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.gifts.models import Gift, IdeaGiver, Person, Store
from apps.gifts.services import gifts, people, seasons, shopping, stores
from apps.households.models import Household

from .factories import (
    GiftFactory,
    HouseholdFactory,
    IdeaFactory,
    MembershipFactory,
    PersonFactory,
    SeasonFactory,
    StoreFactory,
    UserFactory,
    giver,
)

pytestmark = pytest.mark.django_db


# ---------- Búðir ----------


def test_store_spellings_are_the_same_store():
    household = HouseholdFactory()
    first = stores.get_or_create_store(household, "Elkó")
    assert stores.get_or_create_store(household, "ELKO") == first
    assert stores.get_or_create_store(household, "elko").name == "Elkó"
    assert stores.get_or_create_store(household, "  ") is None


def test_rename_store():
    epal = StoreFactory(name="Epal")
    stores.set_locations(epal, "Kringlan")
    renamed = stores.rename_or_merge(epal, "EPAL hönnun")
    assert renamed.pk == epal.pk and renamed.name == "EPAL hönnun"
    assert [loc.name for loc in renamed.locations.all()] == ["Kringlan"]


def test_merge_stores_moves_ideas_gifts_and_locations():
    household = HouseholdFactory()
    epal = StoreFactory(household=household, name="Epal")
    hagkaup = StoreFactory(household=household, name="Hagkaup")
    stores.set_locations(epal, ["Kringlan"])
    stores.set_locations(hagkaup, ["Smáralind"])
    season = SeasonFactory(household=household)
    idea = IdeaFactory(gift=GiftFactory(season=season), store=epal)
    legacy_gift = GiftFactory(season=season)
    legacy_gift.stores.add(epal)

    assert stores.find_conflict(epal, "hagkaup") == hagkaup
    result = stores.rename_or_merge(epal, "hagkaup")

    assert result == hagkaup
    assert not Store.objects.filter(pk=epal.pk).exists()
    idea.refresh_from_db()
    assert idea.store == hagkaup
    assert list(legacy_gift.stores.all()) == [hagkaup]
    assert sorted(loc.name for loc in hagkaup.locations.all()) == ["Kringlan", "Smáralind"]


def test_case_only_rename_keeps_store():
    elko = StoreFactory(name="Elko")
    assert stores.rename_or_merge(elko, "ELKO").name == "ELKO"
    assert Store.objects.count() == 1


def test_stores_of_prefers_idea_stores():
    household = HouseholdFactory()
    gift = GiftFactory(season=SeasonFactory(household=household))
    gift.stores.add(StoreFactory(household=household, name="Gömul"))
    assert [s.name for s in stores.stores_of(gift)] == ["Gömul"]
    IdeaFactory(gift=gift, store=StoreFactory(household=household, name="Epal"))
    assert [s.name for s in stores.stores_of(gift)] == ["Epal"]


# ---------- Fólk ----------


def test_new_giver_is_hidden_as_recipient():
    season = SeasonFactory()
    hugi = GiftFactory(season=season, person=PersonFactory(household=season.household, name="Hugi"))
    amma = people.find_or_create(season.household, "Amma Jóa")
    giver(IdeaFactory(gift=hugi), amma)

    assert people.find_or_create(season.household, "amma jóa") == amma
    assert list(Person.objects.recipients()) == [hugi.person]
    assert list(Person.objects.givers()) == [amma]
    # Gefandi verður sjálfkrafa viðtakandi ef honum er gefin gjöf
    GiftFactory(season=season, person=amma)
    assert set(Person.objects.recipients()) == {hugi.person, amma}


def test_search_prefers_prefix_and_stays_in_household():
    household = HouseholdFactory()
    for name in ["Una Eydís", "Hugi", "Una Elínóra", "Elsa Særún"]:
        PersonFactory(household=household, name=name)
    PersonFactory(name="Una úr öðru heimili")
    assert [p.name for p in people.search(household, "una")] == ["Una Elínóra", "Una Eydís"]
    assert [p.name for p in people.search(household, "el")][:1] == ["Elsa Særún"]
    assert len(people.search(household, "")) == 4


def test_rename_person_requires_confirmation_to_merge():
    household = HouseholdFactory()
    a = PersonFactory(household=household, name="Amma")
    PersonFactory(household=household, name="Amma Jóa")
    with pytest.raises(ValueError):
        people.rename(a, "amma jóa")
    assert people.rename(a, "Amma Gunna").name == "Amma Gunna"


def test_merge_people_combines_gifts_and_giver_links():
    household = HouseholdFactory()
    season = SeasonFactory(household=household)
    source = PersonFactory(household=household, name="Amma")
    target = PersonFactory(household=household, name="Amma Jóa")
    src_gift = GiftFactory(season=season, person=source, plan=3000)
    IdeaFactory(gift=src_gift, text="sokkar")
    dst_gift = GiftFactory(season=season, person=target, plan=2000)
    shared = IdeaFactory(gift=GiftFactory(season=season))
    giver(shared, source)
    giver(shared, target)
    other = IdeaFactory(gift=GiftFactory(season=season))
    giver(other, source)

    people.merge(source, target)

    assert not Person.objects.filter(pk=source.pk).exists()
    dst_gift.refresh_from_db()
    assert [i.text for i in dst_gift.ideas.all()] == ["sokkar"]
    assert dst_gift.plan == 5000
    assert IdeaGiver.objects.filter(idea=shared).count() == 1
    assert IdeaGiver.objects.get(idea=other).person == target


# ---------- Gjafir ----------


def test_pick_and_unpick_idea_drives_bought():
    gift = GiftFactory()
    a, b = IdeaFactory(gift=gift), IdeaFactory(gift=gift)
    gifts.pick_idea(a, 2500)
    gift.refresh_from_db()
    assert gift.bought and a.price == 2500
    gifts.pick_idea(b)
    gifts.unpick_idea(a)
    gift.refresh_from_db()
    assert gift.bought
    gifts.remove_idea(b)
    gift.refresh_from_db()
    assert not gift.bought


def test_mark_bought_adds_amounts():
    gift = GiftFactory()
    gifts.mark_bought(gift)
    assert gifts.needs_price(gift)
    gifts.mark_bought(gift, 4000)
    gifts.mark_bought(gift, 990)
    assert gift.manual_price == 4990 and not gifts.needs_price(gift)
    gifts.mark_unbought(gift)
    assert gift.manual_price is None


def test_set_givers_keeps_payment_state_and_clears_for_other():
    household = HouseholdFactory()
    amma = PersonFactory(household=household, name="Amma")
    afi = PersonFactory(household=household, name="Afi")
    idea = IdeaFactory(gift=GiftFactory(season=SeasonFactory(household=household)), for_other=True)
    giver(idea, amma, paid=True)
    gifts.set_givers(idea, [amma, afi])
    assert IdeaGiver.objects.get(idea=idea, person=amma).paid
    assert IdeaGiver.objects.filter(idea=idea).count() == 2
    gifts.set_givers(idea, [])
    idea.refresh_from_db()
    assert not idea.for_other


def test_sync_ideas_keeps_state_of_unchanged_ideas():
    gift = GiftFactory()
    sokkar = IdeaFactory(gift=gift, text="sokkar", picked=True, price=2000)
    IdeaFactory(gift=gift, text="spil")
    gifts.sync_ideas(gift, ["Sokkar", "bók"])
    texts = [(i.text, i.picked, i.price) for i in gift.ideas.all()]
    assert texts == [("Sokkar", True, 2000), ("bók", False, None)]
    assert gift.ideas.get(text="Sokkar").pk == sokkar.pk


def test_soft_delete_and_restore():
    gift = GiftFactory()
    gifts.soft_delete(gift)
    assert not Gift.objects.alive().exists()
    gifts.restore(gift)
    assert Gift.objects.alive().get() == gift


def test_restore_refuses_duplicate():
    gift = GiftFactory()
    gifts.soft_delete(gift)
    GiftFactory(season=gift.season, person=gift.person)
    with pytest.raises(ValueError):
        gifts.restore(gift)


def test_only_one_live_gift_per_person_and_year():
    gift = GiftFactory()
    with pytest.raises(IntegrityError):
        GiftFactory(season=gift.season, person=gift.person)


def test_gift_text():
    household = HouseholdFactory()
    gift = GiftFactory(season=SeasonFactory(household=household))
    IdeaFactory(gift=gift, text="bók")
    giver(IdeaFactory(gift=gift, text="púsl"), PersonFactory(household=household, name="Ömmu Jóu"))
    assert gifts.gift_text(gift) == "bók, púsl (frá Ömmu Jóu)"
    gifts.pick_idea(gift.ideas.get(text="bók"))
    assert gifts.gift_text(gift) == "bók"


# ---------- Ár ----------


def test_new_season_copies_christmas_recipients():
    household = HouseholdFactory()
    old = SeasonFactory(household=household, year=2025, budget=150000)
    GiftFactory(season=old, person=PersonFactory(household=household, name="Hugi"), plan=15000)
    GiftFactory(season=old, person=PersonFactory(household=household, name="Mahsa", give_christmas=False))
    new = seasons.new_season(household, 2026, copy_from=old)
    assert new.budget == 150000
    assert [(g.person.name, g.plan, g.bought) for g in new.gifts.all()] == [("Hugi", 15000, False)]
    # Ár sem er til er ekki afritað aftur
    assert seasons.new_season(household, 2026, copy_from=old).gifts.count() == 1


def test_history_newest_first():
    household = HouseholdFactory()
    hugi = PersonFactory(household=household, name="Hugi")
    for year, text in [(2024, "legó"), (2025, "OZ miði")]:
        IdeaFactory(
            gift=GiftFactory(season=SeasonFactory(household=household, year=year), person=hugi), text=text
        )
    assert [(h.year, h.text) for h in seasons.history(hugi)] == [(2025, "OZ miði"), (2024, "legó")]
    assert [h.year for h in seasons.history(hugi, before_year=2025)] == [2024]


def test_past_season_is_locked_until_unlocked():
    now = timezone.make_aware(datetime.datetime(2026, 11, 3, 12))
    past = SeasonFactory(year=2025)
    assert past.is_locked(now)
    assert not SeasonFactory(year=2026).is_locked(now)
    past.unlocked_until = now + datetime.timedelta(hours=1)
    assert not past.is_locked(now)


# ---------- Verslanir ----------


def test_shopping_by_store_and_location():
    household = HouseholdFactory()
    season = SeasonFactory(household=household)
    epal = StoreFactory(household=household, name="Epal")
    elko = StoreFactory(household=household, name="Elko")
    stores.set_locations(epal, ["Kringlan", "Smáralind"])
    stores.set_locations(elko, ["Smáralind"])
    a = GiftFactory(season=season, plan=5000)
    IdeaFactory(gift=a, store=epal)
    IdeaFactory(gift=a, store=elko)
    b = GiftFactory(season=season, plan=3000)  # engin búð
    IdeaFactory(gift=GiftFactory(season=season, bought=True), store=epal)  # keypt: ekki með

    groups = shopping.by_store(season)
    assert [(g.store.name if g.store else None, len(g.items)) for g in groups] == [
        ("Elko", 1),
        ("Epal", 1),
        (None, 1),
    ]
    assert groups[-1].items[0].gift == b and groups[-1].items[0].idea is None
    assert groups[-1].plan == 3000

    locations = shopping.by_location(season)
    assert [
        (g.location.name if g.location else None, [s.store.name if s.store else None for s in g.stores])
        for g in locations
    ] == [("Kringlan", ["Epal"]), ("Smáralind", ["Elko", "Epal"]), (None, [None])]


def test_shopping_lists_each_open_idea():
    household = HouseholdFactory()
    season = SeasonFactory(household=household)
    epal = StoreFactory(household=household, name="Epal")
    gift = GiftFactory(season=season, plan=9000)
    book = IdeaFactory(gift=gift, text="bók", store=epal, price=4000)
    mug = IdeaFactory(gift=gift, text="bolli", store=epal)
    IdeaFactory(gift=gift, text="spil", store=epal, picked=True)  # keypt: ekki með
    gift.bought = True
    gift.save()
    # Gjöf merkt keypt á listanum án keyptrar hugmyndar: öll farin
    manual = GiftFactory(season=season, bought=True)
    IdeaFactory(gift=manual, store=epal)

    [group] = shopping.by_store(season)
    assert [i.idea for i in group.items] == [book, mug]
    assert [i.amount for i in group.items] == [4000, None]
    assert group.gift_count == 1


def test_only_open_idea_carries_gift_plan():
    season = SeasonFactory()
    gift = GiftFactory(season=season, plan=7000)
    IdeaFactory(gift=gift)
    [group] = shopping.by_store(season)
    assert group.items[0].amount == 7000


# ---------- Aðgangur ----------


def test_household_for_member():
    membership = MembershipFactory()
    HouseholdFactory()
    assert list(Household.objects.for_member(membership.user)) == [membership.household]
    assert not Household.objects.for_member(UserFactory()).exists()
