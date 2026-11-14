"""Þú sérð ekki hvað aðrir ætla að gefa þér (Membership.person, Idea.wish, services/privacy.py)."""

import datetime

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.gifts import listing
from apps.gifts.models import Gift, Idea, Person
from apps.gifts.services import birthdays, people
from apps.gifts.services.privacy import Viewer
from apps.households import services as household_services
from apps.households.models import Household, Membership
from apps.wishlists import services as wishlist_services
from tests.factories import (
    GiftFactory,
    IdeaFactory,
    MembershipFactory,
    PersonFactory,
    SeasonFactory,
    UserFactory,
    giver,
)

pytestmark = pytest.mark.django_db

THIS_YEAR = timezone.localdate().year
HX = {"HTTP_HX_REQUEST": "true"}


def url(name, *args):
    return reverse(f"gifts:{name}", args=args)


@pytest.fixture
def owner():
    return MembershipFactory(role=Membership.Role.OWNER, user=UserFactory(name="Jói"))


@pytest.fixture
def home(owner):
    return owner.household


@pytest.fixture
def season(home):
    return SeasonFactory(household=home, year=THIS_YEAR, budget=100000)


@pytest.fixture
def joi(home, owner):
    p = PersonFactory(household=home, name="Jói", group="fjolskylda")
    owner.person = p
    owner.save()
    return p


@pytest.fixture
def disa(home):
    return PersonFactory(household=home, name="Dísa", group="fjolskylda")


@pytest.fixture
def disa_member(home, disa):
    """Dísa er „Dísa“ á listanum en kallar sig Ásdísi."""
    return MembershipFactory(household=home, person=disa, user=UserFactory(name="Ásdís"))


@pytest.fixture
def gift(season, disa, joi):
    """Gjöf handa Dísu: ein ósk frá henni og ein hugmynd frá Jóa, keypt fyrir 25.000."""
    gift = GiftFactory(season=season, person=disa, plan=30000, bought=True)
    IdeaFactory(gift=gift, text="trefill", wish=True, position=0)
    secret = IdeaFactory(gift=gift, text="leynihálsmen", price=25000, picked=True, position=1)
    giver(secret, joi)
    return gift


@pytest.fixture
def as_disa(client, disa_member):
    client.force_login(disa_member.user)
    return client


@pytest.fixture
def as_joi(client, owner, joi):
    client.force_login(owner.user)
    return client


# ---------- Reglan ----------


def test_only_the_recipient_is_kept_out_always(home, gift, disa, joi):
    assert Viewer(disa.pk).is_secret(gift)
    assert not Viewer(joi.pk).is_secret(gift)
    assert not Viewer().is_secret(gift)
    old = GiftFactory(season=SeasonFactory(household=home, year=THIS_YEAR - 3), person=disa)
    assert Viewer(disa.pk).is_secret(old)  # líka liðin ár


def test_display_name(disa, joi):
    viewer = Viewer(disa.pk, "Ásdís")
    assert viewer.display_name(disa) == "Ásdís"
    assert viewer.display_name(joi) == "Jói"


# ---------- Listinn ----------


def test_recipient_sees_her_own_name_and_only_her_wishes(as_disa, gift, home):
    html = as_disa.get(url("season", home.slug, THIS_YEAR)).text
    assert "Ásdís" in html and "trefill" in html
    assert "<h2>Ég</h2>" in html and 'id="group-eg"' in html
    assert "leynihálsmen" not in html
    assert "25.000" not in html and "30.000" not in html
    assert f'hx-post="{url("bought", home.slug, gift.pk)}"' not in html
    assert f'hx-post="{url("plan", home.slug, gift.pk)}"' not in html


def test_her_own_gift_is_not_in_her_totals(gift, season, disa):
    other = GiftFactory(season=season, person=PersonFactory(household=season.household), plan=5000)
    gl = listing.build_list(season, listing.ListState(), viewer=Viewer(disa.pk))
    assert gl.summary.count == 1 and gl.summary.total_plan == 5000 and gl.summary.spent == 0
    rows = {r.gift.pk: r for s in gl.sections for r in s.rows}
    assert rows[gift.pk].secret and not rows[other.pk].secret
    # Línan hennar er efst í flokknum „Ég“, ekki í Fjölskyldu
    assert gl.sections[0].mine and [r.gift.pk for r in gl.sections[0].rows] == [gift.pk]
    assert gift.pk not in [r.gift.pk for r in gl.section("fjolskylda").rows]
    assert gl.section("fjolskylda").plan == 0
    bought = listing.build_list(season, listing.ListState(filter="keypt"), viewer=Viewer(disa.pk))
    assert all(r.gift.pk != gift.pk for s in bought.sections for r in s.rows)


