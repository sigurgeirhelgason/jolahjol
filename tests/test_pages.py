"""Áfangi 4: Eftir búðum, Fólk & Fjölskylda, Rukkun."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.gifts.models import Gift, IdeaGiver, Location, Person
from apps.gifts.services import stores
from apps.gifts.services.billing import bill_text, season_billing
from apps.households.models import Membership
from tests.factories import (
    GiftFactory,
    IdeaFactory,
    MembershipFactory,
    PersonFactory,
    SeasonFactory,
    StoreFactory,
    giver,
)

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def member():
    return MembershipFactory(role=Membership.Role.OWNER)


@pytest.fixture
def home(member):
    return member.household


@pytest.fixture
def season(home):
    return SeasonFactory(household=home, year=YEAR)


@pytest.fixture
def client(client, member):
    client.force_login(member.user)
    return client


def url(name, *args):
    return reverse(f"gifts:{name}", args=args)


def _gift(season, name, group="born", **kwargs):
    person = PersonFactory(household=season.household, name=name, group=group)
    return GiftFactory(season=season, person=person, **kwargs)


def _for_other(gift, price, *names, picked=True):
    idea = IdeaFactory(gift=gift, text="púsl", price=price, picked=picked, for_other=True)
    for name in names:
        person = Person.objects.filter(household=gift.season.household, name=name).first()
        giver(idea, person or PersonFactory(household=gift.season.household, name=name))
    if picked:
        Gift.objects.filter(pk=gift.pk).update(bought=True)
    return idea


# ---------- Flipar og ársval ----------


def test_tabs_and_year_select_keep_the_page(client, home, season):
    SeasonFactory(household=home, year=YEAR - 1)
    html = client.get(url("billing", home.slug, YEAR)).text
    for name in ("season", "shop", "people", "billing"):
        assert url(name, home.slug, YEAR) in html
    assert f'value="{url("billing", home.slug, YEAR - 1)}"' in html  # ársval heldur Rukkun
    assert 'data-page="rukkun"' in html


@pytest.mark.parametrize(("route", "target"), [("shop_now", "shop"), ("people_now", "people")])
def test_page_shortcuts_redirect_to_this_year(client, home, season, route, target):
    assert client.get(url(route, home.slug)).url == url(target, home.slug, YEAR)


# ---------- Eftir búðum ----------


def test_shop_groups_unbought_gifts_by_store_and_location(client, home, season):
    elko = StoreFactory(household=home, name="Elko")
    stores.set_locations(elko, "Kringlan, Smáralind")
    IdeaFactory(gift=_gift(season, "Hugi", plan=15000), text="legó", store=elko)
    _gift(season, "Una")  # engin búð
    _gift(season, "Óskar", bought=True)  # keypt: ekki á innkaupalista

    by_store = client.get(url("shop", home.slug, YEAR)).text
    assert "Elko" in by_store and "Búð óákveðin" in by_store and "15.000 kr." in by_store
    assert "Óskar" not in by_store

    by_loc = client.get(url("shop", home.slug, YEAR) + "?eftir=stadsetningu").text
    assert by_loc.count(">Elko<") == 2  # undir Kringlunni og Smáralind
    assert "Staðsetning óákveðin" in by_loc


def test_shop_says_all_bought(client, home, season):
    _gift(season, "Hugi", bought=True)
    assert "Allar gjafir eru keyptar" in client.get(url("shop", home.slug, YEAR)).text


def test_marking_bought_from_shop_refreshes_the_page(client, home, season):
    gift = _gift(season, "Hugi")
    IdeaFactory(gift=gift, picked=True, price=1000)
    response = client.post(url("bought", home.slug, gift.pk), {"bought": "on"}, HTTP_X_PAGE="budir", **HX)
    gift.refresh_from_db()
    assert gift.bought
    assert "refreshPage" in response["HX-Trigger"]
    assert response["HX-Reswap"] == "none"


# ---------- Fólk ----------


def test_people_page_shows_recipients_and_birthdays_not_givers(client, home, season):
    gift = _gift(season, "Hugi")
    IdeaFactory(gift=gift, text="legó", picked=True)
    Gift.objects.filter(pk=gift.pk).update(bought=True)
    PersonFactory(household=home, name="Afi", group="fjolskylda", give_christmas=False, give_birthday=True)
    PersonFactory(household=home, name="Amma Jóa")  # bara gefandi
    html = client.get(url("people", home.slug, YEAR)).text
    assert "Hugi" in html and "Afi" in html and "Amma Jóa" not in html
    assert f"<b>{YEAR}</b> legó" in html
    assert "Engin jólagjöf" in html and "Afmælisgjöf" in html


def test_changing_group_on_people_page(client, home, season):
    person = _gift(season, "Hugi").person
    response = client.post(
        url("person_group", home.slug, person.pk), {"group": "vinir"}, HTTP_X_PAGE="folk", **HX
    )
    person.refresh_from_db()
    assert person.group == "vinir"
    assert "refreshPage" in response["HX-Trigger"]


# ---------- Rukkun ----------


def test_billing_page_lists_payers_with_totals(client, home, season):
    _for_other(_gift(season, "Hugi"), 6000, "Amma Jóa", "Afi")
    _for_other(_gift(season, "Una"), 2000, "Afi", picked=False)  # ekki keypt enn
    html = client.get(url("billing", home.slug, YEAR)).text
    assert "Amma Jóa" in html and "Afi" in html
    assert "3.000 kr." in html  # jöfn skipting
    assert "ekki keypt enn" in html
    assert "Ógreitt samtals <strong>6.000 kr.</strong> frá 2 aðilum" in html
    assert '<span class="nav-count"' in html


def test_billing_is_empty_without_bought_for_others(client, home, season):
    _gift(season, "Hugi")
    assert "Ekkert til að rukka" in client.get(url("billing", home.slug, YEAR)).text


def test_marking_one_giver_paid_and_all_paid(client, home, season):
    idea = _for_other(_gift(season, "Hugi"), 6000, "Amma Jóa", "Afi")
    amma = IdeaGiver.objects.get(idea=idea, person__name="Amma Jóa")
    client.post(url("giver_paid", home.slug, amma.pk), {"paid": "on"}, HTTP_X_PAGE="rukkun", **HX)
    amma.refresh_from_db()
    assert amma.paid
    assert not IdeaGiver.objects.get(idea=idea, person__name="Afi").paid

    afi = Person.objects.get(name="Afi")
    client.post(url("payer_all_paid", home.slug, YEAR, afi.pk), HTTP_X_PAGE="rukkun", **HX)
    assert all(IdeaGiver.objects.filter(idea=idea).values_list("paid", flat=True))
    html = client.get(url("billing", home.slug, YEAR)).text
    assert "Allt greitt" in html and '<span class="nav-count"' not in html


def test_paid_can_be_marked_in_locked_year(client, home):
    past = SeasonFactory(household=home, year=YEAR - 1)
    idea = _for_other(_gift(past, "Hugi"), 1000, "Afi")
    link = idea.giver_links.get()
    assert client.post(url("giver_paid", home.slug, link.pk), {"paid": "on"}, **HX).status_code == 200


def test_bill_text_lists_unpaid_lines(season):
    _for_other(_gift(season, "Hugi"), 5000, "Afi")
    payer = season_billing(season)[0]
    text = bill_text(payer, YEAR)
    assert text.startswith(f"Hæ Afi! Hér er yfirlit yfir jólagjafirnar {YEAR}:")
    assert "• púsl handa Hugi: 5.000 kr." in text and text.endswith("Samtals: 5.000 kr.")


def test_billing_actions_are_scoped_to_household(client, home):
    other_idea = _for_other(_gift(SeasonFactory(year=YEAR), "Stranger"), 1000, "X")
    link = other_idea.giver_links.get()
    assert client.post(url("giver_paid", home.slug, link.pk), {"paid": "on"}, **HX).status_code == 404
    link.refresh_from_db()
    assert not link.paid
    assert Location.objects.count() == 0
