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
        expect(row(page, name).locator(".idea-line:not(.add-line)", has_text=idea)).to_have_count(1)


def test_gift_list_flow(home, page):
    add_gift(page, "Börn", "Hugi", "15000", "legó, spil")
    hugi = row(page, "Hugi")
    expect(hugi.locator(".idea-line:not(.add-line)")).to_have_count(2)
    expect(hugi.get_by_label("Áætlað verð handa Hugi")).to_have_value("15.000 kr.")
    expect(page.locator("#summary .big-stat .num")).to_contain_text("0 af 1")

    # Hugmynd í línu með Enter; reiturinn tæmist
    chip_input = hugi.get_by_label("Ný hugmynd handa Hugi")
    chip_input.fill("bók")
    chip_input.press("Enter")
    expect(row(page, "Hugi").locator(".idea-line:not(.add-line)")).to_have_count(3)

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
    expect(page.locator("#summary .big-stat .num")).to_contain_text("1 af 1")
    expect(page.locator("#group-born-head")).to_contain_text("1 keypt")


def test_pick_idea_in_list(home, page):
    add_gift(page, "Börn", "Una", "5000", "úr, bók")
    row(page, "Una").get_by_label("úr handa Una keypt").check()
    dialog = page.locator("#modal")
    expect(dialog.get_by_text("Hvað kostaði gjöfin?")).to_be_visible()
    dialog.get_by_label("Verð (kr.)").fill("4990")
    dialog.get_by_role("button", name="Skrá verð").click()
    expect(dialog).to_be_hidden()
    una = row(page, "Una")
    expect(una.locator(".idea-line.picked")).to_have_count(1)
    expect(una.get_by_label("úr handa Una keypt")).to_be_checked()
    expect(una.locator(".price-wrap")).to_contain_text("4.990 kr.")
    # Keypt hugmynd gerir gjöfina ekki „Tilbúið“: það gerir notandinn sjálfur
    expect(una).not_to_have_class(re.compile(r"\bdone\b"))
    una.get_by_label("Keypt handa Una").check()
    expect(row(page, "Una")).to_have_class(re.compile(r"\bdone\b"))
    expect(page.locator("#modal")).to_be_hidden()  # verðið er þekkt, ekki spurt

    # Hætt við hugmyndina: gjöfin er áfram tilbúin
    row(page, "Una").get_by_label("úr handa Una keypt").uncheck()
    expect(row(page, "Una").locator(".idea-line.picked")).to_have_count(0)
    expect(row(page, "Una")).to_have_class(re.compile(r"\bdone\b"))


def test_store_typed_in_idea_line(home, page):
    add_gift(page, "Börn", "Una", "5000", "úr")
    # Línan var að koma frá htmx: bíða þar til hún er tengd (settle), annars sendir reiturinn ekkert
    expect(page.locator(".htmx-request, .htmx-settling, .htmx-swapping")).to_have_count(0)
    store_input = row(page, "Una").get_by_label("Búð fyrir úr")
    store_input.fill("Elko")
    store_input.press("Enter")
    expect(row(page, "Una").get_by_role("button", name="Elko")).to_be_visible()
    expect(row(page, "Una").get_by_label("Búð fyrir úr")).to_have_count(0)


def test_idea_dialog_givers_and_billing(home, page):
    add_gift(page, "Fjölskylda", "Ásdís", "8000", "púsl")
    page.get_by_role("button", name=re.compile("^púsl")).click()
    dialog = page.locator("#modal")
    givers = dialog.get_by_label("Hver gefur gjöfina?")

    # Komma aðgreinir gefendur; placeholder hverfur þegar gefandi er kominn
    expect(givers).to_have_attribute("placeholder", "t.d. Amma Jóa, Afi")
    givers.press_sequentially("Amma Jóa, ")
    expect(dialog.locator(".picker-tag")).to_have_count(1)
    expect(givers).to_have_attribute("placeholder", "")
    givers.fill("Afi")
    dialog.get_by_role("option", name=re.compile("Búa til „Afi“")).click()
    expect(dialog.locator(".picker-tag")).to_have_count(2)

    # Keypt fyrir annan birtist bara með gefendum; verðinu er skipt jafnt
    dialog.get_by_text("Keypt fyrir annan").click()
    dialog.get_by_label("Verð (kr.)").fill("6.000")
    dialog.locator("label.switch", has_text="Keypt").last.click()
    dialog.get_by_role("button", name="Vista").click()
    expect(dialog).to_be_hidden()

    asdis = row(page, "Ásdís")
    expect(asdis.locator(".idea-line.picked")).to_contain_text("Amma Jóa og Afi gefa gjöfina")
    expect(page.locator("#summary .money-foot")).to_contain_text("Til innheimtu: 6.000 kr.")
    assert set(IdeaGiver.objects.values_list("person__name", "share")) == {("Amma Jóa", None), ("Afi", None)}

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
    birthday = dialog.get_by_label("Fæðingardagur")
    birthday.press_sequentially("030350")
    expect(birthday).to_have_value("03/03/50")
    expect(dialog.get_by_text(re.compile(r"Verður \d+ ára 3\. mars"))).to_be_visible()
    dialog.get_by_text("Gef afmælisgjafir").click()
    dialog.get_by_role("button", name="Vista").click()
    expect(dialog).to_be_hidden()
    afi = Person.objects.get(name="Afi")
    assert str(afi.birthday) == "1950-03-03" and afi.give_birthday


