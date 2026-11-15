"""Flokkur heimilisins, óskalisti heimilis og að fylgja heimili í heild.

Dæmið: Dísa á heimilið „Laugavegur 5“ með Jóa, Sigga og Stínu í flokki heimilisins. Hún sendir
ömmu Röggu hlekk á óskalista heimilisins. Amma bætir heimilinu á sinn lista og þar verður til
flokkurinn „Laugavegur 5“ með þeim öllum.
"""

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.gifts import listing
from apps.gifts.models import Family, Gift, Person
from apps.gifts.services import groups
from apps.gifts.services.privacy import Viewer
from apps.households.models import Membership
from apps.wishlists import services
from apps.wishlists.services import WishlistError
from tests.factories import (
    GiftFactory,
    HouseholdFactory,
    IdeaFactory,
    MembershipFactory,
    PersonFactory,
    SeasonFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def laugavegur():
    """Dísa (notandi), Jói, Siggi og Stína í flokki heimilisins; Gunna frænka í Fjölskyldu."""
    home = HouseholdFactory(name="Laugavegur 5")
    season = SeasonFactory(household=home, year=YEAR)
    people = {}
    for name in ("Dísa", "Jói", "Siggi", "Stína"):
        people[name] = PersonFactory(household=home, name=name, group="heimili")
        GiftFactory(season=season, person=people[name])
    disa = MembershipFactory(
        household=home, role=Membership.Role.OWNER, user=UserFactory(name="Dísa"), person=people["Dísa"]
    )
    gunna = PersonFactory(household=home, name="Gunna", group="fjolskylda")
    GiftFactory(season=season, person=gunna)

    def gift(name):
        return Gift.objects.get(person=people.get(name) or gunna, season=season)

    IdeaFactory(gift=gift("Siggi"), text="Lego", position=0)
    IdeaFactory(gift=gift("Siggi"), text="Bolti", position=1)
    IdeaFactory(gift=gift("Stína"), text="Hárskraut")
    IdeaFactory(gift=gift("Dísa"), text="Trefill", wish=True)  # hún skráði hana sjálf
    IdeaFactory(gift=gift("Dísa"), text="Leynihálsmen")  # Jói ætlar að gefa henni
    IdeaFactory(gift=gift("Gunna"), text="Kerti")
    share = services.create_household_share(home, disa.user)
    return {"home": home, "season": season, "disa": disa, "people": people, "gift": gift, "share": share}


@pytest.fixture
def ragga():
    """Amma Ragga og hennar eigið Jólahjól."""
    home = HouseholdFactory(name="Hjá ömmu")
    member = MembershipFactory(household=home, role=Membership.Role.OWNER, user=UserFactory(name="Ragga"))
    SeasonFactory(household=home, year=YEAR)
    return member


@pytest.fixture
def disa_aunt():
    """Gunna frænka, sem fylgir Sigga ein og sér (eigin hlekkur hans)."""
    home = HouseholdFactory(name="Hjá frænku")
    member = MembershipFactory(household=home, role=Membership.Role.OWNER, user=UserFactory(name="Gunna"))
    SeasonFactory(household=home, year=YEAR)
    return member


def page_url(share):
    return reverse("wishlists:household", args=[share.token])


def rows(member):
    """{nafn: (flokkur, eigin hugmyndir, af óskalista)} á lista `member`."""
    season = member.household.seasons.get(year=YEAR)
    out = {}
    for section in listing.build_list(season, listing.ListState()).sections:
        for r in section.rows:
            out[r.person.name] = (
                section.label,
                [i.text for i in r.gift.ideas.all()],
                [i.text for i in r.feed],
            )
    return out


# ---------- Flokkur heimilisins ----------


def test_household_group_is_first_and_named_after_the_household(laugavegur):
    gl = listing.build_list(laugavegur["season"], listing.ListState())
    first = gl.sections[0]
    assert first.group == "heimili" and first.label == "Laugavegur 5" and first.home
    assert sorted(r.person.name for r in first.rows) == ["Dísa", "Jói", "Siggi", "Stína"]
    assert gl.section("fjolskylda").rows[0].person.name == "Gunna"


def test_own_row_is_on_top_of_the_household_group_and_not_counted(laugavegur):
    viewer = Viewer(laugavegur["people"]["Dísa"].pk)
    first = listing.build_list(laugavegur["season"], listing.ListState(), viewer=viewer).sections[0]
    assert first.rows[0].secret and first.rows[0].person.name == "Dísa"
    assert first.count == 3  # hennar eigin gjöf telst ekki með


def test_empty_groups_are_shown_so_people_can_be_added():
    season = SeasonFactory(household=HouseholdFactory(name="Tómt"), year=YEAR)
    gl = listing.build_list(season, listing.ListState(), locked=False)
    assert [s.group for s in gl.sections] == ["heimili", "born", "fjolskylda", "vinir", "vinna"]
    assert gl.sections[0].label == "Tómt"
    assert not any(groups.GroupInfo(v, "", "").is_family for v in ("fjolskylda", "heimili", "f"))
    assert groups.GroupInfo("f12", "", "").is_family


def test_list_page_shows_household_name_and_share_button(laugavegur):
    client = Client()
    client.force_login(laugavegur["disa"].user)
    home = laugavegur["home"]
    html = client.get(reverse("gifts:season", args=[home.slug, YEAR])).text
    assert 'id="group-heimili"' in html and "<h2>Laugavegur 5</h2>" in html
    assert reverse("wishlists:household_share", args=[home.slug]) in html


def test_group_choices_and_assign(laugavegur, ragga):
    home = laugavegur["home"]
    assert groups.choices(home)[0] == ("heimili", "Laugavegur 5")
    gunna = Person.objects.get(name="Gunna")
    assert groups.assign(gunna, "heimili") and gunna.group == "heimili"
    assert not groups.assign(gunna, "rugl") and gunna.group == "heimili"

    family = services.follow_household(laugavegur["share"], ragga.household)
    value = groups.family_value(family.pk)
    assert (value, "Laugavegur 5") in groups.choices(ragga.household)
    assert not groups.is_valid(home, value)  # flokkur annars heimilis
    lulli = PersonFactory(household=ragga.household, name="Lúlli", group="vinir")
    assert groups.assign(lulli, value) and lulli.family == family and lulli.group == "vinir"
    assert groups.assign(lulli, "born") and lulli.family is None and lulli.group == "born"


def test_people_page_and_group_select(laugavegur):
    client = Client()
    client.force_login(laugavegur["disa"].user)
    home = laugavegur["home"]
    html = client.get(reverse("gifts:people", args=[home.slug, YEAR])).text
    assert "<h2>Laugavegur 5</h2>" in html
    gunna = Person.objects.get(name="Gunna")
    client.post(reverse("gifts:person_group", args=[home.slug, gunna.pk]), {"group": "heimili"}, **HX)
    gunna.refresh_from_db()
    assert gunna.group == "heimili"


def test_person_dialog_offers_household_group(laugavegur):
    client = Client()
    client.force_login(laugavegur["disa"].user)
    home, gunna = laugavegur["home"], Person.objects.get(name="Gunna")
    html = client.get(reverse("gifts:person", args=[home.slug, gunna.pk]), **HX).text
    assert '<option value="heimili">Laugavegur 5</option>' in html


# ---------- Óskalisti heimilisins ----------


def test_public_page_shows_everyone_in_the_household_group(laugavegur):
    html = Client().get(page_url(laugavegur["share"])).text
    assert "<h1>Laugavegur 5</h1>" in html
    for text in ("Siggi", "Lego", "Bolti", "Stína", "Hárskraut", "Jói", "Trefill"):
        assert text in html, text
    assert "Kerti" not in html  # Gunna er ekki í flokki heimilisins
    assert "Leynihálsmen" not in html  # Dísa er notandi: aðeins hennar eigin óskir


def test_revoked_or_unknown_link_is_gone(laugavegur):
    services.revoke_household_share(laugavegur["home"])
    assert Client().get(page_url(laugavegur["share"])).status_code == 404
    assert Client().get(reverse("wishlists:household", args=["rugl"])).status_code == 404


def test_reserve_and_cancel_from_the_household_page(laugavegur):
    client = Client()
    share = laugavegur["share"]
    lego = laugavegur["gift"]("Siggi").ideas.get(text="Lego")
    url = reverse("wishlists:household_reserve", args=[share.token, lego.pk])
    response = client.post(url, {"name": "Amma Ragga"})
    assert response.url == page_url(share) + f"#idea-{lego.pk}"  # aftur á sömu línu
    lego.refresh_from_db()
    assert lego.reserved and lego.reserved_by.name == "Amma Ragga"
    html = client.get(page_url(share)).text
    assert "Þú tókst þetta frá" in html
    assert "Lego" not in Client().get(page_url(share)).text  # aðrir sjá það ekki

    client.post(reverse("wishlists:household_cancel", args=[share.token, lego.pk]))
    lego.refresh_from_db()
    assert not lego.reserved


def test_cannot_reserve_outside_the_household_group(laugavegur):
    kerti = laugavegur["gift"]("Gunna").ideas.get(text="Kerti")
    leyni = laugavegur["gift"]("Dísa").ideas.get(text="Leynihálsmen")
    for idea in (kerti, leyni):
        with pytest.raises(WishlistError):
            services.reserve(laugavegur["share"], idea.pk, "Ragga")
        idea.refresh_from_db()
        assert not idea.reserved


def test_share_dialog_create_and_revoke(laugavegur):
    client = Client()
    client.force_login(laugavegur["disa"].user)
    home = laugavegur["home"]
    html = client.get(reverse("wishlists:household_share", args=[home.slug]), **HX).text
    assert "Dísa, Jói, Siggi, Stína" in html and laugavegur["share"].token in html

    client.post(reverse("wishlists:household_share_revoke", args=[home.slug]), **HX)
    assert services.active_household_share(home) is None
    html = client.post(reverse("wishlists:household_share_create", args=[home.slug]), **HX).text
    new = services.active_household_share(home)
    assert new.token != laugavegur["share"].token and new.token in html


def test_share_dialog_is_for_members_only(laugavegur, ragga):
    client = Client()
    client.force_login(ragga.user)
    url = reverse("wishlists:household_share", args=[laugavegur["home"].slug])
    assert client.get(url, **HX).status_code == 404
    client.post(reverse("wishlists:household_share_create", args=[laugavegur["home"].slug]), **HX)
    assert services.active_household_share(laugavegur["home"]) == laugavegur["share"]


# ---------- Amma Ragga bætir heimilinu á sinn lista ----------


def test_the_whole_story(laugavegur, ragga):
    client = Client()
    client.force_login(ragga.user)
    share = laugavegur["share"]
    page = client.get(page_url(share)).text
    assert "Á Laugavegur 5 að vera á þínum lista á jolahjol.is?" in page

    response = client.post(
        reverse("wishlists:household_follow", args=[share.token]), {"household": ragga.household.slug}
    )
    assert response.url == reverse("gifts:list", args=[ragga.household.slug])
    family = Family.objects.get(household=ragga.household)
    assert family.source == laugavegur["home"] and family.name == "Laugavegur 5"

    # Nýr flokkur „Laugavegur 5“ hjá ömmu, beint á eftir hennar eigin heimili
    seen = rows(ragga)
    assert {name: g for name, (g, _o, _f) in seen.items()} == {
        n: "Laugavegur 5" for n in ("Dísa", "Jói", "Siggi", "Stína")
    }
    assert seen["Siggi"][2] == ["Lego", "Bolti"]
    assert seen["Dísa"][2] == ["Trefill"]
    season = ragga.household.seasons.get(year=YEAR)
    labels = [s.label for s in listing.build_list(season, listing.ListState()).sections]
    assert labels[:2] == ["Hjá ömmu", "Laugavegur 5"]

    # Síðan veit að amma fylgir
    assert "Á listanum „Hjá ömmu“" in client.get(page_url(share)).text
    # Og Dísa sér hver fylgir
    disa = Client()
    disa.force_login(laugavegur["disa"].user)
    html = disa.get(reverse("wishlists:household_share", args=[laugavegur["home"].slug]), **HX).text
    assert "Á lista hjá: Ragga" in html


def test_feed_needs_an_active_household_link(laugavegur, ragga):
    services.follow_household(laugavegur["share"], ragga.household)
    services.revoke_household_share(laugavegur["home"])
    assert rows(ragga)["Siggi"][2] == []
    # Eigin hlekkur Sigga dugar líka
    services.create_share(laugavegur["people"]["Siggi"], laugavegur["disa"].user)
    assert rows(ragga)["Siggi"][2] == ["Lego", "Bolti"]
    assert rows(ragga)["Stína"][2] == []


def test_existing_person_with_same_name_is_linked(laugavegur, ragga):
    season = ragga.household.seasons.get(year=YEAR)
    siggi = PersonFactory(household=ragga.household, name="Siggi", group="born")
    GiftFactory(season=season, person=siggi)
    services.follow_household(laugavegur["share"], ragga.household)
    siggi.refresh_from_db()
    assert siggi.source == laugavegur["people"]["Siggi"] and siggi.family is not None
    assert Person.objects.filter(household=ragga.household, key="siggi").count() == 1


def test_own_household_people_with_same_name_are_not_linked(laugavegur, ragga):
    # Jói hjá ömmu er hennar eigið heimilisfólk, ekki Jói á Laugavegi
    joi = PersonFactory(household=ragga.household, name="Jói", group="heimili")
    services.follow_household(laugavegur["share"], ragga.household)
    joi.refresh_from_db()
    assert joi.source is None and joi.family is None
    other = Person.objects.get(household=ragga.household, name="Jói (Laugavegur 5)")
    assert other.source == laugavegur["people"]["Jói"]


def test_someone_already_followed_joins_the_group(laugavegur, ragga):
    siggi = laugavegur["people"]["Siggi"]
    single = services.create_share(siggi, laugavegur["disa"].user)
    mine = services.follow(single, ragga.household, name="Siggi litli", group="born")
    services.follow_household(laugavegur["share"], ragga.household)
    mine.refresh_from_db()
    assert mine.family is not None and mine.name == "Siggi litli"
    assert Person.objects.filter(household=ragga.household, source=siggi).count() == 1


def test_new_household_member_appears_when_the_list_is_opened(laugavegur, ragga):
    services.follow_household(laugavegur["share"], ragga.household)
    baby = PersonFactory(household=laugavegur["home"], name="Lilla", group="heimili")
    GiftFactory(season=laugavegur["season"], person=baby)
    client = Client()
    client.force_login(ragga.user)
    client.get(reverse("gifts:season", args=[ragga.household.slug, YEAR]))
    lilla = Person.objects.get(household=ragga.household, name="Lilla")
    assert lilla.source == baby and lilla.family.source == laugavegur["home"]
    assert Gift.objects.filter(person=lilla, season__year=YEAR).exists()


def test_unfollowed_person_is_not_added_again(laugavegur, ragga):
    services.follow_household(laugavegur["share"], ragga.household)
    stina = Person.objects.get(household=ragga.household, name="Stína")
    services.unfollow(stina)
    services.sync_families(ragga.household)
    stina.refresh_from_db()
    assert stina.source is None and stina.family is None
    assert Person.objects.filter(household=ragga.household, name__startswith="Stína").count() == 1


def test_unfollow_family(laugavegur, ragga):
    family = services.follow_household(laugavegur["share"], ragga.household)
    client = Client()
    client.force_login(ragga.user)
    response = client.post(reverse("wishlists:unfollow_family", args=[ragga.household.slug, family.pk]), **HX)
    assert response.status_code == 200
    assert not Family.objects.exists()
    siggi = Person.objects.get(household=ragga.household, name="Siggi")
    assert siggi.source is None and siggi.family is None and siggi.group == "fjolskylda"
    assert rows(ragga)["Siggi"][0] == "Fjölskylda"


def test_unfollow_family_only_by_its_household(laugavegur, ragga):
    family = services.follow_household(laugavegur["share"], ragga.household)
    client = Client()
    client.force_login(laugavegur["disa"].user)
    url = reverse("wishlists:unfollow_family", args=[laugavegur["home"].slug, family.pk])
    assert client.post(url, **HX).status_code == 404
    assert Family.objects.filter(pk=family.pk).exists()


def test_cannot_follow_own_household(laugavegur):
    with pytest.raises(WishlistError):
        services.follow_household(laugavegur["share"], laugavegur["home"])
    client = Client()
    client.force_login(laugavegur["disa"].user)
    html = client.get(page_url(laugavegur["share"])).text
    assert 'id="follow"' not in html


def test_following_twice_is_harmless(laugavegur, ragga):
    services.follow_household(laugavegur["share"], ragga.household)
    services.follow_household(laugavegur["share"], ragga.household)
    assert Family.objects.count() == 1
    assert Person.objects.filter(household=ragga.household).count() == 4


def test_follow_start_for_anonymous_and_without_a_list(laugavegur):
    share = laugavegur["share"]
    start = reverse("wishlists:household_follow_start", args=[share.token])
    response = Client().get(start)
    assert response.url.startswith(reverse("account_signup")) and "next=" in response.url
    client = Client()
    client.force_login(UserFactory())
    assert client.get(start).url.startswith(reverse("households:create"))


def test_follow_start_with_a_list_goes_to_the_form(laugavegur, ragga):
    client = Client()
    client.force_login(ragga.user)
    start = reverse("wishlists:household_follow_start", args=[laugavegur["share"].token])
    assert client.get(start).url == page_url(laugavegur["share"]) + "#follow"
    html = client.get(page_url(laugavegur["share"])).text
    assert reverse("wishlists:household_follow", args=[laugavegur["share"].token]) in html


def test_person_dialog_offers_to_unfollow_the_family(laugavegur, ragga):
    family = services.follow_household(laugavegur["share"], ragga.household)
    siggi = Person.objects.get(household=ragga.household, name="Siggi")
    client = Client()
    client.force_login(ragga.user)
    html = client.get(reverse("gifts:person", args=[ragga.household.slug, siggi.pk]), **HX).text
    assert reverse("wishlists:unfollow_family", args=[ragga.household.slug, family.pk]) in html
    assert f'<option value="f{family.pk}" selected>Laugavegur 5</option>' in html


def test_both_public_pages_explain_who_sees_a_reservation(laugavegur):
    single = services.create_share(laugavegur["people"]["Siggi"], laugavegur["disa"].user)
    for url in (page_url(laugavegur["share"]), reverse("wishlists:public", args=[single.token])):
        html = Client().get(url).text
        assert "Hver sér að þetta er frátekið?" in html
        assert "Heimilið sem deildi listanum:" in html and "nema sá sem á að fá hana" in html


# ---------- Mörk: hver fylgir hverju (code review) ----------


def test_household_link_does_not_keep_individual_followers(laugavegur, disa_aunt):
    """Loki Dísa eigin hlekk Sigga hættir frænka, sem fylgdi honum ein og sér, að sjá hann,
    þótt hlekkur heimilisins sé opinn."""
    siggi = laugavegur["people"]["Siggi"]
    single = services.create_share(siggi, laugavegur["disa"].user)
    services.follow(single, disa_aunt.household, name="Siggi", group="born")
    assert rows(disa_aunt)["Siggi"][2] == ["Lego", "Bolti"]
    services.revoke(siggi)
    assert rows(disa_aunt)["Siggi"][2] == []


def test_friend_with_same_name_is_not_linked(laugavegur, ragga):
    friend = PersonFactory(household=ragga.household, name="Siggi", group="vinir")
    services.follow_household(laugavegur["share"], ragga.household)
    friend.refresh_from_db()
    assert friend.source is None and friend.family is None and friend.group == "vinir"
    assert Person.objects.get(household=ragga.household, name="Siggi (Laugavegur 5)").family is not None


def test_unfollow_family_keeps_earlier_individual_follow(laugavegur, ragga):
    siggi = laugavegur["people"]["Siggi"]
    single = services.create_share(siggi, laugavegur["disa"].user)
    mine = services.follow(single, ragga.household, name="Siggi", group="born")
    family = services.follow_household(laugavegur["share"], ragga.household)
    mine.refresh_from_db()
    assert mine.family == family and not mine.family_follow
    services.unfollow_family(family)
    mine.refresh_from_db()
    assert mine.source == siggi and mine.family is None
    assert rows(ragga)["Siggi"][2] == ["Lego", "Bolti"]  # eigin hlekkur hans gildir enn
    stina = Person.objects.get(household=ragga.household, name="Stína")
    assert stina.source is None


def test_unfollow_family_also_reaches_people_moved_out_of_the_group(laugavegur, ragga):
    family = services.follow_household(laugavegur["share"], ragga.household)
    stina = Person.objects.get(household=ragga.household, name="Stína")
    groups.assign(stina, "vinir")
    assert rows(ragga)["Stína"][2] == ["Hárskraut"]  # fylgir enn í gegnum heimilið
    services.unfollow_family(family)
    stina.refresh_from_db()
    assert stina.source is None and not stina.family_follow
    assert rows(ragga)["Stína"][2] == []


def test_past_year_page_does_not_sync(laugavegur, ragga):
    services.follow_household(laugavegur["share"], ragga.household)
    baby = PersonFactory(household=laugavegur["home"], name="Lilla", group="heimili")
    GiftFactory(season=laugavegur["season"], person=baby)
    SeasonFactory(household=ragga.household, year=YEAR - 1)
    client = Client()
    client.force_login(ragga.user)
    client.get(reverse("gifts:season", args=[ragga.household.slug, YEAR - 1]))
    assert not Person.objects.filter(household=ragga.household, name="Lilla").exists()
    client.get(reverse("gifts:season", args=[ragga.household.slug, YEAR]))
    assert Person.objects.filter(household=ragga.household, name="Lilla").exists()


def test_follow_rejects_household_group_from_post(laugavegur, ragga):
    single = services.create_share(laugavegur["people"]["Siggi"], laugavegur["disa"].user)
    person = services.follow(single, ragga.household, name="Siggi", group="heimili")
    assert person.group != "heimili"