def test_others_see_everything_and_her_list_name(as_joi, gift, home):
    html = as_joi.get(url("season", home.slug, THIS_YEAR)).text
    assert "leynihálsmen" in html and "25.000" in html and "Dísa" in html
    assert 'id="group-eg"' not in html and "Ásdís" not in html


def test_past_years_stay_hidden(as_disa, home, disa):
    old = GiftFactory(season=SeasonFactory(household=home, year=THIS_YEAR - 1), person=disa, bought=True)
    IdeaFactory(gift=old, text="gamalt leyndó", picked=True)
    assert "gamalt leyndó" not in as_disa.get(url("season", home.slug, THIS_YEAR - 1)).text
    assert "gamalt leyndó" not in as_disa.get(url("person", home.slug, disa.pk), **HX).text
    assert "gamalt leyndó" not in as_disa.get(url("people", home.slug, THIS_YEAR - 1)).text


def test_shop_billing_and_people_pages_leak_nothing(as_disa, gift, home):
    secret = gift.ideas.get(text="leynihálsmen")
    secret.picked = False
    secret.for_other = True
    secret.save()
    for page in ("shop", "billing", "people"):
        html = as_disa.get(url(page, home.slug, THIS_YEAR)).text
        assert "leynihálsmen" not in html, page


# ---------- Aðgerðir viðtakandans ----------


def test_recipient_cannot_touch_her_gift(as_disa, gift, home):
    secret = gift.ideas.get(text="leynihálsmen")
    assert as_disa.get(url("gift_edit", home.slug, gift.pk), **HX).status_code == 404
    assert as_disa.post(url("bought", home.slug, gift.pk), {}, **HX).status_code == 404
    assert as_disa.post(url("plan", home.slug, gift.pk), {"plan": "1"}, **HX).status_code == 404
    assert as_disa.get(url("idea", home.slug, secret.pk), **HX).status_code == 404
    assert as_disa.post(url("idea_remove", home.slug, secret.pk), **HX).status_code == 404
    assert as_disa.post(url("delete", home.slug, gift.pk), **HX).status_code == 404
    wish = gift.ideas.get(text="trefill")
    assert as_disa.post(url("idea_bought", home.slug, wish.pk), {"bought": "on"}, **HX).status_code == 404
    assert Idea.objects.filter(pk=secret.pk).exists()


def test_recipient_adds_and_edits_wishes(as_disa, gift, home):
    response = as_disa.post(url("idea_add", home.slug, gift.pk), {"text": "bók"}, **HX)
    assert response.status_code == 200 and "bók" in response.text and "leynihálsmen" not in response.text
    assert gift.ideas.get(text="bók").wish

    wish = gift.ideas.get(text="trefill")
    html = as_disa.get(url("idea", home.slug, wish.pk), **HX).text
    assert "Hugmyndin þín" in html and "Hver gefur" not in html and "Keypt" not in html
    as_disa.post(url("idea", home.slug, wish.pk), {"text": "rauður trefill", "note": "", "link": ""}, **HX)
    wish.refresh_from_db()
    assert wish.text == "rauður trefill" and wish.wish
    as_disa.post(url("idea_remove", home.slug, wish.pk), **HX)
    assert not Idea.objects.filter(pk=wish.pk).exists()


def test_recipient_sets_store_on_own_ideas_only(as_disa, gift, home):
    wish = gift.ideas.get(text="trefill")
    secret = gift.ideas.get(text="leynihálsmen")
    html = as_disa.get(url("season", home.slug, THIS_YEAR)).text
    assert ">Nafn<" in html and ">Hugmyndir<" in html and ">Búð<" in html
    response = as_disa.post(url("idea_store", home.slug, wish.pk), {"store": "Rúmfó"}, **HX)
    assert response.status_code == 200 and "Rúmfó" in response.text
    wish.refresh_from_db()
    assert wish.store.name == "Rúmfó"
    assert as_disa.post(url("idea_store", home.slug, secret.pk), {"store": "X"}, **HX).status_code == 404


