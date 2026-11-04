import re

import pytest
from django.utils import timezone
from playwright.sync_api import expect

from apps.accounts.models import User
from apps.gifts.models import Gift, IdeaGiver, Person, Season
from apps.households.models import Household, Membership

YEAR = timezone.localdate().year


@pytest.fixture
def home(live_server, page, login):
    user = User.objects.create_user(email="sibbi@example.com", name="Sibbi")
    household = Household.objects.create(name="Okkar", slug="okkar")
    Membership.objects.create(user=user, household=household, role=Membership.Role.OWNER)
    Season.objects.create(household=household, year=YEAR, budget=100000)
    login(page, "sibbi@example.com")
    expect(page).to_have_url(re.compile(rf"/h/okkar/{YEAR}/$"))
    return household


def row(page, name):
    return page.locator(".row.gift", has=page.get_by_role("button", name=name, exact=True))


def add_gift(page, group, name, plan="", ideas=""):
    """„Bæta við aðila í <flokki>“ → ný lína: nafn og áætlun, Enter vistar. Hugmyndir í línunni."""
    page.get_by_role("button", name=f"Bæta við aðila í {group}").click()
    new_row = page.locator(".new-row")
    name_input = new_row.get_by_label("Nafn", exact=True)
    expect(name_input).to_be_focused()
    name_input.fill(name)
    if plan:
        new_row.get_by_label("Áætlað verð").fill(plan)
    new_row.get_by_label("Áætlað verð").press("Enter")
    expect(page.locator(".new-row")).to_have_count(0)
    for idea in [i.strip() for i in ideas.split(",") if i.strip()]:
        chip = row(page, name).get_by_label(f"Ný hugmynd handa {name}")
        chip.fill(idea)
        chip.press("Enter")
        expect(row(page, name).locator(".chip", has_text=idea)).to_have_count(1)


def test_gift_list_flow(home, page):
    add_gift(page, "Börn", "Hugi", "15000", "legó, spil")
    hugi = row(page, "Hugi")
    expect(hugi.locator(".chip")).to_have_count(2)
    expect(hugi.get_by_label("Áætlað verð handa Hugi")).to_have_value("15.000 kr.")
    expect(page.locator("#summary .big-stat .num")).to_contain_text("0 / 1")

    # Hugmynd í línu með Enter; reiturinn tæmist
    chip_input = hugi.get_by_label("Ný hugmynd handa Hugi")
    chip_input.fill("bók")
    chip_input.press("Enter")
    expect(row(page, "Hugi").locator(".chip")).to_have_count(3)

    # +upphæð bætir við áætlun
    plan = row(page, "Hugi").get_by_label("Áætlað verð handa Hugi")
    plan.click()
    expect(plan).to_have_value("15000")
    plan.fill("+2000")
    plan.press("Enter")
    expect(row(page, "Hugi").get_by_label("Áætlað verð handa Hugi")).to_have_value("17.000 kr.")

    # Keypt án verðs → verðgluggi → verð skráð
    row(page, "Hugi").get_by_label("Keypt handa Hugi").check()
    dialog = page.locator("#modal")
    expect(dialog.get_by_text("Hvað kostaði gjöfin?")).to_be_visible()
    dialog.get_by_label("Verð (kr.)").fill("2500+990")
    dialog.get_by_role("button", name="Skrá verð").click()
    expect(dialog).to_be_hidden()
    hugi = row(page, "Hugi")
    expect(hugi).to_have_class(re.compile(r"\bdone\b"))
    expect(hugi.locator(".price-wrap")).to_contain_text("3.490 kr.")
    expect(page.locator("#summary .big-stat .num")).to_contain_text("1 / 1")
    expect(page.locator("#group-born-head")).to_contain_text("1 keypt")


