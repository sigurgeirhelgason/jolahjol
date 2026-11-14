"""Óskabeiðni: einstaklingurinn fær hlekk og skrifar sjálfur óskirnar sínar á listann."""

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.gifts.models import Gift, Idea
from apps.households.models import Membership
from apps.wishlists import services
from apps.wishlists.models import WishRequest
from tests.factories import (
    GiftFactory,
    IdeaFactory,
    MembershipFactory,
    PersonFactory,
    SeasonFactory,
    giver,
)

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def member():
    return MembershipFactory(role=Membership.Role.OWNER, household__name="Jói og Anna")


@pytest.fixture
def disa(member):
    return PersonFactory(household=member.household, name="Dísa frænka")


@pytest.fixture
def req(disa, member):
    return services.create_request(disa, member.user, "7")


def page(token):
    return reverse("wishlists:request", args=[token])


def this_years_gift(person):
    return GiftFactory(season=SeasonFactory(household=person.household, year=YEAR), person=person)


# ---------- Heimilið: hlekkurinn ----------


def test_member_creates_link_with_chosen_lifetime_and_revokes(client, member, disa):
    client.force_login(member.user)
    url = reverse("wishlists:request_create", args=[member.household.slug, disa.pk])
    before = timezone.now()
    r = client.post(url, {"lifetime": "3"}, **HX)
    assert r.status_code == 200
    req = WishRequest.objects.get(person=disa)
    assert req.token in r.content.decode()
    three = datetime.timedelta(days=3)
    assert before + three <= req.expires_at <= timezone.now() + three

    client.post(url, {"lifetime": "30"}, **HX)  # nýr hlekkur: sá gamli hættir að virka
    assert services.get_request(req.token) is None
    assert services.active_request(disa).expires_at > timezone.now() + datetime.timedelta(days=29)

    client.post(reverse("wishlists:request_revoke", args=[member.household.slug, disa.pk]), **HX)
    assert services.active_request(disa) is None


def test_unknown_lifetime_falls_back_to_default(client, member, disa):
    client.force_login(member.user)
    url = reverse("wishlists:request_create", args=[member.household.slug, disa.pk])
    client.post(url, {"lifetime": "999"}, **HX)
    expires = WishRequest.objects.get(person=disa).expires_at
    assert datetime.timedelta(days=6) < expires - timezone.now() <= datetime.timedelta(days=7)


def test_until_christmas_ends_after_christmas_eve():
    tz = timezone.get_current_timezone()
    nov = datetime.datetime(2026, 11, 14, 12, tzinfo=tz)
    assert timezone.localtime(services.expiry("jol", nov)) == datetime.datetime(2026, 12, 25, tzinfo=tz)
    late = datetime.datetime(2026, 12, 27, 12, tzinfo=tz)
    assert timezone.localtime(services.expiry("jol", late)).date() == datetime.date(2027, 12, 25)


def test_other_household_cannot_create_link(client, disa):
    other = MembershipFactory(role=Membership.Role.OWNER)
    client.force_login(other.user)
    r = client.post(reverse("wishlists:request_create", args=[disa.household.slug, disa.pk]), **HX)
    assert r.status_code == 404
    assert not WishRequest.objects.exists()


def test_no_request_for_household_members(client, member):
    """Notendur heimilisins skrá óskir sjálfir í appinu."""
    anna = MembershipFactory(household=member.household)
    anna.person = PersonFactory(household=member.household, name="Anna")
    anna.save()
    client.force_login(member.user)
    r = client.post(reverse("wishlists:request_create", args=[member.household.slug, anna.person.pk]), **HX)
    assert r.status_code == 404
    dialog = client.get(reverse("gifts:person", args=[member.household.slug, anna.person.pk]), **HX)
    assert "Biðja um óskir" not in dialog.content.decode()


def test_person_dialog_shows_request_section(client, member, disa):
    client.force_login(member.user)
    r = client.get(reverse("gifts:person", args=[member.household.slug, disa.pk]), **HX)
    assert "Biðja um óskir" in r.content.decode()


# ---------- Opna síðan ----------


def test_page_needs_no_login(client, req):
    r = client.get(page(req.token))
    assert r.status_code == 200
    assert "Hæ Dísa frænka!" in r.content.decode()
    assert "noindex" in r["X-Robots-Tag"]