# ---------- Afmæli, áminningar og óskalisti ----------


def test_birthday_card_is_secret_for_recipient(as_disa, home, disa):
    today = timezone.localdate()
    day = today + datetime.timedelta(days=10)
    disa.birthday = day.replace(year=1990)
    disa.give_birthday = True
    disa.save()
    gift = birthdays.ensure_gift(disa, day.year)
    Gift.objects.filter(pk=gift.pk).update(plan=7000)
    IdeaFactory(gift=gift, text="leyniúr", price=9000)
    IdeaFactory(gift=gift, text="ósk um bók", wish=True)
    html = as_disa.get(url("birthdays", home.slug)).text
    assert "ósk um bók" in html and "Leyndarmál" in html and "Ásdís" in html
    card = html[html.index('id="person-') :]
    card = card[: card.index("</article>")]
    assert "leyniúr" not in html
    assert "7.000" not in card and "9.000" not in card


def test_birthday_reminder_not_sent_to_birthday_person(home, owner, disa, disa_member):
    home.birthday_reminders = True
    home.save()
    disa.birthday = datetime.date(1990, 11, 18)
    disa.give_birthday = True
    disa.save()
    assert birthdays.send_reminders(datetime.date(2026, 11, 12)) == 1
    assert mail.outbox[0].to == [owner.user.email]


def test_public_wishlist_of_a_member_shows_only_wishes(gift, disa, disa_member, owner):
    share = wishlist_services.create_share(disa, owner.user)
    _, ideas = wishlist_services.visible_ideas(share)
    assert [i.text for i in ideas] == ["trefill"]


def test_public_wishlist_of_non_member_is_unchanged(season, owner, home):
    hugi = PersonFactory(household=home, name="Hugi")
    gift = GiftFactory(season=season, person=hugi)
    IdeaFactory(gift=gift, text="legó")
    _, ideas = wishlist_services.visible_ideas(wishlist_services.create_share(hugi, owner.user))
    assert [i.text for i in ideas] == ["legó"]


# ---------- Nýtt heimili ----------


def test_creating_household_puts_you_on_the_list(client):
    user = UserFactory(name="")
    client.force_login(user)
    response = client.post(reverse("households:create"), {"name": "Heima", "your_name": "Jói"})
    household = Household.objects.get(name="Heima")
    assert response.url == reverse("gifts:list", args=[household.slug])
    membership = household.memberships.get()
    assert membership.person.name == "Jói" and membership.person.group == "fjolskylda"
    assert Gift.objects.filter(person=membership.person, season__year=THIS_YEAR).exists()
    user.refresh_from_db()
    assert user.name == "Jói"


def test_your_name_is_required(client):
    client.force_login(UserFactory(name=""))
    response = client.post(reverse("households:create"), {"name": "Heima", "your_name": ""})
    assert response.status_code == 200 and not Household.objects.exists()


# ---------- Boð ----------


def test_invite_from_person_dialog(as_joi, home, disa):
    html = as_joi.get(url("person", home.slug, disa.pk), **HX).text
    assert "Senda boð" in html
    invite_url = reverse("households:person_invite", args=[home.slug, disa.pk])
    assert "Skrifaðu netfangið" in as_joi.post(invite_url, **HX).text
    assert "ekki gilt" in as_joi.post(invite_url, {"invite_email": "ekki-netfang"}, **HX).text
    assert not home.invites.exists() and not mail.outbox

    section = as_joi.post(invite_url, {"invite_email": "disa@example.com"}, **HX).text
    invite = home.invites.get()
    assert invite.person == disa and invite.email == "disa@example.com" and invite.token in section
    assert "Boð var sent á" in section
    [message] = mail.outbox
    assert message.to == ["disa@example.com"]
    assert invite.token in message.body and "Á listanum heitir þú Dísa" in message.body
    # Nýtt boð kemur í stað þess eldra
    as_joi.post(invite_url, {"invite_email": "disa@example.com"}, **HX)
    assert home.invites.count() == 1
    as_joi.post(reverse("households:person_invite_revoke", args=[home.slug, disa.pk]), **HX)
    assert not home.invites.exists()


