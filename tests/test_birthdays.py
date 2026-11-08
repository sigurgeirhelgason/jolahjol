"""Áfangi 5b: afmælisgjafir."""

import datetime

import pytest
from django.core import mail
from django.urls import reverse

from apps.gifts import listing
from apps.gifts.models import BirthdayReminder, Gift, Occasion, Person, Season
from apps.gifts.services import birthdays
from apps.gifts.services.seasons import new_season
from apps.households.models import Membership
from tests.factories import GiftFactory, IdeaFactory, MembershipFactory, PersonFactory, SeasonFactory

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 12)
HX = {"HTTP_HX_REQUEST": "true", "HTTP_X_PAGE": "afmaeli"}


@pytest.fixture
def member():
    return MembershipFactory(role=Membership.Role.OWNER)


@pytest.fixture
def home(member):
    return member.household


@pytest.fixture
def client(client, member):
    client.force_login(member.user)
    return client


def person(home, name, birthday, **kwargs):
    return PersonFactory(household=home, name=name, birthday=birthday, give_birthday=True, **kwargs)


def url(name, *args):
    return reverse(f"gifts:{name}", args=args)


# ---------- Reglur ----------


@pytest.mark.parametrize(
    ("birthday", "today", "expected"),
    [
        (datetime.date(2014, 11, 18), TODAY, datetime.date(2026, 11, 18)),
        (datetime.date(2014, 11, 12), TODAY, datetime.date(2026, 11, 12)),  # í dag
        (datetime.date(2014, 1, 5), TODAY, datetime.date(2027, 1, 5)),  # liðið í ár → næsta ár
        (datetime.date(2016, 2, 29), datetime.date(2026, 3, 1), datetime.date(2027, 2, 28)),  # hlaupár
    ],
)
def test_next_birthday(birthday, today, expected):
    assert birthdays.next_birthday(birthday, today) == expected


def test_overview_covers_next_12_months_with_age_round_and_christmas(home):
    person(home, "Hugi", datetime.date(2014, 11, 18))
    person(home, "Áslaug", datetime.date(1986, 12, 19))
    person(home, "Óskar", datetime.date(2018, 12, 24))
    person(home, "Pabbi", datetime.date(1960, 1, 12))
    PersonFactory(household=home, name="Án afmælisgjafar", birthday=datetime.date(2000, 11, 20))
    PersonFactory(household=home, name="Vantar dag", give_birthday=True)

    ov = birthdays.overview(home, TODAY)
    assert [m.key for m in ov.months][:3] == ["2026-11", "2026-12", "2027-01"]
    assert len(ov.months) == 12
    names = [e.person.name for e in ov.entries]
    assert names == ["Hugi", "Áslaug", "Óskar", "Pabbi"]
    hugi, aslaug, oskar, pabbi = ov.entries
    assert (hugi.age, hugi.days, hugi.urgent) == (12, 6, True)
    assert aslaug.age == 40 and aslaug.round_birthday
    assert oskar.near_christmas and not hugi.near_christmas
    assert pabbi.date == datetime.date(2027, 1, 12)
    assert [p.name for p in ov.missing_date] == ["Vantar dag"]
    assert ov.next_up == hugi


def test_birthday_earlier_this_month_goes_to_same_month_next_year(client, home):
    """Afmæli 3. nóv þegar í dag er 12. nóv er í nóv næsta ár, 13. mánuði gluggans."""
    person(home, "Lilja", datetime.date(2010, 11, 3))
    ov = birthdays.overview(home, TODAY)
    assert len(ov.months) == 13
    assert ov.months[-1].key == "2027-11"
    assert [e.person.name for e in ov.months[-1].entries] == ["Lilja"]
    assert ov.entries[0].days == 356

    resp = client.get(url("birthdays", home.slug))
    assert resp.status_code == 200


def test_birthday_gift_is_found_in_the_year_of_the_birthday(home):
    pabbi = person(home, "Pabbi", datetime.date(1960, 1, 12))
    gift = birthdays.ensure_gift(pabbi, 2027)
    assert gift.occasion == Occasion.BIRTHDAY and gift.season.year == 2027
    assert birthdays.ensure_gift(pabbi, 2027) == gift
    assert birthdays.overview(home, TODAY).entries[0].gift == gift


def test_person_can_have_christmas_and_birthday_gift_same_year(home):
    hugi = person(home, "Hugi", datetime.date(2014, 11, 18))
    season = SeasonFactory(household=home, year=2026)
    GiftFactory(season=season, person=hugi)
    birthdays.ensure_gift(hugi, 2026)
    assert Gift.objects.alive().filter(person=hugi, season=season).count() == 2


def test_distribution_counts_months(home):
    person(home, "A", datetime.date(2000, 12, 1))
    person(home, "B", datetime.date(2001, 12, 9))
    person(home, "C", datetime.date(2002, 4, 3))
    dist = birthdays.distribution(home)
    assert dist[11] == 2 and dist[3] == 1 and sum(dist) == 3


# ---------- Jólasíður sjá ekki afmælisgjafir ----------


def test_christmas_pages_ignore_birthday_gifts(home):
    season = SeasonFactory(household=home, year=2026)
    hugi = person(home, "Hugi", datetime.date(2014, 11, 18))
    IdeaFactory(gift=birthdays.ensure_gift(hugi, 2026), text="afmælislegó")
    gl = listing.build_list(season, listing.ListState())
    assert gl.summary.count == 0
    assert all(not s.rows for s in gl.sections)