def test_expired_or_revoked_link_is_gone(client, req, disa):
    req.expires_at = timezone.now() - datetime.timedelta(minutes=1)
    req.save()
    r = client.get(page(req.token))
    assert r.status_code == 404
    assert "útrunninn" in r.content.decode()
    assert client.post(page(req.token), {"text": "sokkar"}, **HX).status_code == 404

    fresh = services.create_request(disa, None, "1")
    services.revoke_request(disa)
    assert client.get(page(fresh.token)).status_code == 404
    assert not Idea.objects.exists()


def test_adding_like_the_gift_list_creates_this_years_gift(client, req, disa):
    """„+ Hugmynd“ eins og á listanum: komma aðskilur og svarið er línan sjálf."""
    r = client.post(page(req.token), {"text": "Ullarsokkar, spil"}, **HX)
    assert r.status_code == 200
    body = r.content.decode()
    assert 'id="wish-row"' in body and "Ullarsokkar" in body and "spil" in body
    gift = Gift.objects.get(person=disa, season__year=YEAR)
    assert [(i.text, i.wish) for i in gift.ideas.all()] == [("Ullarsokkar", True), ("spil", True)]
    assert "Ullarsokkar" in client.get(page(req.token)).content.decode()


def test_duplicate_and_empty_wish_ignored(client, req, disa):
    client.post(page(req.token), {"text": ""}, **HX)
    assert not Gift.objects.filter(person=disa).exists()  # engin gjöf fyrr en fyrsta óskin kemur
    client.post(page(req.token), {"text": "Bók"}, **HX)
    client.post(page(req.token), {"text": " bók "}, **HX)
    assert Idea.objects.count() == 1


def test_page_never_shows_household_ideas_or_status(client, req, disa, member):
    """Hún sér aðeins eigin óskir, ekki hugmyndir heimilisins, verð, gefendur né stöðu."""
    gift = this_years_gift(disa)
    IdeaFactory(gift=gift, text="leyndo-hugmynd", price=5000)
    mine = IdeaFactory(gift=gift, text="Trefill", wish=True, reserved=True, price=7777)
    giver(mine, PersonFactory(household=member.household, name="Leynigefandi"))
    for body in (
        client.get(page(req.token)).content.decode(),
        client.get(reverse("wishlists:request_edit", args=[req.token, mine.pk])).content.decode(),
    ):
        assert "Trefill" in body
        for secret in ("leyndo-hugmynd", "Leynigefandi", "7.777", "Frátekið", "Keypt"):
            assert secret not in body
    # Sami texti og hugmynd heimilisins kemur ekki upp um hana: hún bætist við
    client.post(page(req.token), {"text": "Leyndo-hugmynd"}, **HX)
    assert gift.ideas.filter(wish=True, text="Leyndo-hugmynd").exists()


def test_edit_in_wish_dialog_and_delete(client, req):
    client.post(page(req.token), {"text": "Bók"}, **HX)
    idea = Idea.objects.get()
    url = reverse("wishlists:request_edit", args=[req.token, idea.pk])
    dialog = client.get(url, **HX).content.decode()
    assert "Hugmyndin þín" in dialog and url in dialog
    r = client.post(url, {"text": "Glæpasaga", "note": "eftir Arnald", "link": ""}, **HX)
    assert r["HX-Retarget"] == "#wish-row"
    assert "closeModal" in r["HX-Trigger-After-Settle"]
    idea.refresh_from_db()
    assert (idea.text, idea.note) == ("Glæpasaga", "eftir Arnald")
    assert client.post(url, {"text": ""}, **HX).status_code == 422

    r = client.post(reverse("wishlists:request_delete", args=[req.token, idea.pk]), **HX)
    assert r.status_code == 200 and "Glæpasaga" not in r.content.decode()
    assert not Idea.objects.exists()


def test_deleting_a_reserved_wish_keeps_it_for_the_household(client, req, disa):
    idea = IdeaFactory(gift=this_years_gift(disa), text="Trefill", wish=True, reserved=True)
    client.post(reverse("wishlists:request_delete", args=[req.token, idea.pk]), **HX)
    idea.refresh_from_db()
    assert idea.wish is False  # horfin hjá henni, en frátekningin helst
    assert "Trefill" not in client.get(page(req.token)).content.decode()


def test_cannot_touch_other_ideas(client, req, disa):
    theirs = IdeaFactory(gift=this_years_gift(disa), text="leyndo", wish=False)
    other = IdeaFactory(text="annars", wish=True)
    for idea in (theirs, other):
        url = reverse("wishlists:request_edit", args=[req.token, idea.pk])
        assert client.get(url).status_code == 404
        assert client.post(url, {"text": "hakk"}).status_code == 404
        client.post(reverse("wishlists:request_delete", args=[req.token, idea.pk]))
    assert set(Idea.objects.values_list("text", flat=True)) == {"leyndo", "annars"}