def test_non_owner_cannot_invite_from_person_dialog(client, home, disa, joi):
    member = MembershipFactory(household=home, person=PersonFactory(household=home))
    client.force_login(member.user)
    assert client.post(reverse("households:person_invite", args=[home.slug, disa.pk])).status_code == 403


def test_accepting_person_invite_keeps_list_name(client, home, owner, disa):
    invite = household_services.create_invite(home, owner.user, person=disa)
    user = UserFactory(name="")
    client.force_login(user)
    page = client.get(reverse("households:invite_accept", args=[invite.token])).text
    assert "Á listanum heitir þú <strong>Dísa</strong>" in page
    client.post(reverse("households:invite_accept", args=[invite.token]), {"name": "Ásdís"})
    membership = Membership.objects.get(user=user)
    disa.refresh_from_db()
    user.refresh_from_db()
    assert membership.person == disa and disa.name == "Dísa" and user.name == "Ásdís"
    assert Gift.objects.filter(person=disa, season__year=THIS_YEAR).exists()


def test_general_invite_puts_newcomer_in_family(home, owner):
    invite = household_services.create_invite(home, owner.user)
    membership = household_services.accept_invite(invite.token, UserFactory(), "Gunna")
    assert membership.person.name == "Gunna" and membership.person.group == "fjolskylda"


def test_general_invite_with_taken_name_asks_again(client, home, owner, joi):
    invite = household_services.create_invite(home, owner.user)
    client.force_login(UserFactory())
    response = client.post(reverse("households:invite_accept", args=[invite.token]), {"name": "jói"})
    assert response.status_code == 422 and "nafnið aðeins öðruvísi" in response.text
    invite.refresh_from_db()
    assert invite.accepted_at is None


def test_person_invite_for_taken_person_falls_back_to_name(home, owner, disa, disa_member):
    invite = household_services.create_invite(home, owner.user)
    invite.person = disa
    invite.save()
    membership = household_services.accept_invite(invite.token, UserFactory(), "Önnur")
    assert membership.person.name == "Önnur"


# ---------- Tenging við einstakling ----------


def test_unlinked_member_is_asked_once(client, home, season, disa):
    GiftFactory(season=season, person=disa)
    member = MembershipFactory(household=home, user=UserFactory(name="Dísa"))
    client.force_login(member.user)
    html = client.get(url("season", home.slug, THIS_YEAR)).text
    assert "Hver ert þú á listanum?" in html
    assert f'<option value="{disa.pk}" selected>Dísa</option>' in html  # nafnið passar

    client.post(reverse("households:claim_person", args=[home.slug]), {"person": disa.pk})
    member.refresh_from_db()
    assert member.person == disa
    assert "Hver ert þú á listanum?" not in client.get(url("season", home.slug, THIS_YEAR)).text

    # Seinna getur hann ekki valið aftur
    client.post(reverse("households:claim_person", args=[home.slug]), {"person": "", "name": "Annað"})
    member.refresh_from_db()
    assert member.person == disa


def test_claim_keeps_ideas_already_seen_this_year(client, home, season, disa):
    """Ótengdur meðlimur sá hugmyndirnar á línunni sinni; eftir tenginguna sér hann þær áfram."""
    gift = GiftFactory(season=season, person=disa)
    IdeaFactory(gift=gift, text="bíómynd", picked=True)
    old = GiftFactory(season=SeasonFactory(household=home, year=THIS_YEAR - 1), person=disa)
    IdeaFactory(gift=old, text="gamalt")
    member = MembershipFactory(household=home, user=UserFactory(name="Dísa"))
    client.force_login(member.user)
    client.post(reverse("households:claim_person", args=[home.slug]), {"person": disa.pk})
    html = client.get(url("season", home.slug, THIS_YEAR)).text
    assert "bíómynd" in html
    assert f'hx-post="{url("bought", home.slug, gift.pk)}"' not in html  # staðan samt leynd
    assert not Idea.objects.get(text="gamalt").wish


def test_invited_newcomer_does_not_see_existing_ideas(home, owner, season, disa):
    IdeaFactory(gift=GiftFactory(season=season, person=disa), text="leyndó")
    invite = household_services.create_invite(home, owner.user, person=disa)
    household_services.accept_invite(invite.token, UserFactory(), "Ásdís")
    assert not Idea.objects.get(text="leyndó").wish


