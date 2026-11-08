"""Raunverð og rukkun; dæmin eru úr hegðun gamla appsins (gjafalistinn/index.html)."""

import datetime

import pytest

from apps.gifts.services import billing, gifts, summary
from apps.gifts.services.pricing import actual_price, giver_breakdown, split_shares

from .factories import GiftFactory, IdeaFactory, PersonFactory, SeasonFactory, giver

pytestmark = pytest.mark.django_db


@pytest.fixture
def season():
    return SeasonFactory(year=2026, budget=160000)


@pytest.fixture
def amma(season):
    return PersonFactory(household=season.household, name="Amma Jóa")


def test_unbought_gift_has_no_price(season):
    gift = GiftFactory(season=season, manual_price=5000)
    assert actual_price(gift) is None


def test_manual_price_when_ideas_have_no_price(season):
    gift = GiftFactory(season=season, bought=True, manual_price=5000)
    IdeaFactory(gift=gift, picked=True)
    assert actual_price(gift) == 5000


def test_picked_idea_prices_override_manual(season):
    gift = GiftFactory(season=season, bought=True, manual_price=9999)
    IdeaFactory(gift=gift, picked=True, price=2000)
    IdeaFactory(gift=gift, picked=True, price=990)
    IdeaFactory(gift=gift, picked=False, price=50000)
    assert actual_price(gift) == 2990


def test_bought_for_other_only_is_outside_actual_price(season, amma):
    """Púsl frá Ömmu Jóu keypt fyrir hana: ekki okkar eyðsla, raunverð „—“."""
    gift = GiftFactory(season=season, bought=True)
    puzzle = IdeaFactory(gift=gift, text="púsl", picked=True, price=3500, for_other=True)
    giver(puzzle, amma)
    assert actual_price(gift) is None


def test_mixed_gift(season, amma):
    """Bók frá okkur 2.000 + púsl frá Ömmu Jóu 3.500 → raunverð 2.000."""
    gift = GiftFactory(season=season, bought=True)
    IdeaFactory(gift=gift, text="bók", picked=True, price=2000)
    puzzle = IdeaFactory(gift=gift, text="púsl", picked=True, price=3500, for_other=True)
    giver(puzzle, amma)
    assert actual_price(gift) == 2000
    assert giver_breakdown(gift) == [(None, 2000)]


def test_equal_split_between_givers(season, amma):
    afi = PersonFactory(household=season.household, name="Afi")
    idea = IdeaFactory(gift=GiftFactory(season=season), price=5000, for_other=True, picked=True)
    giver(idea, amma)
    giver(idea, afi)
    shares = split_shares(idea)
    assert [(p.name, n) for p, n in shares.givers] == [("Amma Jóa", 2500), ("Afi", 2500)]
    assert shares.ours == 0


def test_rounding_goes_to_first_giver(season):
    idea = IdeaFactory(gift=GiftFactory(season=season), price=1001, for_other=True)
    for name in ["A", "B", "C"]:
        giver(idea, PersonFactory(household=season.household, name=name))
    assert [n for _, n in split_shares(idea).givers] == [335, 333, 333]


def test_explicit_share_leaves_rest_to_us(season, amma):
    """6.000 kr. gjöf, Amma Jóa greiðir 4.000 → 2.000 í okkar raunverð."""
    gift = GiftFactory(season=season, bought=True)
    idea = IdeaFactory(gift=gift, picked=True, price=6000, for_other=True)
    giver(idea, amma, share=4000)
    shares = split_shares(idea)
    assert [(p.name, n) for p, n in shares.givers] == [("Amma Jóa", 4000)]
    assert shares.ours == 2000
    assert actual_price(gift) == 2000


def test_gift_from_givers_not_billed_shows_breakdown(season):
    """Gjöf „frá börnunum“ (ekki keypt fyrir annan) er okkar eyðsla en sundurliðuð."""
    born = PersonFactory(household=season.household, name="börnin")
    gift = GiftFactory(season=season, bought=True)
    giver(IdeaFactory(gift=gift, picked=True, price=5500), born)
    assert actual_price(gift) == 5500
    assert giver_breakdown(gift) == [(born, 5500)]


def test_no_breakdown_without_givers(season):
    gift = GiftFactory(season=season, bought=True)
    IdeaFactory(gift=gift, picked=True, price=1000)
    assert giver_breakdown(gift) is None


def test_billing_groups_by_person(season, amma):
    hugi = GiftFactory(
        season=season, person=PersonFactory(household=season.household, name="Hugi"), bought=True
    )
    una = GiftFactory(
        season=season, person=PersonFactory(household=season.household, name="Una"), bought=True
    )
    giver(IdeaFactory(gift=hugi, text="púsl", picked=True, price=3500, for_other=True), amma)
    giver(IdeaFactory(gift=una, text="púsl", picked=True, price=3500, for_other=True), amma)
    giver(IdeaFactory(gift=una, text="bók", picked=False, for_other=True), amma)  # ekki keypt enn

    [payer] = billing.season_billing(season)
    assert payer.person == amma
    assert len(payer.lines) == 3
    assert payer.total == 7000
    assert payer.unpaid == 7000
    pending = [line for line in payer.lines if line.pending]
    assert len(pending) == 1 and pending[0].amount is None  # „Verð vantar“

    assert billing.mark_all_paid(season, amma) == 2
    [payer] = billing.season_billing(season)
    assert payer.unpaid == 0
    assert all(line.paid for line in payer.bought_lines)


def test_each_giver_pays_own_share(season, amma):
    afi = PersonFactory(household=season.household, name="Afi")
    idea = IdeaFactory(gift=GiftFactory(season=season, bought=True), picked=True, price=5000, for_other=True)
    giver(idea, amma, paid=True)
    giver(idea, afi)
    payers = {p.person.name: p for p in billing.season_billing(season)}
    assert payers["Amma Jóa"].unpaid == 0 and payers["Amma Jóa"].total == 2500
    assert payers["Afi"].unpaid == 2500
    # Sá sem skuldar raðast fyrst
    assert [p.person.name for p in billing.season_billing(season)] == ["Afi", "Amma Jóa"]


def test_deleted_gifts_are_not_billed(season, amma):
    gift = GiftFactory(season=season, bought=True)
    giver(IdeaFactory(gift=gift, picked=True, price=3500, for_other=True), amma)
    gifts.soft_delete(gift)
    assert billing.season_billing(season) == []


def test_season_summary(season, amma):
    a = GiftFactory(season=season, plan=5000, bought=True)
    IdeaFactory(gift=a, picked=True, price=2000)
    giver(IdeaFactory(gift=a, picked=True, price=3500, for_other=True), amma)
    GiftFactory(season=season, plan=8000)
    s = summary.season_summary(season, today=datetime.date(2026, 11, 3))
    assert (s.count, s.done, s.todo) == (2, 1, 1)
    assert s.spent == 2000
    assert s.owed == 3500
    assert s.total_plan == 13000
    assert s.planned_left == 8000
    assert s.bought_plan == 5000 and s.bought_spent == 2000
    assert s.left == 158000
    assert s.unallocated == 147000
    assert s.days_left == 51
    assert s.gifts_per_day == pytest.approx(1 / 51)


def test_season_summary_without_budget_compares_to_plan(season):
    season.budget = 0
    season.save()
    a = GiftFactory(season=season, plan=4000, bought=True)
    IdeaFactory(gift=a, picked=True, price=3000)
    GiftFactory(season=season, plan=6000)
    s = summary.season_summary(season)
    assert not s.has_budget
    assert s.target == 10000
    assert s.spent_pct == 30
    assert s.left == 7000