def test_own_row_on_gift_list_unchanged(client, member):
    """„Ég“-línan á gjafalistanum notar sama sniðmát og óskabeiðnin."""
    me = PersonFactory(household=member.household, name="Jói")
    member.person = me
    member.save()
    gift = this_years_gift(me)
    IdeaFactory(gift=gift, text="Mín ósk", wish=True)
    client.force_login(member.user)
    body = client.get(reverse("gifts:season", args=[member.household.slug, YEAR])).content.decode()
    assert f'id="gift-{gift.pk}"' in body and "Mín ósk" in body
    assert reverse("gifts:idea_add", args=[member.household.slug, gift.pk]) in body


# ---------- Heimilið felur ósk (× á línunni) ----------


def list_html(client, member):
    return client.get(reverse("gifts:season", args=[member.household.slug, YEAR])).content.decode()


def test_household_hides_wish_but_she_still_sees_it(client, req, disa, member):
    client.post(page(req.token), {"text": "Hestur, Bók"}, **HX)
    hestur = Idea.objects.get(text="Hestur")
    client.force_login(member.user)
    assert "Fela hugmynd: Hestur" in list_html(client, member)

    r = client.post(reverse("gifts:idea_remove", args=[member.household.slug, hestur.pk]), **HX)
    assert r.status_code == 200
    body = r.content.decode()
    assert "Hestur" in body and "Afturkalla" in body  # aðeins í tilkynningunni
    hestur.refresh_from_db()
    assert hestur.hidden and hestur.wish
    listing = list_html(client, member)
    assert ">Hestur<" not in listing and "Bók" in listing

    # Opni óskalistinn sýnir hana ekki heldur
    share = services.create_share(disa, member.user)
    assert "Hestur" not in client.get(reverse("wishlists:public", args=[share.token])).content.decode()

    # Hún sér hana áfram og getur ekki bætt henni við aftur (tvítekning)
    client.logout()
    assert "Hestur" in client.get(page(req.token)).content.decode()
    client.post(page(req.token), {"text": "hestur"}, **HX)
    assert Idea.objects.filter(text__iexact="hestur").count() == 1

    # Afturkalla
    client.force_login(member.user)
    client.post(reverse("gifts:idea_unhide", args=[member.household.slug, hestur.pk]), **HX)
    hestur.refresh_from_db()
    assert not hestur.hidden


def test_cannot_hide_reserved_wish(client, disa, member):
    idea = IdeaFactory(gift=this_years_gift(disa), text="Trefill", wish=True, reserved=True)
    client.force_login(member.user)
    assert "Fela hugmynd" not in list_html(client, member)
    r = client.post(reverse("gifts:idea_remove", args=[member.household.slug, idea.pk]), **HX)
    assert r.status_code == 403
    idea.refresh_from_db()
    assert not idea.hidden


def test_household_can_add_same_text_as_hidden_wish(client, disa, member):
    gift = this_years_gift(disa)
    IdeaFactory(gift=gift, text="Hestur", wish=True, hidden=True)
    client.force_login(member.user)
    client.post(reverse("gifts:idea_add", args=[member.household.slug, gift.pk]), {"text": "hestur"}, **HX)
    assert gift.ideas.filter(wish=False, text="hestur").exists()


def test_she_deletes_hidden_wish_for_good(client, req, disa):
    idea = IdeaFactory(gift=this_years_gift(disa), text="Hestur", wish=True, hidden=True)
    client.post(reverse("wishlists:request_delete", args=[req.token, idea.pk]), **HX)
    assert not Idea.objects.filter(pk=idea.pk).exists()


def test_member_still_sees_own_hidden_wish(client, member):
    me = PersonFactory(household=member.household, name="Jói")
    member.person = me
    member.save()
    IdeaFactory(gift=this_years_gift(me), text="Falin ósk", wish=True, hidden=True)
    client.force_login(member.user)
    assert "Falin ósk" in list_html(client, member)


# ---------- Ósk keypt eða tekin frá: afrit sem heimilið á ----------


@pytest.fixture
def trefill(disa):
    return IdeaFactory(gift=this_years_gift(disa), text="Trefill", note="grár", wish=True, price=5000)