def test_claim_with_new_name(client, home, season):
    member = MembershipFactory(household=home)
    client.force_login(member.user)
    client.post(reverse("households:claim_person", args=[home.slug]), {"person": "", "name": "Nýr"})
    member.refresh_from_db()
    assert member.person.name == "Nýr" and member.person.group == "fjolskylda"


def test_nobody_changes_own_link(home, owner, joi):
    with pytest.raises(household_services.HouseholdError):
        household_services.set_person(owner, None, by=owner.user)


def test_owner_changes_others_links(client, home, owner, joi, disa, disa_member):
    link = reverse("households:member_person", args=[home.slug, disa_member.pk])
    client.force_login(disa_member.user)
    assert client.post(link, {"person": ""}).status_code == 403
    disa_member.refresh_from_db()
    assert disa_member.person == disa

    client.force_login(owner.user)
    html = client.get(reverse("households:settings", args=[home.slug])).text
    assert html.count('class="member-person"') == 1  # aðeins fyrir Dísu, ekki eigandann sjálfan
    client.post(link, {"person": ""})
    disa_member.refresh_from_db()
    assert disa_member.person is None


def test_person_can_only_be_linked_once_and_in_same_household(home, owner, disa, disa_member):
    other = MembershipFactory(household=home)
    with pytest.raises(household_services.HouseholdError):
        household_services.set_person(other, disa, by=owner.user)
    with pytest.raises(household_services.HouseholdError):
        household_services.set_person(other, PersonFactory(), by=owner.user)  # annað heimili


def test_merge_keeps_member_link(home, disa, disa_member):
    target = PersonFactory(household=home, name="Dísa Jóns")
    people.merge(disa, target)
    disa_member.refresh_from_db()
    assert disa_member.person == target


def test_linked_person_is_not_deleted_when_gift_is_renamed(season, disa, disa_member):
    gift = GiftFactory(season=season, person=disa)
    people.resolve_recipient(gift, "Einhver annar")
    disa_member.refresh_from_db()
    assert disa_member.person == disa
    assert Person.objects.filter(pk=disa.pk).exists()


def test_settings_only_offers_recipients(client, home, owner, joi, season, disa, disa_member):
    GiftFactory(season=season, person=PersonFactory(household=home, name="Hugi"))
    PersonFactory(household=home, name="Ragnhildi")  # bara gefandi
    client.force_login(owner.user)
    html = client.get(reverse("households:settings", args=[home.slug])).text
    assert ">Hugi</option>" in html and ">Dísa</option>" in html
    assert "Ragnhildi" not in html


def test_invite_from_settings_for_a_person(client, home, owner, joi, season, disa):
    GiftFactory(season=season, person=disa)
    client.force_login(owner.user)
    html = client.get(reverse("households:settings", args=[home.slug])).text
    assert "Hver er þetta á listanum?" in html and f'<option value="{disa.pk}">Dísa</option>' in html
    create = reverse("households:invite_create", args=[home.slug])
    client.post(create, {"person": disa.pk, "email": "disa@example.com"})
    client.post(create, {"person": "", "email": "nyr@example.com"})
    client.post(create, {"person": ""})  # netfang vantar: ekkert boð
    assert sorted(str(i.person) for i in home.invites.all()) == ["Dísa", "None"]
    assert sorted(m.to[0] for m in mail.outbox) == ["disa@example.com", "nyr@example.com"]
    page = client.get(reverse("households:settings", args=[home.slug])).text
    assert "disa@example.com" in page and "fyrir Dísa" in page  # virk boð: netfang og hlekkur


# ---------- Atriði úr yfirferð ----------


def test_two_members_cannot_be_merged(as_disa, home, disa, disa_member, joi):
    """Annars yrði annar notandinn ótengdur og sæi allt sem aðrir ætla að gefa honum."""
    data = {"name": "Jói", "group": "fjolskylda", "birthday": "", "merge": "on"}
    response = as_disa.post(url("person", home.slug, disa.pk), data, **HX)
    assert response.status_code == 422 and "Báðir eru notendur" in response.text
    disa_member.refresh_from_db()
    assert disa_member.person == disa
    with pytest.raises(ValueError):
        people.merge(disa, joi)