def test_idea_dialog_givers_and_billing(home, page):
    add_gift(page, "Fjölskylda", "Ásdís", "8000", "púsl")
    page.get_by_role("button", name=re.compile("^púsl")).click()
    dialog = page.locator("#modal")
    givers = dialog.get_by_label("Frá hverjum?")

    # Nýr gefandi með Enter, annar valinn úr tillögum
    expect(givers).to_be_visible()
    givers.fill("Amma Jóa")
    givers.press("Enter")
    expect(dialog.locator(".picker-tag")).to_have_count(1)
    givers.fill("Afi")
    dialog.get_by_role("option", name=re.compile("Búa til „Afi“")).click()
    expect(dialog.locator(".picker-tag")).to_have_count(2)

    # Keypt fyrir annan birtist bara með gefendum; hlutir birtast með fleiri en einum
    dialog.get_by_text("Keypt fyrir annan").click()
    expect(dialog.locator(".shares")).to_be_visible()
    dialog.locator(".share-row input").first.fill("4000")
    dialog.get_by_label("Verð (kr.)").fill("6.000")
    dialog.locator("label.switch", has_text="Keypt").last.click()
    dialog.get_by_role("button", name="Vista").click()
    expect(dialog).to_be_hidden()

    asdis = row(page, "Ásdís")
    expect(asdis.locator(".chip.picked")).to_contain_text("frá Amma Jóa og Afi")
    expect(asdis.locator(".price-wrap")).to_contain_text("2.000 kr.")
    expect(page.locator("#summary .money-foot")).to_contain_text("Til innheimtu: 4.000 kr.")
    shares = dict(IdeaGiver.objects.values_list("person__name", "share"))
    assert shares == {"Amma Jóa": 4000, "Afi": None}

    # Gefendurnir eru á hugmyndinni þegar hún er opnuð aftur (🎁 á undan valinni hugmynd)
    page.locator(".chip-t", has_text="púsl").click()
    expect(dialog.locator(".picker-tag")).to_have_count(2)
    dialog.locator("[data-close]").first.click()


def test_search_filters_and_delete_with_undo(home, page):
    add_gift(page, "Börn", "Hugi", ideas="legó")
    add_gift(page, "Vinir", "Mahsa", ideas="trefill")

    page.get_by_label("Leita", exact=True).fill("tref")
    expect(row(page, "Mahsa")).to_be_visible()
    expect(row(page, "Hugi")).to_have_count(0)
    expect(page).to_have_url(re.compile(r"leit=tref"))
    page.get_by_label("Leita", exact=True).fill("")
    expect(row(page, "Hugi")).to_be_visible()

    page.get_by_role("button", name=re.compile(r"^Eftir að kaupa")).click()
    expect(page).to_have_url(re.compile(r"syna=eftir"))
    expect(page.get_by_role("button", name=re.compile(r"^Eftir að kaupa \(2\)"))).to_have_attribute(
        "aria-pressed", "true"
    )

    row(page, "Hugi").get_by_label("Eyða gjöf handa Hugi").click()
    expect(row(page, "Hugi")).to_have_count(0)
    toast = page.locator("#toast")
    expect(toast).to_contain_text("Gjöf til Hugi eytt")
    toast.get_by_role("button", name="Afturkalla").click()
    expect(row(page, "Hugi")).to_be_visible()
    assert Gift.objects.alive().count() == 2


def test_mobile_layout_has_no_horizontal_scroll(home, page):
    add_gift(page, "Börn", "Una Elínóra", "15000", "hundalegó, Hummel peysa, Fíasól")
    page.set_viewport_size({"width": 375, "height": 800})
    page.reload()
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0
    expect(row(page, "Una Elínóra")).to_be_visible()


def test_new_row_disappears_without_name_and_person_dialog(home, page):
    page.get_by_role("button", name="Bæta við aðila í Fjölskylda").click()
    expect(page.locator(".new-row")).to_have_count(1)
    page.get_by_label("Leita", exact=True).click()  # farið úr tómri línu
    expect(page.locator(".new-row")).to_have_count(0)

    add_gift(page, "Fjölskylda", "Afi", "5000")
    expect(row(page, "Afi").get_by_label("Áætlað verð handa Afi")).to_have_value("5.000 kr.")

    # Smellt á nafn: fæðingardagur og afmælisgjöf
    row(page, "Afi").get_by_role("button", name="Afi", exact=True).click()
    dialog = page.locator("#modal")
    dialog.get_by_label("Fæðingardagur").fill("1950-03-03")
    expect(dialog.get_by_text(re.compile(r"Verður \d+ ára 3\. mars"))).to_be_visible()
    dialog.get_by_text("Gef afmælisgjafir").click()
    dialog.get_by_role("button", name="Vista").click()
    expect(dialog).to_be_hidden()
    afi = Person.objects.get(name="Afi")
    assert str(afi.birthday) == "1950-03-03" and afi.give_birthday