def bought(client, member, idea, on=True):
    url = reverse("gifts:idea_bought", args=[member.household.slug, idea.pk])
    return client.post(url, {"bought": "on"} if on else {}, **HX)


def test_buying_her_wish_makes_our_own_copy(client, req, member, disa, trefill):
    client.force_login(member.user)
    assert bought(client, member, trefill).status_code == 200
    trefill.refresh_from_db()
    assert trefill.hidden and trefill.reserved and not trefill.picked
    copy = trefill.copies.get()
    assert (copy.text, copy.note, copy.price) == ("Trefill", "grár", 5000)
    assert copy.picked and not copy.wish
    assert list_html(client, member).count("Trefill") >= 1  # afritið á listanum

    # Afritið er okkar: glugginn er ekki læstur og efninu má breyta
    dialog = client.get(reverse("gifts:idea", args=[member.household.slug, copy.pk]), **HX).content.decode()
    assert 'name="text"' in dialog
    client.post(
        reverse("gifts:idea", args=[member.household.slug, copy.pk]),
        {"text": "Rauður trefill", "note": "", "store": "Rúmfó", "price": "4500", "picked": "on"},
        **HX,
    )
    copy.refresh_from_db()
    assert (copy.text, copy.price, copy.store.name) == ("Rauður trefill", 4500, "Rúmfó")
    trefill.refresh_from_db()
    assert trefill.text == "Trefill"  # óskin hennar óbreytt

    # Hún sér óskina sína áfram, ekkert um kaupin
    client.logout()
    body = client.get(page(req.token)).content.decode()
    assert "Trefill" in body and "Rauður" not in body and "Rúmfó" not in body

    # Opni óskalistinn: tekin, sést ekki
    share = services.create_share(disa, member.user)
    assert "Trefill" not in client.get(reverse("wishlists:public", args=[share.token])).content.decode()


def test_unchecking_unchanged_copy_brings_wish_back(client, member, trefill):
    client.force_login(member.user)
    bought(client, member, trefill)
    copy = trefill.copies.get()
    bought(client, member, copy, on=False)
    assert not Idea.objects.filter(pk=copy.pk).exists()  # óbreytt afrit hverfur
    trefill.refresh_from_db()
    assert not trefill.hidden and not trefill.reserved and trefill.reservation_secret == ""


def test_unchecking_edited_copy_keeps_it_and_frees_wish(client, member, trefill):
    client.force_login(member.user)
    bought(client, member, trefill)
    copy = trefill.copies.get()
    dialog_post(client, member, copy, text="Annar trefill", picked="on")
    copy.refresh_from_db()
    assert copy.edited
    bought(client, member, copy, on=False)
    copy.refresh_from_db()
    trefill.refresh_from_db()
    assert copy.source is None and not copy.picked  # okkar hugmynd, ótengd óskinni
    assert not trefill.hidden and not trefill.reserved


def test_deleting_copy_frees_wish(client, member, trefill):
    client.force_login(member.user)
    bought(client, member, trefill)
    copy = trefill.copies.get()
    client.post(reverse("gifts:idea_remove", args=[member.household.slug, copy.pk]), **HX)
    trefill.refresh_from_db()
    assert not trefill.hidden and not trefill.reserved


def test_reserving_in_dialog_makes_copy_and_unreserving_frees_it(client, member, trefill):
    client.force_login(member.user)
    url = reverse("gifts:idea", args=[member.household.slug, trefill.pk])
    client.post(url, {"text": "x", "price": "", "reserved": "on"}, **HX)
    trefill.refresh_from_db()
    copy = trefill.copies.get()
    assert trefill.hidden and trefill.reserved
    assert copy.reserved and not copy.picked and copy.text == "Trefill" and copy.note == "grár"
    client.post(
        reverse("gifts:idea", args=[member.household.slug, copy.pk]),
        {"text": "Trefill", "note": "grár", "price": "5000"},
        **HX,
    )
    trefill.refresh_from_db()
    assert not Idea.objects.filter(pk=copy.pk).exists()
    assert not trefill.hidden and not trefill.reserved


def test_price_dialog_takes_only_when_saved(client, member, disa):
    wish = IdeaFactory(gift=this_years_gift(disa), text="Bók", wish=True)  # ekkert verð
    client.force_login(member.user)
    assert bought(client, member, wish)["HX-Retarget"] == "#modal-body"  # verðglugginn
    wish.refresh_from_db()
    assert not wish.hidden and not wish.copies.exists()  # „Hætta“ skilur hana eftir lausa
    client.post(reverse("gifts:idea_price", args=[member.household.slug, wish.pk]), {"amount": "3990"}, **HX)
    wish.refresh_from_db()
    copy = wish.copies.get()
    assert wish.hidden and copy.picked and copy.price == 3990


