"""Dísa deilir óskalista heimilisins „Laugavegur 5“; amma Ragga tekur frá og bætir heimilinu á sinn lista."""

import re

from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect

from apps.accounts.models import User
from apps.gifts.models import Gift, Idea, Person, Season
from apps.households.models import Household, Membership

YEAR = timezone.localdate().year


def test_disa_shares_household_and_ragga_follows(live_server, page, login, browser):
    disa = User.objects.create_user(email="disa@example.com", name="Dísa")
    home = Household.objects.create(name="Laugavegur 5", slug="laugavegur-5")
    season = Season.objects.create(household=home, year=YEAR)
    for name, idea in (("Jói", "Veiðistöng"), ("Siggi", "Lego"), ("Stína", "Hárskraut")):
        gift = Gift.objects.create(season=season, person=Person.objects.create(household=home, name=name))
        Idea.objects.create(gift=gift, text=idea)
    Membership.objects.create(user=disa, household=home, role=Membership.Role.OWNER)

    ragga = User.objects.create_user(email="ragga@example.com", name="Ragga")
    hers = Household.objects.create(name="Hjá ömmu", slug="hja-ommu")
    Membership.objects.create(user=ragga, household=hers, role=Membership.Role.OWNER)
    Season.objects.create(household=hers, year=YEAR)

    # Dísa setur Jóa, Sigga og Stínu í flokk heimilisins á Fólk-síðunni
    login(page, "disa@example.com")
    page.goto(live_server.url + reverse("gifts:people", args=[home.slug, YEAR]))
    for name in ("Jói", "Siggi", "Stína"):
        page.get_by_label(f"Flokkur {name}").select_option("heimili")
        expect(
            page.locator(".sections .card", has=page.get_by_role("heading", name="Laugavegur 5"))
        ).to_contain_text(name)

    # … og deilir óskalista heimilisins af gjafalistanum
    page.goto(live_server.url + reverse("gifts:season", args=[home.slug, YEAR]))
    head = page.locator("#group-heimili-head")
    expect(head.get_by_role("heading", name="Laugavegur 5")).to_be_visible()
    head.get_by_role("button", name=re.compile("Deila óskalista heimilisins")).click()
    dialog = page.locator("#modal")
    expect(dialog).to_contain_text("Jói, Siggi, Stína")
    dialog.get_by_role("button", name="Búa til hlekk").click()
    link = dialog.get_by_label("Hlekkur á óskalista heimilisins").input_value()

    # Amma opnar hlekkinn, tekur Lego frá og bætir heimilinu á sinn lista
    other = browser.new_context(locale="is-IS").new_page()
    login(other, "ragga@example.com")
    other.goto(link)
    expect(other.get_by_role("heading", name="Laugavegur 5", level=1)).to_be_visible()
    # Án nafns: vafrinn biður um nafnið áður en nokkuð er sent
    other.get_by_role("button", name="Ég kaupi Lego handa Siggi").click()
    assert not Idea.objects.get(text="Lego").reserved
    other.get_by_label("Nafnið þitt").fill("Amma Ragga")
    other.get_by_role("button", name="Ég kaupi Lego handa Siggi").click()
    lego = other.locator(".wl-line", has_text="Lego")
    expect(lego).to_contain_text("Þú tókst þetta frá")
    lego.get_by_role("button", name="Hætta við").click()
    expect(other.get_by_text("Frátekningin var felld niður.")).to_be_visible()
    other.get_by_role("button", name="Ég kaupi Lego handa Siggi").click()  # nafnið er munað
    expect(other.locator(".wl-line", has_text="Lego")).to_contain_text("Þú tókst þetta frá")
    assert Idea.objects.get(text="Lego").reserved

    other.locator("#follow").get_by_role("button", name=re.compile("Bæta á minn lista")).click()
    expect(other).to_have_url(re.compile(r"/h/hja-ommu/"))
    group = other.locator(".sections .card", has=other.get_by_role("heading", name="Laugavegur 5"))
    for name in ("Jói", "Siggi", "Stína"):
        expect(group.get_by_role("button", name=name, exact=True)).to_be_visible()
    expect(group).to_contain_text("Veiðistöng")
    expect(group).to_contain_text("Hárskraut")
    expect(group).not_to_contain_text("Dísa")  # hún er ekki í flokki heimilisins
