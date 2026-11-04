import re

from playwright.sync_api import expect

from apps.gifts.models import Season
from apps.households.models import Household, Membership


def test_signup_onboarding_and_invite(live_server, page, login, browser):
    # Nýr notandi: forsíða → kóði → stofna heimili
    page.goto(live_server.url)
    page.get_by_role("link", name="Byrja").click()
    login(page, "sibbi@example.com")
    expect(page.get_by_role("heading", name="Velkomin í Jólahjól")).to_be_visible()
    page.get_by_label("Nafn heimilis").fill("Heimilið á Þórsgötu")
    page.get_by_label("Hvað heitir þú?").fill("Sibbi")
    page.get_by_role("button", name="Stofna heimili").click()
    expect(page).to_have_url(re.compile(r"/h/heimilid-a-thorsgotu/\d{4}/$"))

    # Valmynd heimilis (Alpine) → stillingar → boðshlekkur
    page.get_by_role("button", name="Heimilið á Þórsgötu").click()
    page.get_by_role("link", name="Stillingar").click()
    page.get_by_role("button", name="Búa til boðshlekk").click()
    invite_url = page.get_by_label("Boðshlekkur").input_value()
    expect(page.locator(".invite-link button").first).to_have_text(re.compile(r"Afrita$"))

    # Annar notandi í hreinum vafra þiggur boðið
    other = browser.new_context(locale="is-IS").new_page()
    other.goto(invite_url)
    expect(other.get_by_label("Netfang")).to_be_visible()  # boðið krefst innskráningar
    login(other, "maki@example.com", navigate=False)
    other.get_by_role("button", name="Þiggja boð").click()
    expect(other.get_by_text("Gaman að fá þig")).to_be_visible()
    assert Membership.objects.filter(user__email="maki@example.com", role="member").exists()

    # Eigandinn sér nýja meðliminn
    page.reload()
    expect(page.locator("#members")).to_contain_text("maki@example.com")


def test_user_menu_logs_out(live_server, page, login):
    login(page, "a@example.com")
    page.get_by_label("Nafn heimilis").fill("Okkar")
    page.get_by_role("button", name="Stofna heimili").click()
    page.get_by_role("button", name="Okkar").click()
    page.get_by_role("button", name="Skrá út").click()
    expect(page.get_by_role("link", name="Byrja")).to_be_visible()


def test_deleting_season_asks_in_styled_dialog(live_server, page, login):
    login(page, "eigandi@example.com")
    page.get_by_label("Nafn heimilis").fill("Okkar")
    page.get_by_role("button", name="Stofna heimili").click()
    page.get_by_role("button", name="Okkar").click()
    page.get_by_role("link", name="Stillingar").click()

    page.get_by_role("button", name=re.compile(r"^Eyða jólum")).first.click()
    dialog = page.locator("#confirm-dialog")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("heading")).to_contain_text("Eyða jólum")
    dialog.get_by_role("button", name="Hætta við").click()
    expect(dialog).to_be_hidden()
    assert Season.objects.count() == 1

    page.get_by_role("button", name=re.compile(r"^Eyða jólum")).first.click()
    dialog.get_by_role("button", name=re.compile(r"^Eyða jólum")).click()
    expect(page.get_by_text("Engin jólaár enn.")).to_be_visible()
    assert Season.objects.count() == 0


def test_deleting_household_requires_typing_its_name(live_server, page, login):
    login(page, "eigandi@example.com")
    page.get_by_label("Nafn heimilis").fill("Heimilið okkar")
    page.get_by_role("button", name="Stofna heimili").click()
    page.get_by_role("button", name="Heimilið okkar").click()
    page.get_by_role("link", name="Stillingar").click()

    page.get_by_role("button", name="Eyða heimili").click()
    dialog = page.locator("dialog[open]")
    expect(dialog).to_contain_text("Gögnin verða ekki aðgengileg aftur")
    confirm = dialog.get_by_role("button", name="Eyða heimili")
    expect(confirm).to_be_disabled()
    dialog.get_by_label(re.compile("til að staðfesta")).fill("heimilið")
    expect(confirm).to_be_disabled()
    dialog.get_by_label(re.compile("til að staðfesta")).fill(" heimilið OKKAR ")
    expect(confirm).to_be_enabled()
    confirm.click()
    expect(page.get_by_text("var eytt")).to_be_visible()
    assert not Household.objects.exists()
