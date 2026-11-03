from playwright.sync_api import expect

from apps.households.models import Membership


def test_signup_onboarding_and_invite(live_server, page, login, browser):
    # Nýr notandi: forsíða → kóði → stofna heimili
    page.goto(live_server.url)
    page.get_by_role("link", name="Byrja").click()
    login(page, "sibbi@example.com")
    expect(page.get_by_role("heading", name="Velkomin í Jólahjól")).to_be_visible()
    page.get_by_label("Nafn heimilis").fill("Heimilið á Þórsgötu")
    page.get_by_label("Hvað heitir þú?").fill("Sibbi")
    page.get_by_role("button", name="Stofna heimili").click()
    expect(page).to_have_url(f"{live_server.url}/h/heimilid-a-thorsgotu/")

    # Valmynd heimilis (Alpine) → stillingar → boðshlekkur
    page.get_by_role("button", name="Heimilið á Þórsgötu").click()
    page.get_by_role("link", name="Stillingar og meðlimir").click()
    page.get_by_role("button", name="Búa til boðshlekk").click()
    invite_url = page.get_by_label("Boðshlekkur").input_value()

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
    page.get_by_role("button", name="Aðgangur").click()
    page.get_by_role("button", name="Skrá út").click()
    expect(page.get_by_role("link", name="Byrja")).to_be_visible()
