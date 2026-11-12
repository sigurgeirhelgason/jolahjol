import re

import pytest
from django.utils import timezone
from playwright.sync_api import expect

from apps.accounts.models import User
from apps.gifts.models import Gift, Idea, Person, Season
from apps.households.models import Household, Membership

YEAR = timezone.localdate().year


@pytest.fixture
def home(live_server, page, login):
    user = User.objects.create_user(email="sibbi@example.com", name="Sibbi")
    household = Household.objects.create(name="Okkar", slug="okkar")
    Membership.objects.create(user=user, household=household, role=Membership.Role.OWNER)
    season = Season.objects.create(household=household, year=YEAR)
    hugi = Person.objects.create(household=household, name="Hugi", group="born")
    gift = Gift.objects.create(season=season, person=hugi, plan=15000)
    Idea.objects.create(gift=gift, text="legó", price=8990, position=0)
    Idea.objects.create(gift=gift, text="spil", position=1)
    login(page, "sibbi@example.com")
    return household


def test_share_reserve_and_household_sees_it(home, live_server, page, browser):
    # Heimilið: smellt á nafn → Búa til hlekk
    page.get_by_role("button", name="Hugi", exact=True).click()
    dialog = page.locator("#modal")
    dialog.get_by_role("button", name="Búa til hlekk").click()
    link = dialog.get_by_label("Hlekkur á óskalista").input_value()
    assert "/o/" in link
    dialog.locator("[data-close]").first.click()

    # Amma opnar hlekkinn í síma, án innskráningar
    amma = browser.new_context(locale="is-IS", viewport={"width": 390, "height": 800}).new_page()
    amma.goto(link)
    expect(amma.get_by_role("heading", name="Hugi", exact=True)).to_be_visible()
    overflow = amma.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0
    item = amma.locator(".wish-item", has_text="legó")
    item.get_by_placeholder("Nafnið þitt").fill("Amma Jóa")
    item.get_by_role("button", name="Ég kaupi þetta").click()
    expect(amma.get_by_text("Takk! Þetta er frátekið á þitt nafn.")).to_be_visible()
    expect(amma.locator(".wish-item", has_text="legó")).to_contain_text("Þú tókst þetta frá")
    # Nafnið er munað fyrir næstu hugmynd
    expect(amma.locator(".wish-item", has_text="spil").get_by_placeholder("Nafnið þitt")).to_have_value(
        "Amma Jóa"
    )

    # Heimilið sér frátekninguna (appelsínugul, án gátreits) og getur afhakað hana
    page.reload()
    line = page.locator(".idea-line", has=page.locator(".chip-t", has_text="legó"))
    expect(line).to_have_class(re.compile(r"\breserved\b"))
    expect(line.locator("input[type=checkbox]")).to_have_count(0)
    line.locator(".chip-t").click()
    expect(dialog.get_by_text(re.compile("Frátekið af Amma Jóa"))).to_be_visible()
    reserved = dialog.get_by_role("checkbox", name=re.compile("^Frátekið"))
    expect(reserved).to_be_checked()
    dialog.locator("label.reserved-switch").click()
    dialog.get_by_role("button", name=re.compile("Vista")).click()
    expect(dialog).to_be_hidden()
    line = page.locator(".idea-line", has=page.locator(".chip-t", has_text="legó"))
    expect(line).not_to_have_class(re.compile(r"\breserved\b"))
    assert not Idea.objects.get(text="legó").reserved
