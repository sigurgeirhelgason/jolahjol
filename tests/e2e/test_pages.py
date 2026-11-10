import re

import pytest
from django.utils import timezone
from playwright.sync_api import expect

from apps.accounts.models import User
from apps.gifts.models import Gift, Idea, IdeaGiver, Person, Season
from apps.gifts.services import stores
from apps.households.models import Household, Membership

YEAR = timezone.localdate().year


@pytest.fixture
def home(live_server, page, login):
    user = User.objects.create_user(email="sibbi@example.com", name="Sibbi")
    household = Household.objects.create(name="Okkar", slug="okkar")
    Membership.objects.create(user=user, household=household, role=Membership.Role.OWNER)
    season = Season.objects.create(household=household, year=YEAR, budget=100000)

    # Hugi: púsl keypt fyrir Ömmu Jóu og Afa; Una: óákveðin búð; Elko í Kringlunni
    hugi = Person.objects.create(household=household, name="Hugi", group="born")
    una = Person.objects.create(household=household, name="Una", group="born")
    gift = Gift.objects.create(season=season, person=hugi, bought=True, plan=8000)
    idea = Idea.objects.create(gift=gift, text="púsl", price=6000, picked=True, for_other=True)
    for name in ("Amma Jóa", "Afi"):
        IdeaGiver.objects.create(idea=idea, person=Person.objects.create(household=household, name=name))
    una_gift = Gift.objects.create(season=season, person=una, plan=5000)
    elko = stores.get_or_create_store(household, "Elko")
    stores.set_locations(elko, "Kringlan")
    Idea.objects.create(gift=una_gift, text="úr", store=elko)

    login(page, "sibbi@example.com")
    return household


def test_billing_mark_paid_updates_page_and_tab_count(home, live_server, page):
    page.get_by_role("link", name=re.compile(r"^Rukkun")).first.click()
    expect(page).to_have_url(re.compile(rf"/{YEAR}/rukkun/$"))
    tab = page.locator("nav.views a", has_text="Rukkun")
    expect(tab.locator(".nav-count")).to_have_text("2")

    amma = page.locator(".card", has=page.get_by_role("heading", name="Amma Jóa"))
    amma.get_by_role("checkbox").check()
    expect(amma.locator(".count-pill")).to_have_text("Greitt")
    expect(tab.locator(".nav-count")).to_have_text("1")

    afi = page.locator(".card", has=page.get_by_role("heading", name="Afi"))
    afi.get_by_role("button", name="Merkja allt greitt").click()
    expect(page.get_by_text("Allt greitt – engin útistandandi rukkun.")).to_be_visible()
    expect(tab.locator(".nav-count")).to_have_count(0)


def test_shop_by_location_and_mark_bought(home, live_server, page):
    page.locator("nav.views").get_by_role("link", name="Verslanir").click()
    expect(page.get_by_role("heading", name="Elko")).to_be_visible()
    page.get_by_role("link", name="Staðsetningu").click()
    expect(page.locator(".loc-head", has_text="Kringlan")).to_be_visible()

    page.get_by_label("úr handa Una keypt").check()
    dialog = page.locator("#modal")
    expect(dialog.get_by_text("Hvað kostaði gjöfin?")).to_be_visible()
    dialog.get_by_label("Verð (kr.)").fill("4990")
    dialog.get_by_role("button", name="Skrá verð").click()
    expect(page.get_by_text("Allar gjafir eru keyptar!")).to_be_visible()
    assert not Gift.objects.get(person__name="Una").bought  # „Tilbúið“ merkir notandinn sjálfur
    assert Idea.objects.get(text="úr").price == 4990


def test_people_change_group_and_edit_person(home, live_server, page):
    page.locator("nav.views").get_by_role("link", name="Fólk & Fjölskylda").click()
    expect(page.get_by_role("button", name="Una", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Amma Jóa")).to_have_count(0)  # bara gefandi

    page.get_by_label("Flokkur Una").select_option("vinir")
    vinir = page.locator(".card", has=page.get_by_role("heading", name="Vinir"))
    expect(vinir.get_by_role("button", name="Una", exact=True)).to_be_visible()

    page.get_by_role("button", name="Una", exact=True).click()
    dialog = page.locator("#modal")
    dialog.get_by_label("Fæðingardagur").press_sequentially("170516")
    dialog.get_by_role("button", name="Vista").click()
    expect(dialog).to_be_hidden()
    expect(page.locator(".person", has_text="Una")).to_contain_text("🎂")
