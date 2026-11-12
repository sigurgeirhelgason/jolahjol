"""Dísa frænka fær óskalista Siggu frá Jóa og Önnu, bætir henni á sitt Jólahjól og tekur hugmynd frá."""

import re

from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect

from apps.accounts.models import User
from apps.gifts.models import Gift, Idea, Person, Season
from apps.households.models import Household, Membership
from apps.wishlists import services

YEAR = timezone.localdate().year


def test_disa_follows_sigga_and_reserves(live_server, page, login):
    joi = User.objects.create_user(email="joi@example.com", name="Jói")
    home = Household.objects.create(name="Laugavegur 4", slug="laugavegur-4")
    Membership.objects.create(user=joi, household=home, role=Membership.Role.OWNER)
    season = Season.objects.create(household=home, year=YEAR)
    sigga = Person.objects.create(household=home, name="Sigga", group="born")
    gift = Gift.objects.create(season=season, person=sigga)
    Idea.objects.create(gift=gift, text="Bangsi", position=0)
    Idea.objects.create(gift=gift, text="Bíll", position=1)
    share = services.create_share(sigga, joi)

    disa = User.objects.create_user(email="disa@example.com", name="Dísa")
    mine = Household.objects.create(name="Heima hjá Dísu", slug="heima-hja-disu")
    Membership.objects.create(user=disa, household=mine, role=Membership.Role.OWNER)
    gunna = Person.objects.create(household=mine, name="Gunna")
    Gift.objects.create(season=Season.objects.create(household=mine, year=YEAR), person=gunna)

    # Opna síðan: skrá inn og koma aftur
    page.goto(live_server.url + reverse("wishlists:public", args=[share.token]))
    page.get_by_role("link", name=re.compile("Bæta á minn lista")).click()
    login(page, "disa@example.com", navigate=False)
    # Listinn hennar opnast með valglugganum
    expect(page).to_have_url(re.compile(r"/h/heima-hja-disu/\d+/\?fylgja="))
    popup = page.locator("dialog.follow-dlg")
    expect(popup).to_be_visible()
    popup.get_by_role("button", name="Hætta við").click()
    expect(popup).to_be_hidden()
    expect(page).not_to_have_url(re.compile("fylgja"))
    page.goto(live_server.url + reverse("wishlists:public", args=[share.token]))
    page.get_by_role("link", name=re.compile("Bæta á minn lista")).click()
    expect(popup).to_be_visible()
    popup.get_by_label("Flokkur").select_option("born")
    popup.get_by_role("button", name=re.compile("Bæta á listann")).click()
    expect(page).to_have_url(re.compile(r"/h/heima-hja-disu/"))
    expect(page.get_by_text("Hugmyndir sem þú bætir við sjást ekki")).to_be_visible()

    row = page.locator(".row.gift", has=page.get_by_role("button", name="Sigga", exact=True))
    expect(row.locator(".idea-line.feed")).to_have_count(2)
    row.locator(".idea-line.feed .chip-t", has_text="Bíll").click()
    dialog = page.locator("#modal")
    expect(dialog.get_by_text("Laugavegur 4").first).to_be_visible()
    dialog.get_by_role("button", name=re.compile("Frátekið")).click()
    expect(dialog).to_be_hidden()

    row = page.locator(".row.gift", has=page.get_by_role("button", name="Sigga", exact=True))
    expect(row.locator(".idea-line.feed")).to_have_count(1)
    expect(row.locator(".idea-line.reserved")).to_contain_text("Bíll")
    bill = Idea.objects.get(gift=gift, text="Bíll")
    assert bill.reserved and bill.reserved_by.name == "Dísa"


def test_new_user_signs_up_from_wishlist(live_server, page, login):
    """Ókunnug manneskja opnar óskalistann, nýskráir sig og Sigga er komin á nýja listann."""
    joi = User.objects.create_user(email="joi@example.com", name="Jói")
    home = Household.objects.create(name="Laugavegur 4", slug="laugavegur-4")
    Membership.objects.create(user=joi, household=home, role=Membership.Role.OWNER)
    season = Season.objects.create(household=home, year=YEAR)
    sigga = Person.objects.create(household=home, name="Sigga", group="born")
    Idea.objects.create(gift=Gift.objects.create(season=season, person=sigga), text="Bangsi", position=0)
    share = services.create_share(sigga, joi)

    page.goto(live_server.url + reverse("wishlists:public", args=[share.token]))
    expect(page.get_by_text("Minnkaðu jólastressið!")).to_be_visible()
    page.get_by_role("link", name=re.compile("Bæta á minn lista")).click()
    expect(page.get_by_text("svo getur Sigga bæst á hann")).to_be_visible()
    # Nýskráningin er eitt skref: heimili, nafn, netfang og lykilorð
    page.get_by_label("Nafn heimilis").fill("Heima hjá Dísu")
    page.get_by_label("Hvað heitir þú?").fill("Dísa")
    page.get_by_label("Netfang").fill("ny@example.com")
    page.get_by_label("Lykilorð").fill("jolasveinn-123")
    page.get_by_role("button", name=re.compile("Stofna aðgang")).click()

    popup = page.locator("dialog.follow-dlg")
    expect(popup).to_be_visible()
    popup.get_by_role("button", name=re.compile("Bæta á listann")).click()
    expect(page.get_by_text("Hugmyndir sem þú bætir við sjást ekki")).to_be_visible()
    row = page.locator(".row.gift", has=page.get_by_role("button", name="Sigga", exact=True))
    expect(row.locator(".idea-line.feed")).to_contain_text("Bangsi")
