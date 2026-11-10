"""Jói býður Dísu úr glugganum hennar; Ásdís (eins og hún kallar sig) sér bara óskirnar sínar."""

import re

from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect

from apps.accounts.models import User
from apps.gifts.models import Idea

YEAR = timezone.localdate().year


def test_invite_from_person_and_recipient_sees_only_wishes(live_server, page, login, browser):
    # Jói stofnar heimili og fer sjálfur á listann
    login(page, "joi@example.com")
    expect(page).to_have_url(re.compile(r"/heimili/nytt/"))
    page.get_by_label("Nafn heimilis").fill("Okkar")
    page.get_by_label("Hvað heitir þú?").fill("Jói")
    page.get_by_role("button", name="Stofna heimili").click()
    expect(page).to_have_url(re.compile(rf"/{YEAR}/$"))
    expect(page.get_by_role("button", name="Jói", exact=True)).to_be_visible()
    expect(page.get_by_text("Hver ert þú á listanum?")).to_have_count(0)

    # Jói bætir Dísu við með hugmynd og býður henni úr glugganum hennar
    page.get_by_role("button", name="Bæta við aðila í Fjölskylda").click()
    page.locator(".new-row").get_by_label("Nafn", exact=True).fill("Dísa")
    page.locator(".new-row").get_by_label("Áætlað verð").press("Enter")
    chip = page.get_by_label("Ný hugmynd handa Dísa")
    chip.fill("hálsmen")
    chip.press("Enter")
    expect(page.locator(".idea-line", has_text="hálsmen")).to_have_count(1)
    page.get_by_role("button", name="Dísa", exact=True).click()
    dialog = page.locator("#modal")
    dialog.get_by_label("Netfang").fill("asdis@example.com")
    dialog.get_by_role("button", name="Senda boð").click()
    expect(dialog.get_by_text("Boð var sent á")).to_be_visible()
    link = dialog.get_by_label("Boðshlekkur").input_value()
    assert reverse("households:invite_accept", args=["x"]).rsplit("x", 1)[0] in link

    # Ásdís þiggur boðið og skrifar nafnið sitt
    other = browser.new_context(locale="is-IS").new_page()
    other.goto(link)
    login(other, "asdis@example.com", navigate=False)
    expect(other.get_by_text("Á listanum heitir þú")).to_contain_text("Dísa")
    other.get_by_label("Hvað heitir þú?").fill("Ásdís")
    other.get_by_role("button", name="Þiggja boð").click()
    expect(other).to_have_url(re.compile(rf"/{YEAR}/$"))
    assert User.objects.get(email="asdis@example.com").name == "Ásdís"

    mine = other.locator(".row.gift.secret")
    expect(mine).to_contain_text("Ásdís")
    expect(other.locator("#group-eg")).to_contain_text("Ég")
    expect(other.locator("#group-eg .row.gift.secret")).to_have_count(1)
    expect(other.locator("#sections")).not_to_contain_text("hálsmen")
    expect(mine.locator("input[type=checkbox]")).to_have_count(0)
    expect(mine.locator("input[name=plan]")).to_have_count(0)
    wish = mine.get_by_label("Ný hugmynd fyrir þig")
    wish.fill("bók")
    wish.press("Enter")
    expect(other.locator(".row.gift.secret")).to_contain_text("bók")
    assert Idea.objects.get(text="bók").wish

    # Jói sér Dísu (ekki Ásdísi), óskina hennar og sína hugmynd
    page.reload()
    disa = page.locator(".row.gift", has=page.get_by_role("button", name="Dísa", exact=True))
    expect(disa).to_contain_text("hálsmen")
    expect(disa).to_contain_text("bók")
    expect(page.locator("#sections")).not_to_contain_text("Ásdís")