def test_store_dialog_adds_location(home, page):
    add_gift(page, "Börn", "Hugi", ideas="legó")
    page.locator(".chip-t", has_text="legó").click()
    dialog = page.locator("#modal")
    dialog.get_by_label("Búð", exact=True).fill("Elko")
    dialog.get_by_role("button", name="Vista").click()
    expect(dialog).to_be_hidden()

    row(page, "Hugi").get_by_role("button", name="Elko").click()
    dialog.get_by_label("Annar staður").fill("Kringlan")
    dialog.get_by_role("button", name="Vista").click()
    expect(dialog).to_be_hidden()
    row(page, "Hugi").get_by_role("button", name="Elko").click()
    expect(dialog.locator("label.loc-pick", has_text="Kringlan").locator("input")).to_be_checked()


def test_selecting_text_and_releasing_outside_keeps_dialog_open(home, page):
    add_gift(page, "Börn", "Hugi", ideas="legó")
    page.locator(".chip-t", has_text="legó").click()
    dialog = page.locator("#modal")
    price = dialog.get_by_label("Verð (kr.)")
    price.fill("4990")

    # Dregið yfir textann og músinni sleppt utan gluggans
    box = price.bounding_box()
    page.mouse.move(box["x"] + box["width"] - 5, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(5, 5, steps=5)
    page.mouse.up()
    expect(dialog).to_be_visible()

    # Smellur á bilið inni í glugganum lokar ekki heldur
    dbox = dialog.bounding_box()
    page.mouse.click(dbox["x"] + 6, dbox["y"] + dbox["height"] / 2)
    expect(dialog).to_be_visible()

    # Venjulegur smellur á bakgrunninn lokar
    page.mouse.click(5, 5)
    expect(dialog).to_be_hidden()


def test_eye_hides_a_persons_gifts_on_this_device(home, page):
    add_gift(page, "Fjölskylda", "Kona", plan="20000", ideas="hálsmen")
    add_gift(page, "Fjölskylda", "Mamma", ideas="bók")
    kona, mamma = row(page, "Kona"), row(page, "Mamma")
    eye = kona.get_by_role("button", name="Fela gjafir handa Kona")
    expect(eye).to_have_attribute("aria-pressed", "false")

    eye.click()
    expect(kona).to_have_class(re.compile(r"\bpeek-off\b"))
    expect(eye).to_have_attribute("aria-pressed", "true")
    expect(mamma).not_to_have_class(re.compile(r"\bpeek-off\b"))
    # Óskýrt og ekki hægt að smella á hugmyndina; nafnið sést áfram
    assert "blur" in kona.locator(".ideas").evaluate("el => getComputedStyle(el).filter")
    expect(kona.get_by_role("button", name="Kona", exact=True)).to_be_visible()

    # Helst eftir endurhleðslu (vafrakaka sem þjónninn les) og á Verslunum
    page.reload()
    expect(row(page, "Kona")).to_have_class(re.compile(r"\bpeek-off\b"))
    page.get_by_role("link", name="Verslanir").click()
    expect(page.locator(".shop-person", has_text="Kona")).to_have_class(re.compile(r"\bpeek-off\b"))
    expect(page.locator(".shop-person", has_text="Mamma")).not_to_have_class(re.compile(r"\bpeek-off\b"))

    # Aftur sýnilegt
    page.locator(".shop-person", has_text="Kona").get_by_role("button", name="Fela gjafir handa Kona").click()
    page.go_back()
    page.reload()
    expect(row(page, "Kona")).not_to_have_class(re.compile(r"\bpeek-off\b"))