def test_recipient_wish_is_not_swallowed_by_hidden_idea(as_disa, gift, home):
    as_disa.post(url("idea_add", home.slug, gift.pk), {"text": "Leynihálsmen"}, **HX)
    assert gift.ideas.filter(text__iexact="leynihálsmen").count() == 2
    assert gift.ideas.get(text="Leynihálsmen").wish


def test_recipient_removing_bought_wish_keeps_it_for_others(as_disa, gift, home, joi):
    wish = gift.ideas.get(text="trefill")
    wish.picked = True
    wish.price = 5000
    wish.save()
    as_disa.post(url("idea_remove", home.slug, wish.pk), **HX)
    wish.refresh_from_db()
    assert wish.picked and not wish.wish  # horfin hjá henni, keypt hjá hinum
    plain = IdeaFactory(gift=gift, text="ný ósk", wish=True)
    as_disa.post(url("idea_remove", home.slug, plain.pk), **HX)
    assert not Idea.objects.filter(pk=plain.pk).exists()


def test_linking_respects_give_christmas(home, owner, season):
    amma = PersonFactory(household=home, name="Amma", give_christmas=False)
    member = MembershipFactory(household=home)
    household_services.set_person(member, amma, by=owner.user)
    assert not Gift.objects.filter(person=amma).exists()


def test_invite_survives_mail_failure(client, home, owner, joi, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("SMTP niðri")

    monkeypatch.setattr("apps.households.services.send_mail", boom)
    client.force_login(owner.user)
    response = client.post(reverse("households:invite_create", args=[home.slug]), {"email": "x@example.com"})
    assert response.status_code == 302
    assert home.invites.get().email == "x@example.com"
    page = client.get(response.url).text
    assert "pósturinn á x@example.com fór ekki" in page


# ---------- Aðeins viðtakandinn breytir sinni hugmynd ----------


def test_others_can_buy_but_not_edit_her_idea(as_joi, gift, home):
    wish = gift.ideas.get(text="trefill")
    html = as_joi.get(url("idea", home.slug, wish.pk), **HX).text
    assert "Aðeins Dísa getur breytt" in html and 'name="text"' not in html
    data = {"text": "breytt", "note": "keypt í Elko", "store": "Elko", "price": "4000", "picked": "on"}
    as_joi.post(url("idea", home.slug, wish.pk), data, **HX)
    wish.refresh_from_db()
    assert wish.text == "trefill" and wish.note == "" and wish.store is None  # efnið óbreytt
    # Kaupin fara á afrit sem heimilið á; óskin verður falin og frátekin (gifts.take_wish)
    assert wish.hidden and wish.reserved and not wish.picked
    copy = wish.copies.get()
    assert copy.picked and copy.price == 4000 and copy.text == "trefill" and not copy.wish
    # Tekin ósk er ekki lengur til í augum heimilisins (falin): hvorki fjarlægð né breytt
    assert as_joi.post(url("idea_remove", home.slug, wish.pk), **HX).status_code == 404
    assert as_joi.post(url("idea_store", home.slug, wish.pk), {"store": "Elko"}, **HX).status_code == 404
    assert Idea.objects.filter(pk=wish.pk, store=None).exists()
    # Ósk annars sem er ekki tekin: má ekki breyta búð hennar
    other = Idea.objects.create(gift=wish.gift, text="vettlingar", wish=True)
    assert as_joi.post(url("idea_store", home.slug, other.pk), {"store": "Elko"}, **HX).status_code == 403


def test_gift_dialog_leaves_her_ideas_alone(as_joi, gift, home):
    html = as_joi.get(url("gift_edit", home.slug, gift.pk), **HX).text
    assert "trefill" not in html  # ekki í kommulistanum
    data = {
        "name": "Dísa",
        "group": "fjolskylda",
        "plan": "",
        "ideas": "leynihálsmen, trefill",
        "store": "",
        "link": "",
    }
    as_joi.post(url("gift_edit", home.slug, gift.pk), data, **HX)
    assert gift.ideas.filter(text="trefill").count() == 1 and gift.ideas.get(text="trefill").wish
    data["ideas"] = ""
    as_joi.post(url("gift_edit", home.slug, gift.pk), data, **HX)
    assert gift.ideas.filter(text="trefill", wish=True).exists()  # hverfur ekki þótt listinn sé tæmdur