def test_she_edits_wish_after_purchase_marks_copy(client, req, member, trefill):
    client.force_login(member.user)
    bought(client, member, trefill)
    copy = trefill.copies.get()
    client.logout()
    client.post(
        reverse("wishlists:request_edit", args=[req.token, trefill.pk]),
        {"text": "Trefill", "note": "stærð 40", "link": ""},
        **HX,
    )
    copy.refresh_from_db()
    assert copy.source_changed and copy.note == "grár"  # afritið uppfærist ekki
    client.force_login(member.user)
    assert "breytti óskinni" in list_html(client, member)
    dialog = client.get(reverse("gifts:idea", args=[member.household.slug, copy.pk]), **HX).content.decode()
    assert "stærð 40" in dialog
    client.post(
        reverse("gifts:idea", args=[member.household.slug, copy.pk]),
        {"text": "Trefill", "note": "stærð 40", "price": "5000", "picked": "on"},
        **HX,
    )
    copy.refresh_from_db()
    assert not copy.source_changed and copy.note == "stærð 40"


def test_she_deletes_wish_after_purchase_copy_stays(client, req, member, trefill):
    client.force_login(member.user)
    bought(client, member, trefill)
    copy = trefill.copies.get()
    client.logout()
    client.post(reverse("wishlists:request_delete", args=[req.token, trefill.pk]), **HX)
    assert not Idea.objects.filter(pk=trefill.pk).exists()
    copy.refresh_from_db()
    assert copy.picked and copy.source is None


# ---------- Búð og hlekkur á eigin ósk ----------


def test_she_sets_store_inline_and_in_dialog(client, req, member):
    client.post(page(req.token), {"text": "Spil"}, **HX)
    spil = Idea.objects.get(text="Spil")
    store_url = reverse("wishlists:request_store", args=[req.token, spil.pk])
    r = client.post(store_url, {"store": "Spilavinir"}, **HX)
    assert "Spilavinir" in r.content.decode()
    spil.refresh_from_db()
    assert spil.store.name == "Spilavinir" and spil.store.household == member.household

    url = reverse("wishlists:request_edit", args=[req.token, spil.pk])
    assert 'value="Spilavinir"' in client.get(url, **HX).content.decode()
    client.post(url, {"text": "Spil", "note": "", "store": "", "link": "https://www.nexus.is/x"}, **HX)
    spil.refresh_from_db()
    assert spil.store.name == "Nexus" and spil.link == "https://www.nexus.is/x"  # búð úr hlekknum


def test_public_page_does_not_leak_household_stores(client, req, member):
    from tests.factories import StoreFactory

    StoreFactory(household=member.household, name="LeyniBúð")
    client.post(page(req.token), {"text": "Spil"}, **HX)
    body = client.get(page(req.token)).content.decode()
    assert "LeyniBúð" not in body and "row-store-list" not in body


def test_store_change_after_purchase_marks_copy(client, req, member, trefill):
    client.force_login(member.user)
    bought(client, member, trefill)
    copy = trefill.copies.get()
    client.logout()
    client.post(reverse("wishlists:request_store", args=[req.token, trefill.pk]), {"store": "Rúmfó"}, **HX)
    copy.refresh_from_db()
    assert copy.source_changed and copy.store is None


# ---------- Lagfæringar eftir yfirferð ----------


def dialog_post(client, member, idea, **fields):
    data = {"text": idea.text, "note": idea.note, "price": "" if idea.price is None else str(idea.price)}
    data.update(fields)
    return client.post(reverse("gifts:idea", args=[member.household.slug, idea.pk]), data, **HX)


def test_reserved_then_bought_in_one_save_keeps_wish_taken(client, member, trefill):
    """Frátekið af og Keypt á í sömu vistun má ekki losa óskina á milli skrefa."""
    client.force_login(member.user)
    dialog_post(client, member, trefill, reserved="on", givers="Amma")
    copy = trefill.copies.get()
    dialog_post(client, member, copy, picked="on", givers="Amma")
    copy.refresh_from_db()
    trefill.refresh_from_db()
    assert copy.picked and not copy.reserved and copy.giver_links.count() == 1
    assert trefill.hidden and trefill.reserved
    assert Idea.objects.filter(gift=trefill.gift).count() == 2  # óskin + eitt afrit


