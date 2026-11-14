"""Augað við nafnið: gjafir einstaklings óskýrar á þessu tæki (vafrakakan `faldir`)."""

import datetime

import pytest
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.gifts.context_processors import HIDDEN_COOKIE, hidden_people
from apps.gifts.templatetags.gifts import peek_label
from apps.households.models import Membership
from tests.factories import GiftFactory, IdeaFactory, MembershipFactory, PersonFactory, SeasonFactory

pytestmark = pytest.mark.django_db

THIS_YEAR = timezone.localdate().year
HX = {"HTTP_HX_REQUEST": "true"}


def url(name, *args):
    return reverse(f"gifts:{name}", args=args)


@pytest.fixture
def member():
    return MembershipFactory(role=Membership.Role.OWNER)


@pytest.fixture
def home(member):
    return member.household


@pytest.fixture
def season(home):
    return SeasonFactory(household=home, year=THIS_YEAR)


@pytest.fixture
def client(client, member):
    client.force_login(member.user)
    return client


@pytest.fixture
def kona(home):
    return PersonFactory(household=home, name="Kona", group="fjolskylda")


@pytest.fixture
def gift(season, kona):
    gift = GiftFactory(season=season, person=kona, plan=20000)
    IdeaFactory(gift=gift, text="hálsmen")
    return gift


def hide(client, *people):
    client.cookies[HIDDEN_COOKIE] = ".".join(str(p.pk) for p in people)


def row_tag(gift, hidden=False):
    """Upphaf <div> línunnar; id er síðast svo próf geti séð hvort hx-swap-oob fylgir."""
    cls = "row gift peek-off" if hidden else "row gift"
    label = peek_label(gift.person_id)
    return f'class="{cls}" data-peek="{gift.person_id}" data-peek-label="{label}" id="gift-{gift.pk}"'


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", set()), ("3.17", {3, 17}), ("3..x.17;", {3}), ("abc", set())],
)
def test_cookie_is_parsed_leniently(raw, expected):
    request = RequestFactory().get("/")
    request.COOKIES[HIDDEN_COOKIE] = raw
    assert hidden_people(request)["hidden_people"] == expected


def test_rows_are_visible_and_have_an_eye_by_default(client, home, gift):
    html = client.get(url("season", home.slug, THIS_YEAR)).text
    assert f'data-peek="{gift.person_id}"' in html
    assert f'data-peek-toggle="{gift.person_id}" aria-pressed="false"' in html
    assert "peek-off" not in html


def test_hidden_person_is_rendered_blurred_but_others_are_not(client, home, season, gift):
    other = GiftFactory(season=season, person=PersonFactory(household=home, name="Barn", group="born"))
    hide(client, gift.person)
    html = client.get(url("season", home.slug, THIS_YEAR)).text
    assert row_tag(gift, hidden=True) in html
    assert f'data-peek-toggle="{gift.person_id}" aria-pressed="true"' in html
    assert row_tag(other) in html


def test_row_stays_hidden_after_htmx_update(client, home, gift):
    """Hugmynd bætt við á meðan falið er: nýja línan kemur frá þjóninum, líka falin."""
    hide(client, gift.person)
    html = client.post(url("idea_add", home.slug, gift.pk), {"text": "bók"}, **HX).text
    assert row_tag(gift, hidden=True) in html


def test_shop_people_dialog_and_birthdays_respect_it(client, home, season, kona, gift):
    old = GiftFactory(season=SeasonFactory(household=home, year=THIS_YEAR - 1), person=kona, bought=True)
    IdeaFactory(gift=old, text="trefill", picked=True)
    kona.birthday = datetime.date(1990, 1, 1)
    kona.give_birthday = True
    kona.save()
    hide(client, kona)

    assert 'class="shop-person peek-off"' in client.get(url("shop", home.slug, THIS_YEAR)).text
    assert 'class="person peek-off"' in client.get(url("people", home.slug, THIS_YEAR)).text
    assert 'class="past peek-off"' in client.get(url("person", home.slug, kona.pk), **HX).text
    assert "bday-card peek-off" in client.get(url("birthdays", home.slug)).text
