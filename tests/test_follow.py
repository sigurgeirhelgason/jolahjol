"""Fylgja óskalista einstaklings úr öðru heimili (Person.source, Idea.source, wishlists/services).

Dæmið: Jói og Anna („Laugavegur 4“) eiga Siggu og deila óskalistanum hennar. Dísa frænka bætir
Siggu á sitt eigið Jólahjól og sér hugmyndir þeirra á meðan þær eru ekki keyptar eða fráteknar.
"""

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.gifts import listing
from apps.gifts.models import Gift, Idea, IdeaGiver, Person
from apps.gifts.services import gifts as gift_services
from apps.households.models import Membership
from apps.wishlists import services
from tests.factories import (
    GiftFactory,
    HouseholdFactory,
    IdeaFactory,
    MembershipFactory,
    PersonFactory,
    SeasonFactory,
    StoreFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def laugavegur():
    """Heimili Jóa og Önnu, með Siggu og óskalistahlekk hennar."""
    home = HouseholdFactory(name="Laugavegur 4")
    joi = MembershipFactory(household=home, role=Membership.Role.OWNER, user=UserFactory(name="Jói"))
    season = SeasonFactory(household=home, year=YEAR)
    sigga = PersonFactory(household=home, name="Sigga", group="born")
    gift = GiftFactory(season=season, person=sigga)
    IdeaFactory(gift=gift, text="Bangsi", position=0)
    IdeaFactory(gift=gift, text="Bíll", position=1)
    share = services.create_share(sigga, joi.user)
    return {"home": home, "joi": joi, "season": season, "sigga": sigga, "gift": gift, "share": share}


@pytest.fixture
def disa():
    """Dísa frænka og hennar eigið Jólahjól."""
    home = HouseholdFactory(name="Heima hjá Dísu")
    member = MembershipFactory(household=home, role=Membership.Role.OWNER, user=UserFactory(name="Dísa"))
    SeasonFactory(household=home, year=YEAR)
    return member


def follow_url(share):
    return reverse("wishlists:follow", args=[share.token])


def popup_url(member, share):
    """Gjafalistinn með valglugganum opnum, eins og FollowStartView vísar á hann."""
    return reverse("gifts:season", args=[member.household.slug, YEAR]) + f"?fylgja={share.token}"


def texts(member, person_name):
    """Það sem `member` sér á línu `person_name`: (eigin hugmyndir, af óskalista)."""
    season = member.household.seasons.get(year=YEAR)
    viewer_rows = [r for s in listing.build_list(season, listing.ListState()).sections for r in s.rows]
    row = next(r for r in viewer_rows if r.person.name == person_name)
    return [i.text for i in row.gift.ideas.all()], [i.text for i in row.feed]


def test_the_whole_story(client, laugavegur, disa):
    share, sigga, gift = laugavegur["share"], laugavegur["sigga"], laugavegur["gift"]

    # Dísa bætir Siggu við Börn
    client.force_login(disa.user)
    page = client.get(reverse("wishlists:public", args=[share.token])).text
    assert "Á Sigga að vera á þínum lista á jolahjol.is?" in page
    assert "fáðu allar hugmyndir sem Jói bætir við" in page
    response = client.post(
        follow_url(share), {"household": disa.household.slug, "person": "", "name": "Sigga", "group": "born"}
    )
    assert response.url == reverse("gifts:list", args=[disa.household.slug])
    mine = Person.objects.get(household=disa.household, name="Sigga")
    assert mine.source == sigga and mine.group == "born"

    # Dísa bætir Bók við; hún sér Bíl, Bangsa og Bók. Jói og Anna sjá ekki Bók.
    gift_services.add_ideas(Gift.objects.get(person=mine), "Bók")
    assert texts(disa, "Sigga") == (["Bók"], ["Bangsi", "Bíll"])
    assert sorted(gift.ideas.values_list("text", flat=True)) == ["Bangsi", "Bíll"]

    # Jói og Anna bæta við Vettlingum: Dísa sér þá líka
    IdeaFactory(gift=gift, text="Vettlingar", position=2)
    assert texts(disa, "Sigga")[1] == ["Bangsi", "Bíll", "Vettlingar"]

    # Amma tekur Bangsa frá á opnu síðunni: hverfur hjá Dísu
    bangsi = gift.ideas.get(text="Bangsi")
    services.reserve(share, bangsi.pk, "Amma")
    assert texts(disa, "Sigga") == (["Bók"], ["Bíll", "Vettlingar"])

    # Jói sér að Dísa fylgir
    client.force_login(laugavegur["joi"].user)
    dialog = client.get(reverse("gifts:person", args=[laugavegur["home"].slug, sigga.pk]), **HX).text
    assert "Á lista hjá: Dísa" in dialog


def test_follow_someone_already_on_my_list(client, laugavegur, disa):
    season = disa.household.seasons.get(year=YEAR)
    existing = GiftFactory(
        season=season, person=PersonFactory(household=disa.household, name="Sigga litla")
    ).person
    client.force_login(disa.user)
    page = client.get(popup_url(disa, laugavegur["share"])).text
    assert "Sigga litla - Annað" in page  # flokkurinn sést við nafnið
    assert "Allar hugmyndir sem Jói setur inn" in page  # einn notandi í heimilinu sem deildi
    MembershipFactory(household=laugavegur["home"], user=UserFactory(name="Anna"))
    page = client.get(popup_url(disa, laugavegur["share"])).text
    assert "Allar hugmyndir sem Jói og Anna setja inn" in page
    client.post(follow_url(laugavegur["share"]), {"household": disa.household.slug, "person": existing.pk})
    existing.refresh_from_db()
    assert existing.source == laugavegur["sigga"]
    assert texts(disa, "Sigga litla")[1] == ["Bangsi", "Bíll"]


def test_disa_marks_bought_it_is_only_reserved_at_the_source(client, laugavegur, disa):
    gunna = MembershipFactory(household=HouseholdFactory(), user=UserFactory(name="Gunna"))
    SeasonFactory(household=gunna.household, year=YEAR)
    services.follow(laugavegur["share"], gunna.household, name="Sigga")
    mine = services.follow(laugavegur["share"], disa.household, name="Sigga", group="born")
    my_gift = Gift.objects.get(person=mine)
    bill = laugavegur["gift"].ideas.get(text="Bíll")
    bill.price = 3000
    bill.save()

    client.force_login(disa.user)
    client.post(
        reverse("gifts:feed_idea", args=[disa.household.slug, my_gift.pk, bill.pk]), {"action": "keypt"}, **HX
    )
    bill.refresh_from_db()
    assert bill.reserved and not bill.picked  # frátekið hjá Jóa og Önnu, aldrei keypt
    assert bill.reserved_by.name == "Dísa"
    assert IdeaGiver.objects.filter(idea=bill, person__name="Dísa").exists()
    copy = my_gift.ideas.get(source=bill)
    assert copy.picked and copy.price == 3000 and copy.text == "Bíll"
    assert texts(disa, "Sigga") == (["Bíll"], ["Bangsi"])  # tekin: nú hennar hugmynd
    assert texts(gunna, "Sigga")[1] == ["Bangsi"]  # hverfur hjá öðrum sem fylgja

    # Dísa eyðir afritinu: frátekningin hjá Jóa og Önnu fellur niður
    gift_services.remove_idea(copy)
    bill.refresh_from_db()
    assert not bill.reserved and not IdeaGiver.objects.filter(idea=bill, person__name="Dísa").exists()
    assert texts(gunna, "Sigga")[1] == ["Bangsi", "Bíll"]


def test_reserve_without_price_and_ask_price_on_bought(client, laugavegur, disa):
    mine = services.follow(laugavegur["share"], disa.household, name="Sigga")
    my_gift = Gift.objects.get(person=mine)
    bangsi = laugavegur["gift"].ideas.get(text="Bangsi")
    url = reverse("gifts:feed_idea", args=[disa.household.slug, my_gift.pk, bangsi.pk])
    client.force_login(disa.user)
    dialog = client.get(url, **HX).text
    assert "Af óskalista sem Sigga á" in dialog and "heimilisins „Laugavegur 4“" in dialog
    assert "en Jói mun sjá gjöfina sem frátekna" in dialog
    response = client.post(url, {"action": "keypt"}, **HX)
    assert response["HX-Retarget"] == "#modal-body"  # verð vantar: spurt fyrst
    assert "Hvað kostaði gjöfin?" in response.text and url in response.text
    # Ekkert tekið fyrr en verð er skráð eða sleppt („Hætta“ skilur hana eftir lausa)
    bangsi.refresh_from_db()
    assert not bangsi.reserved and not my_gift.ideas.filter(source=bangsi).exists()
    assert client.post(url, {"action": "keypt", "amount": "abc"}, **HX).status_code == 422
    client.post(url, {"action": "keypt", "amount": "2500"}, **HX)
    copy = my_gift.ideas.get(source=bangsi)
    assert copy.picked and copy.price == 2500
    bangsi.refresh_from_db()
    assert bangsi.reserved and not bangsi.picked
    # Tvisvar: þegar tekið
    assert "var á undan þér" in client.post(url, {"action": "fratekid"}, **HX).text


def test_closing_the_link_stops_followers_new_link_keeps_them(laugavegur, disa):
    mine = services.follow(laugavegur["share"], disa.household, name="Sigga")
    services.create_share(laugavegur["sigga"], laugavegur["joi"].user)  # „Nýr hlekkur“
    assert texts(disa, "Sigga")[1] == ["Bangsi", "Bíll"]
    services.revoke(laugavegur["sigga"])  # „Loka hlekk“
    assert texts(disa, "Sigga")[1] == []
    mine.refresh_from_db()
    assert mine.source == laugavegur["sigga"]  # tengingin vaknar aftur ef nýr hlekkur verður til


def test_only_same_year(laugavegur, disa):
    mine = services.follow(laugavegur["share"], disa.household, name="Sigga")
    this_year = Gift.objects.get(person=mine)
    last_year = GiftFactory(season=SeasonFactory(household=disa.household, year=YEAR - 1), person=mine)
    feeds = services.gift_feeds([this_year, last_year])
    assert [i.text for i in feeds[this_year.pk]] == ["Bangsi", "Bíll"]
    assert feeds[last_year.pk] == []


def test_cannot_follow_from_own_household(client, laugavegur):
    client.force_login(laugavegur["joi"].user)
    page = client.get(reverse("wishlists:public", args=[laugavegur["share"].token])).text
    assert "á þínum lista á jolahjol.is" not in page
    with pytest.raises(services.WishlistError):
        services.follow(laugavegur["share"], laugavegur["home"], name="Sigga")


def test_public_page_states(client, laugavegur, disa):
    url = reverse("wishlists:public", args=[laugavegur["share"].token])
    anonymous = Client().get(url).text
    assert "Minnkaðu jólastressið!" in anonymous and "allar hugmyndir sem Jói bætir við" in anonymous
    assert reverse("wishlists:follow_start", args=[laugavegur["share"].token]) in anonymous
    client.force_login(UserFactory())
    assert "Gefðu listanum þínum nafn" in client.get(url).text
    client.force_login(disa.user)
    services.follow(laugavegur["share"], disa.household, name="Sigga")
    page = client.get(url).text
    assert "á listanum „Heima hjá Dísu“" in page
    assert "Minnkaðu jólastressið!" in page and "Opna minn lista" in page  # hausinn líka innskráð


def test_create_household_returns_to_wishlist(client, laugavegur):
    client.force_login(UserFactory(name=""))
    back = reverse("wishlists:public", args=[laugavegur["share"].token])
    response = client.post(reverse("households:create"), {"name": "Mitt", "your_name": "Gunna", "next": back})
    assert response.url == back
    response = client.post(
        reverse("households:create"), {"name": "Annað", "your_name": "Gunna", "next": "https://illt.is/"}
    )
    assert "illt.is" not in response.url


def test_unfollow_keeps_taken_ideas(client, laugavegur, disa):
    mine = services.follow(laugavegur["share"], disa.household, name="Sigga")
    my_gift = Gift.objects.get(person=mine)
    services.claim(my_gift, laugavegur["gift"].ideas.get(text="Bíll").pk, "Dísa")
    client.force_login(disa.user)
    dialog = client.get(reverse("gifts:person", args=[disa.household.slug, mine.pk]), **HX).text
    assert "Hætta að fylgja" in dialog
    client.post(reverse("wishlists:unfollow", args=[disa.household.slug, mine.pk]), **HX)
    mine.refresh_from_db()
    assert mine.source is None
    assert texts(disa, "Sigga") == (["Bíll"], [])


def test_feed_is_not_counted_in_totals(laugavegur, disa):
    mine = services.follow(laugavegur["share"], disa.household, name="Sigga")
    season = disa.household.seasons.get(year=YEAR)
    gl = listing.build_list(season, listing.ListState())
    assert gl.summary.spent == 0 and gl.summary.total_plan == 0
    assert Idea.objects.filter(gift__person=mine).count() == 0


def test_best_name_matches_first_in_dropdown(client, laugavegur, disa):
    season = disa.household.seasons.get(year=YEAR)
    for name in ["Anna", "Inga", "Siggi", "Sigga litla", "Sigga", "Jói"]:
        GiftFactory(season=season, person=PersonFactory(household=disa.household, name=name))
    client.force_login(disa.user)
    response = client.get(popup_url(disa, laugavegur["share"]))
    people = response.context["follow_popup"]["follow"]["households"][0][1]
    assert [p.name for p in people] == ["Sigga", "Sigga litla", "Siggi", "Anna", "Inga", "Jói"]


def test_signup_from_wishlist_opens_the_popup_on_my_list(client, laugavegur):
    """Ný manneskja: „Bæta á minn lista“ → kóði → stofna lista → listinn opnast með valglugganum."""
    share, sigga = laugavegur["share"], laugavegur["sigga"]
    start = reverse("wishlists:follow_start", args=[share.token])
    response = client.get(start)
    assert response.url.startswith(reverse("account_request_login_code")) and "fylgja" in response.url

    client.force_login(UserFactory(name=""))
    response = client.get(start)
    assert response.url.startswith(reverse("households:create"))
    response = client.post(response.url, {"name": "Heima hjá Dísu", "your_name": "Dísa"})
    assert response.url == start
    response = client.get(start, follow=True)
    assert response.redirect_chain[-1][0].endswith(f"/{YEAR}/?fylgja={share.token}")
    page = response.text
    assert "data-autoopen" in page and "Bæta á minn lista – Sigga" in page
    assert not Person.objects.filter(source=sigga).exists()  # ekkert gerist fyrr en valið er

    home = Membership.objects.get(user=response.wsgi_request.user).household
    client.post(follow_url(share), {"household": home.slug, "person": "", "name": "Sigga", "group": "born"})
    mine = Person.objects.get(source=sigga)
    assert mine.household == home and Gift.objects.filter(person=mine, season__year=YEAR).exists()
    # Aftur á hnappinn: þegar á listanum, enginn gluggi
    response = client.get(start)
    assert response.url == reverse("gifts:list", args=[home.slug])


def test_popup_only_with_valid_link_and_not_for_own_list(client, laugavegur, disa):
    share = laugavegur["share"]
    start = reverse("wishlists:follow_start", args=[share.token])
    client.force_login(disa.user)
    assert (
        client.get(start).url == reverse("gifts:list", args=[disa.household.slug]) + f"?fylgja={share.token}"
    )
    assert "data-autoopen" in client.get(popup_url(disa, share)).text
    assert "data-autoopen" not in client.get(popup_url(disa, share) + "x").text
    # Jói: hans eigin listi, enginn gluggi
    client.force_login(laugavegur["joi"].user)
    assert client.get(start).url == reverse("wishlists:public", args=[share.token])
    joi_list = reverse("gifts:season", args=[laugavegur["home"].slug, YEAR]) + f"?fylgja={share.token}"
    assert "data-autoopen" not in client.get(joi_list).text
    # Lokaður hlekkur
    services.revoke(laugavegur["sigga"])
    assert client.get(start).status_code == 404
    client.force_login(disa.user)
    assert "data-autoopen" not in client.get(popup_url(disa, share)).text


def test_feed_shows_the_ideas_store_not_the_household(client, laugavegur, disa):
    bill = laugavegur["gift"].ideas.get(text="Bíll")
    bill.store = StoreFactory(household=laugavegur["home"], name="Elko")
    bill.save()
    services.follow(laugavegur["share"], disa.household, name="Sigga")
    client.force_login(disa.user)
    page = client.get(reverse("gifts:season", args=[disa.household.slug, YEAR])).text
    assert '<span class="stores none">Elko</span>' in page
    assert '<span class="stores none">Laugavegur 4</span>' not in page


# ---------- Úr yfirferð ----------


def test_no_email_is_shown_when_users_have_no_name(client, laugavegur, disa):
    joi = laugavegur["joi"].user
    joi.name = ""
    joi.save()
    page = Client().get(reverse("wishlists:public", args=[laugavegur["share"].token])).text
    assert joi.email not in page
    assert "allar hugmyndir sem Laugavegur 4 bætir við" in page  # nafn heimilisins í staðinn
    # Dísa án nafns tekur hugmynd: hvorki netfang né hluti þess verður gefandi hjá Jóa
    disa.user.name = ""
    disa.user.save()
    mine = services.follow(laugavegur["share"], disa.household, name="Sigga")
    url = reverse("gifts:feed_idea", args=[disa.household.slug, Gift.objects.get(person=mine).pk, 0])
    bill = laugavegur["gift"].ideas.get(text="Bíll")
    client.force_login(disa.user)
    client.post(url.replace("/0/", f"/{bill.pk}/"), {"action": "fratekid"}, **HX)
    bill.refresh_from_db()
    assert bill.reserved_by.name == "Heima hjá Dísu"
    assert disa.user.email.split("@")[0] not in Person.objects.values_list("name", flat=True)
    # „Á lista hjá“ hjá Jóa: nafn heimilisins, ekki netfang
    client.force_login(joi)
    dialog = client.get(reverse("gifts:person", args=[laugavegur["home"].slug, laugavegur["sigga"].pk]), **HX)
    assert "Á lista hjá: Heima hjá Dísu" in dialog.text and disa.user.email not in dialog.text


def test_existing_giver_survives_release(laugavegur, disa):
    """Dísa var þegar í púkki á Bíl hjá Jóa: tekur hann og hættir við, en púkkið helst."""
    bill = laugavegur["gift"].ideas.get(text="Bíll")
    IdeaGiver.objects.create(idea=bill, person=PersonFactory(household=laugavegur["home"], name="Dísa"))
    mine = services.follow(laugavegur["share"], disa.household, name="Sigga")
    copy = services.claim(Gift.objects.get(person=mine), bill.pk, "Dísa")
    assert not copy.source_added_giver
    gift_services.remove_idea(copy)
    bill.refresh_from_db()
    assert not bill.reserved and IdeaGiver.objects.filter(idea=bill, person__name="Dísa").exists()


def test_claim_name_never_lands_on_the_family_or_recipient(laugavegur, disa):
    """Dísa heitir líka Sigga: frátekningin má ekki lenda á Siggu sjálfri hjá Jóa."""
    mine = services.follow(laugavegur["share"], disa.household, name="Sigga")
    bill = laugavegur["gift"].ideas.get(text="Bíll")
    services.claim(Gift.objects.get(person=mine), bill.pk, "Sigga")
    bill.refresh_from_db()
    assert bill.reserved_by != laugavegur["sigga"]
    assert bill.reserved_by.name == "Sigga (Heima hjá Dísu)"


def test_unreserving_a_bought_copy_keeps_the_link(laugavegur, disa):
    mine = services.follow(laugavegur["share"], disa.household, name="Sigga")
    bill = laugavegur["gift"].ideas.get(text="Bíll")
    copy = services.claim(Gift.objects.get(person=mine), bill.pk, "Dísa")
    gift_services.pick_idea(copy)
    gift_services.set_reserved(copy, False)
    gift_services.unpick_idea(copy)
    gift_services.remove_idea(copy)
    bill.refresh_from_db()
    assert not bill.reserved  # losnaði þrátt fyrir að frátekningin væri afhökuð á afritinu


def test_deleting_household_or_season_releases_claims(laugavegur, disa):
    from apps.gifts.services.seasons import delete_season
    from apps.households.services import delete_household

    mine = services.follow(laugavegur["share"], disa.household, name="Sigga")
    gift = Gift.objects.get(person=mine)
    for text in ("Bíll", "Bangsi"):
        services.claim(gift, laugavegur["gift"].ideas.get(text=text).pk, "Dísa")
    delete_season(gift.season)
    assert not laugavegur["gift"].ideas.filter(reserved=True).exists()

    gift = gift_services.ensure_christmas_gift(mine, YEAR)  # árið aftur, sama einstaklingur
    services.claim(gift, laugavegur["gift"].ideas.get(text="Bíll").pk, "Dísa")
    delete_household(disa.household)
    assert not laugavegur["gift"].ideas.filter(reserved=True).exists()


def test_merging_keeps_followers_and_the_link(laugavegur, disa):
    from apps.gifts.services.people import merge

    mine = services.follow(laugavegur["share"], disa.household, name="Sigga")
    other = PersonFactory(household=laugavegur["home"], name="Sigga litla")
    merge(laugavegur["sigga"], other)
    mine.refresh_from_db()
    assert mine.source == other and services.active_share(other) is not None
    # Sá sem fylgdi og er sameinaður öðrum: fylgnin flyst
    target = PersonFactory(household=disa.household, name="Sigga Jóns")
    merge(mine, target)
    target.refresh_from_db()
    assert target.source == other


def test_a_wishlist_follows_only_one_person_per_household(laugavegur, disa):
    services.follow(laugavegur["share"], disa.household, name="Sigga")
    with pytest.raises(services.WishlistError, match="fylgir nú þegar"):
        services.follow(laugavegur["share"], disa.household, name="Sigga Jónsdóttir")
    assert Person.objects.filter(household=disa.household, source=laugavegur["sigga"]).count() == 1


def test_list_feed_queries_do_not_grow_with_followers(laugavegur, disa):
    season = disa.household.seasons.get(year=YEAR)
    services.follow(laugavegur["share"], disa.household, name="Sigga")
    with CaptureQueriesContext(connection) as one:
        listing.build_list(season, listing.ListState())
    for i in range(4):
        home = HouseholdFactory(name=f"Heimili {i}")
        s = SeasonFactory(household=home, year=YEAR)
        kid = PersonFactory(household=home, name=f"Barn {i}")
        IdeaFactory(gift=GiftFactory(season=s, person=kid), text=f"Hugmynd {i}")
        share = services.create_share(kid, laugavegur["joi"].user)
        services.follow(share, disa.household, name=f"Barn {i}")
    with CaptureQueriesContext(connection) as five:
        gl = listing.build_list(season, listing.ListState())
    feeds = [r.feed for s in gl.sections for r in s.rows if r.feed]
    assert len(feeds) == 5
    assert len(five) - len(one) < 4 * 3  # ekki ~5 fyrirspurnir fyrir hvern sem fylgir