def test_double_click_makes_one_copy(client, member, trefill):
    from apps.gifts.services.gifts import take_wish

    first = take_wish(trefill)
    second = take_wish(trefill)  # eins og önnur beiðni sem beið eftir læsingunni
    assert first.pk == second.pk and trefill.copies.count() == 1


def test_copy_with_givers_stays_when_unchecked(client, member, trefill):
    client.force_login(member.user)
    dialog_post(client, member, trefill, picked="on", givers="Amma")
    copy = trefill.copies.get()
    bought(client, member, copy, on=False)
    copy.refresh_from_db()
    trefill.refresh_from_db()
    assert copy.source_id == trefill.pk and [g.person.name for g in copy.giver_links.all()] == ["Amma"]
    assert trefill.hidden  # óskin er enn tekin: afritið er í notkun (gefandi)


def test_unchecked_copy_gives_price_back_to_wish(client, member, disa):
    wish = IdeaFactory(gift=this_years_gift(disa), text="Bók", wish=True)
    client.force_login(member.user)
    client.post(reverse("gifts:idea_price", args=[member.household.slug, wish.pk]), {"amount": "3990"}, **HX)
    copy = wish.copies.get()
    bought(client, member, copy, on=False)
    wish.refresh_from_db()
    assert not Idea.objects.filter(pk=copy.pk).exists()
    assert not wish.hidden and wish.price == 3990


def test_adding_giver_only_makes_copy(client, member, trefill):
    """Leið A: gefandi (án Keypt/Frátekið) fer á afrit, ekki á ósk viðtakandans."""
    client.force_login(member.user)
    dialog_post(client, member, trefill, givers="Amma")
    trefill.refresh_from_db()
    copy = trefill.copies.get()
    assert not trefill.giver_links.exists() and copy.giver_links.count() == 1
    assert trefill.hidden and not copy.picked and not copy.reserved


def test_price_only_stays_on_wish(client, member, trefill):
    client.force_login(member.user)
    dialog_post(client, member, trefill, price="6000")
    trefill.refresh_from_db()
    assert trefill.price == 6000 and not trefill.hidden and not trefill.copies.exists()


def test_after_christmas_eve_wishes_go_to_next_year(client, req, disa, monkeypatch):
    import datetime as dt

    boxing_day = timezone.make_aware(dt.datetime(YEAR, 12, 27, 12))
    monkeypatch.setattr(timezone, "now", lambda: boxing_day)
    assert services.christmas_year() == YEAR + 1
    req.expires_at = boxing_day + dt.timedelta(days=7)
    req.save()
    client.post(page(req.token), {"text": "Skíði"}, **HX)
    assert Idea.objects.get(text="Skíði").gift.season.year == YEAR + 1


def test_saving_unchanged_wish_does_not_mark_copy(client, req, member, trefill):
    client.force_login(member.user)
    bought(client, member, trefill)
    copy = trefill.copies.get()
    client.logout()
    url = reverse("wishlists:request_edit", args=[req.token, trefill.pk])
    client.post(url, {"text": "Trefill", "note": "grár", "store": "", "link": ""}, **HX)
    copy.refresh_from_db()
    assert not copy.source_changed


def test_unhide_only_for_wishes_hidden_with_x(client, member, trefill):
    client.force_login(member.user)
    url = reverse("gifts:idea_unhide", args=[member.household.slug, trefill.pk])
    assert client.post(url, **HX).status_code == 404  # ekki falin
    bought(client, member, trefill)
    assert client.post(url, **HX).status_code == 404  # tekin (afrit til)
    trefill.refresh_from_db()
    assert trefill.hidden


@pytest.mark.django_db(transaction=True)
def test_unchecking_copy_works_outside_test_transaction(client, member, trefill):
    """Eins og í raunverulegri beiðni (engin ytri færsla): release læsir línum (select_for_update)."""
    client.force_login(member.user)
    bought(client, member, trefill)
    copy = trefill.copies.get()
    assert bought(client, member, copy, on=False).status_code == 200
    trefill.refresh_from_db()
    assert not trefill.hidden and not Idea.objects.filter(pk=copy.pk).exists()


# ---------- Lagfæringar eftir aðra yfirferð ----------


