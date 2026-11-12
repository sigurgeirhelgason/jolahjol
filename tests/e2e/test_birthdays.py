import datetime
import re

import pytest
from django.utils import timezone
from playwright.sync_api import expect

from apps.accounts.models import User
from apps.gifts.models import Gift, Occasion, Person
from apps.households.models import Household, Membership


@pytest.fixture
def home(live_server, page, login):
    user = User.objects.create_user(email="sibbi@example.com", name="Sibbi")
    household = Household.objects.create(name="Okkar", slug="okkar")
    Membership.objects.create(user=user, household=household, role=Membership.Role.OWNER)
    # Hugi á afmæli eftir 5 daga (verður 12 ára)
    soon = timezone.localdate() + datetime.timedelta(days=5)
    Person.objects.create(
        household=household,
        name="Hugi",
        group="born",
        give_birthday=True,
        birthday=soon.replace(year=soon.year - 12),
    )
    login(page, "sibbi@example.com")
    return household


def test_birthday_card_flow(home, live_server, page):
    page.locator("nav.views").get_by_role("link", name="Afmæli").click()
    expect(page.get_by_role("heading", name=re.compile("Afmælisgjafir"))).to_be_visible()
    card = page.locator(".bday-card", has_text="Hugi")
    expect(card).to_contain_text("verður 12 ára")
    expect(card.locator(".days-chip")).to_contain_text("Eftir 5 daga")

    # Hugmynd í línu
    idea = card.get_by_label("Ný afmælishugmynd handa Hugi")
    idea.fill("legó")
    idea.press("Enter")
    expect(page.locator(".bday-card", has_text="Hugi").locator(".chip", has_text="legó")).to_be_visible()

    # Keypt án verðs → verðgluggi
    page.locator(".bday-card", has_text="Hugi").get_by_label("Afmælisgjöf keypt handa Hugi").check()
    dialog = page.locator("#modal")
    expect(dialog.get_by_text("Hvað kostaði gjöfin?")).to_be_visible()
    dialog.get_by_label("Verð (kr.)").fill("8990")
    dialog.get_by_role("button", name="Skrá verð").click()
    card = page.locator(".bday-card", has_text="Hugi")
    expect(card.locator(".status-pill")).to_have_text("Keypt")
    expect(page.locator(".bday-box-cap")).to_contain_text("1 / 1")
    gift = Gift.objects.get(occasion=Occasion.BIRTHDAY)
    assert gift.bought and gift.actual_price == 8990

    # Jólalistinn sér ekki afmælisgjöfina
    page.locator("nav.views").get_by_role("link", name="Gjafalisti").click()
    expect(page.locator(".chip", has_text="legó")).to_have_count(0)


def test_bank_reminders_and_add_birthday(home, live_server, page):
    page.goto(live_server.url + "/h/okkar/afmaeli/")
    page.locator(".bank button", has_text="Leikhúsmiðar").click()
    dialog = page.locator("#modal")
    dialog.get_by_role("button", name="Bæta við").click()
    expect(
        page.locator(".bday-card", has_text="Hugi").locator(".chip", has_text="Leikhúsmiðar")
    ).to_be_visible()

    page.get_by_text("Slökkt").click()
    expect(page.get_by_text("Kveikt")).to_be_visible()
    assert Household.objects.get().birthday_reminders

    page.locator(".bday-hero").get_by_role("button", name="Bæta við afmæli").click()
    dialog.get_by_label("Nafn", exact=True).fill("Mamma")
    birthday = dialog.get_by_label("Fæðingardagur")
    birthday.press_sequentially("020260")
    # Skástrikin bætast við á meðan skrifað er (Alpine); senda ekki fyrr en reiturinn er tilbúinn
    expect(birthday).to_have_value("02/02/60")
    dialog.get_by_role("button", name="Bæta við").click()
    expect(page.locator(".bday-card", has_text="Mamma")).to_be_visible()


def test_mobile_has_no_horizontal_scroll(home, live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server.url + "/h/okkar/afmaeli/")
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0