def test_new_season_copies_christmas_into_year_created_by_a_birthday(home):
    old = SeasonFactory(household=home, year=2026, budget=100000)
    GiftFactory(season=old, person=PersonFactory(household=home, name="Mamma"), plan=8000)
    pabbi = person(home, "Pabbi", datetime.date(1960, 1, 12))
    birthdays.ensure_gift(pabbi, 2027)  # árið 2027 verður til vegna afmælis
    season = new_season(home, 2027, copy_from=old)
    assert [g.person.name for g in season.gifts.christmas()] == ["Mamma"]
    assert season.budget == 100000
    assert season.gifts.birthdays().count() == 1


# ---------- Síðan og aðgerðir ----------


def test_page_renders_cards_pills_and_rail(client, home):
    person(home, "Hugi", datetime.date(2014, 11, 18))
    html = client.get(url("birthdays", home.slug)).text
    assert 'data-page="afmaeli"' in html
    assert "Hugi" in html and "verður" in html
    assert "Afmælisdreifing" in html and "Gjafahugmyndabanki" in html
    assert "Áminningar í tölvupósti" in html
    assert Season.objects.count() == 0  # að skoða síðuna býr ekki til ár


def test_actions_create_gift_and_reuse_christmas_rules(client, home):
    hugi = person(home, "Hugi", datetime.date(2014, 11, 18))
    year = birthdays.next_birthday(hugi.birthday, datetime.date.today()).year
    client.post(url("birthday_action", home.slug, hugi.pk, year, "hugmynd"), {"text": "legó, bók"}, **HX)
    gift = Gift.objects.get(person=hugi, occasion=Occasion.BIRTHDAY)
    assert [i.text for i in gift.ideas.all()] == ["legó", "bók"]

    response = client.post(
        url("birthday_action", home.slug, hugi.pk, year, "aaetlun"), {"plan": "12.000"}, **HX
    )
    assert "refreshPage" in response["HX-Trigger"]
    gift.refresh_from_db()
    assert gift.plan == 12000

    priced = client.post(url("birthday_action", home.slug, hugi.pk, year, "keypt"), {"bought": "on"}, **HX)
    assert "Hvað kostaði gjöfin?" in priced.text  # sama verðgluggi og á jólalistanum


def test_action_rejects_unknown_action_and_far_years(client, home):
    hugi = person(home, "Hugi", datetime.date(2014, 11, 18))
    assert client.post(url("birthday_action", home.slug, hugi.pk, 2040, "hugmynd"), **HX).status_code == 405
    assert client.post(url("birthday_action", home.slug, hugi.pk, 2026, "eyda"), **HX).status_code == 405
    stranger = PersonFactory(birthday=datetime.date(2000, 1, 1))
    assert (
        client.post(url("birthday_action", home.slug, stranger.pk, 2026, "hugmynd"), **HX).status_code == 404
    )


def test_add_birthday_dialog(client, home):
    mamma = PersonFactory(household=home, name="Mamma", group="fjolskylda")
    client.post(url("birthday_add", home.slug), {"name": "mamma", "birthday": "02/02/60"}, **HX)
    mamma.refresh_from_db()
    assert mamma.give_birthday and str(mamma.birthday) == "1960-02-02" and mamma.group == "fjolskylda"
    response = client.post(url("birthday_add", home.slug), {"name": "Nýr", "birthday": ""}, **HX)
    assert response.status_code == 422


def test_idea_bank_adds_to_chosen_person(client, home):
    hugi = person(home, "Hugi", datetime.date(2014, 11, 18))
    year = birthdays.next_birthday(hugi.birthday, datetime.date.today()).year
    dialog = client.get(url("bank_add", home.slug, 0), **HX).text
    assert f'value="{hugi.pk}-{year}"' in dialog
    client.post(url("bank_add", home.slug, 0), {"who": f"{hugi.pk}-{year}"}, **HX)
    assert (
        Gift.objects.get(person=hugi, occasion=Occasion.BIRTHDAY).ideas.get().text
        == "Kaffiáskrift (3 mánuðir)"
    )


def test_reminder_settings(client, home):
    client.post(url("birthday_reminders", home.slug), {"enabled": "on", "days": "7"}, **HX)
    home.refresh_from_db()
    assert home.birthday_reminders and home.reminder_days == 7
    client.post(url("birthday_reminders", home.slug), {"days": "999"}, **HX)
    home.refresh_from_db()
    assert not home.birthday_reminders and home.reminder_days == 14


# ---------- Áminningar ----------


def test_reminders_are_sent_once_to_all_members(home, member):
    MembershipFactory(household=home)
    home.birthday_reminders = True
    home.save()
    hugi = person(home, "Hugi", datetime.date(2014, 11, 18))
    person(home, "Langt í", datetime.date(2014, 3, 1))
    IdeaFactory(gift=birthdays.ensure_gift(hugi, 2026), text="legó")

    assert birthdays.send_reminders(TODAY) == 1
    message = mail.outbox[0]
    assert message.subject == "🎂 Hugi á afmæli eftir 6 daga"
    assert len(message.to) == 2
    assert "verður 12 ára" in message.body and "• legó" in message.body
    assert "\\n" not in message.body
    assert birthdays.send_reminders(TODAY) == 0  # aldrei tvisvar
    assert BirthdayReminder.objects.count() == 1


def test_no_reminders_when_disabled(home):
    person(home, "Hugi", datetime.date(2014, 11, 18))
    assert birthdays.send_reminders(TODAY) == 0
    assert not mail.outbox


def test_person_page_shows_birthday_gift_in_history(client, home):
    hugi = person(home, "Hugi", datetime.date(2014, 11, 18))
    gift = birthdays.ensure_gift(hugi, 2025)
    IdeaFactory(gift=gift, text="afmælisbók", picked=True)
    Gift.objects.filter(pk=gift.pk).update(bought=True)
    html = client.get(url("person", home.slug, hugi.pk), **HX).text
    assert "2025 🎂" in html and "afmælisbók" in html
    assert Person.objects.count() == 1