def test_stale_double_click_picks_the_copy_not_the_wish(client, member, trefill):
    """Seinni beiðnin hafði sótt óskina áður en sú fyrri kláraðist: hún hakar við afritið."""
    from apps.gifts.services.gifts import take_wish

    stale = Idea.objects.get(pk=trefill.pk)  # sótt áður en fyrri beiðnin tók óskina
    first = take_wish(trefill)
    second = take_wish(stale)
    assert second.pk == first.pk
    client.force_login(member.user)
    bought(client, member, trefill)  # gamalt eintak af síðunni: hakar við óskina sjálfa
    trefill.refresh_from_db()
    assert not trefill.picked and trefill.copies.count() == 1


def test_wish_freed_even_if_copy_reservation_was_cleared(client, member, trefill):
    client.force_login(member.user)
    dialog_post(client, member, trefill, reserved="on")
    copy = trefill.copies.get()
    copy.reservation_secret = ""  # t.d. „fjarlægja frátekningu“ hreinsaði leyndarmálið
    copy.save()
    dialog_post(client, member, copy)  # Frátekið af
    trefill.refresh_from_db()
    assert not trefill.hidden and not trefill.reserved
    assert not Idea.objects.filter(pk=copy.pk).exists()


def test_recipient_edit_does_not_make_copy_count_as_ours(client, req, member, trefill):
    """Dísa breytir „skór 38“ í „skór 40“: afhakað afrit hverfur, ekki tvær hugmyndir."""
    client.force_login(member.user)
    bought(client, member, trefill)
    copy = trefill.copies.get()
    client.logout()
    client.post(
        reverse("wishlists:request_edit", args=[req.token, trefill.pk]),
        {"text": "Trefill", "note": "stærð 40", "store": "", "link": ""},
        **HX,
    )
    client.force_login(member.user)
    bought(client, member, copy, on=False)
    assert not Idea.objects.filter(pk=copy.pk).exists()
    trefill.refresh_from_db()
    assert not trefill.hidden and trefill.note == "stærð 40"


def test_link_stops_working_when_person_joins(client, req, member, disa):
    joined = MembershipFactory(household=member.household)
    joined.person = disa
    joined.save()
    assert client.get(page(req.token)).status_code == 404
    assert client.post(page(req.token), {"text": "x"}, **HX).status_code == 404


def test_recipient_deletes_bought_hidden_wish_keeps_purchase(member, disa):
    """Eldri gögn: ósk sem er bæði keypt og falin heldur sér sem hugmynd heimilisins."""
    from apps.gifts.services.gifts import remove_wish

    idea = IdeaFactory(gift=this_years_gift(disa), text="Hjól", wish=True, picked=True, hidden=True)
    remove_wish(idea)
    idea.refresh_from_db()
    assert idea.picked and not idea.wish and not idea.hidden


def test_inline_store_on_copy_marks_it_edited(client, member, trefill):
    client.force_login(member.user)
    bought(client, member, trefill)
    copy = trefill.copies.get()
    client.post(reverse("gifts:idea_store", args=[member.household.slug, copy.pk]), {"store": "Elko"}, **HX)
    copy.refresh_from_db()
    assert copy.edited and copy.store.name == "Elko"


# ---------- Lagfæringar eftir þriðju yfirferð ----------


def test_joining_does_not_turn_our_copies_into_her_wishes(client, member, disa, trefill):
    """Dísa gengur í heimilið eftir að Jói keypti óskina: hún sér hana einu sinni, ekki kaupin."""
    from apps.households.services import claim_person

    client.force_login(member.user)
    bought(client, member, trefill)
    copy = trefill.copies.get()
    joined = MembershipFactory(household=member.household)
    claim_person(joined, person=disa)
    copy.refresh_from_db()
    assert not copy.wish
    client.force_login(joined.user)
    body = list_html(client, joined)
    assert body.count(">Trefill") == 1


def test_link_stops_working_when_her_gift_was_deleted(client, req, disa):
    from apps.gifts.services.gifts import soft_delete

    gift = this_years_gift(disa)
    soft_delete(gift)
    assert client.get(page(req.token)).status_code == 404
    assert client.post(page(req.token), {"text": "sokkar"}, **HX).status_code == 404
    assert Gift.objects.filter(person=disa).count() == 1  # engin ný gjöf


def test_removing_reservation_on_copy_frees_wish(client, member, trefill):
    client.force_login(member.user)
    dialog_post(client, member, trefill, reserved="on")
    copy = trefill.copies.get()
    url = reverse("gifts:reservation_remove", args=[member.household.slug, copy.pk])
    client.post(url, **HX)
    trefill.refresh_from_db()
    assert not trefill.hidden and not trefill.reserved
    assert not Idea.objects.filter(pk=copy.pk).exists()


def test_hidden_wish_cannot_be_opened_by_household(client, member, trefill):
    client.force_login(member.user)
    client.post(reverse("gifts:idea_remove", args=[member.household.slug, trefill.pk]), **HX)  # ×
    trefill.refresh_from_db()
    assert trefill.hidden
    for name in ("idea", "idea_bought", "idea_price", "reservation_remove"):
        r = client.post(
            reverse(f"gifts:{name}", args=[member.household.slug, trefill.pk]), {"price": "1"}, **HX
        )
        assert r.status_code == 404, name
    assert (
        client.get(reverse("gifts:idea", args=[member.household.slug, trefill.pk]), **HX).status_code == 404
    )


def test_store_from_link_does_not_count_as_our_edit(client, member, disa):
    wish = IdeaFactory(gift=this_years_gift(disa), text="Spil", wish=True, link="https://www.elko.is/x")
    client.force_login(member.user)
    dialog_post(client, member, wish, picked="on")
    copy = wish.copies.get()
    dialog_post(client, member, copy, link=copy.link, store="")  # vistað óbreytt, Keypt af
    assert not Idea.objects.filter(pk=copy.pk).exists()  # ekki „breytt af okkur“: hverfur
    wish.refresh_from_db()
    assert not wish.hidden


def test_she_can_clear_store_when_link_stays(client, req, disa):
    idea = IdeaFactory(gift=this_years_gift(disa), text="Spil", wish=True, link="https://www.elko.is/x")
    url = reverse("wishlists:request_edit", args=[req.token, idea.pk])
    client.post(url, {"text": "Spil", "note": "", "store": "Nexus", "link": idea.link}, **HX)
    idea.refresh_from_db()
    assert idea.store.name == "Nexus"
    client.post(url, {"text": "Spil", "note": "", "store": "", "link": idea.link}, **HX)
    idea.refresh_from_db()
    assert idea.store is None


# ---------- Lagfæringar eftir fjórðu yfirferð ----------


def test_hide_checks_state_under_lock(member, trefill):
    """Úrelt eintak (sótt áður en einhver tók óskina frá) getur hvorki falið né birt hana."""
    from apps.gifts.services.gifts import hide_wish

    stale = Idea.objects.get(pk=trefill.pk)
    Idea.objects.filter(pk=trefill.pk).update(reserved=True)  # frátekið af opna óskalistanum
    with pytest.raises(ValueError):
        hide_wish(stale)
    Idea.objects.filter(pk=trefill.pk).update(hidden=True)  # tekin (afrit): ekki birt aftur
    with pytest.raises(ValueError):
        hide_wish(stale, hidden=False)
    trefill.refresh_from_db()
    assert trefill.hidden and trefill.reserved


def test_deleting_copy_gives_price_back_to_wish(client, member, trefill):
    client.force_login(member.user)
    dialog_post(client, member, trefill, picked="on", price="4000")
    copy = trefill.copies.get()
    client.post(reverse("gifts:idea_remove", args=[member.household.slug, copy.pk]), **HX)
    trefill.refresh_from_db()
    assert not trefill.hidden and trefill.price == 4000


def test_dialog_says_why_link_is_closed(client, member, disa, req):
    from apps.gifts.services.gifts import soft_delete

    soft_delete(this_years_gift(disa))
    client.force_login(member.user)
    dialog = client.get(reverse("gifts:person", args=[member.household.slug, disa.pk]), **HX)
    assert "virkar ekki á meðan gjöfin í ár er eydd" in dialog.content.decode()


def test_clearing_store_on_copy_counts_as_our_edit(client, member, disa):
    from tests.factories import StoreFactory

    elko = StoreFactory(household=member.household, name="Elko")
    wish = IdeaFactory(gift=this_years_gift(disa), text="Spil", wish=True, store=elko)
    client.force_login(member.user)
    dialog_post(client, member, wish, picked="on")
    copy = wish.copies.get()
    dialog_post(client, member, copy, store="", picked="on")  # búðin hreinsuð
    copy.refresh_from_db()
    assert copy.store is None and copy.edited


def test_x_button_follows_can_hide(client, member, trefill):
    client.force_login(member.user)
    assert "Fela hugmynd: Trefill" in list_html(client, member)
    Idea.objects.filter(pk=trefill.pk).update(reserved=True)
    assert "Fela hugmynd: Trefill" not in list_html(client, member)
