"""Áfangi 5: óskalistar (opinn hlekkur og frátekning án innskráningar)."""

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.gifts.models import IdeaGiver, Person
from apps.households.models import Membership
from apps.wishlists import services
from apps.wishlists.models import WishlistShare
from tests.factories import (
    GiftFactory,
    IdeaFactory,
    MembershipFactory,
    PersonFactory,
    SeasonFactory,
    StoreFactory,
    giver,
)

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def member():
    return MembershipFactory(role=Membership.Role.OWNER, household__name="Fjölskyldan á Þórsgötu")


@pytest.fixture
def home(member):
    return member.household


@pytest.fixture
def hugi(home):
    """Hugi á gjöf í ár með þremur hugmyndum; Una á aðra gjöf sem má ekki sjást."""
    season = SeasonFactory(household=home, year=YEAR)
    hugi = PersonFactory(household=home, name="Hugi", group="born")
    gift = GiftFactory(season=season, person=hugi)
    IdeaFactory(
        gift=gift,
        text="legó",
        price=8990,
        store=StoreFactory(household=home, name="Elko"),
        position=0,
        link="https://elko.is/lego",
    )
    keypt = IdeaFactory(gift=gift, text="bók", picked=True, position=1)
    giver(keypt, PersonFactory(household=home, name="Leynigefandi"))
    IdeaFactory(gift=gift, text="spil", note="Bezzerwizzer", position=2)
    una = PersonFactory(household=home, name="Una")
    IdeaFactory(gift=GiftFactory(season=season, person=una), text="leyndó-hugmynd-Unu")
    return hugi


@pytest.fixture
def share(hugi, member):
    return services.create_share(hugi, member.user)


def public(token):
    return reverse("wishlists:public", args=[token])


def idea(text):
    from apps.gifts.models import Idea

    return Idea.objects.get(text=text)


# ---------- Hlekkur (heimilið) ----------


def test_member_creates_replaces_and_revokes_link(client, member, hugi):
    client.force_login(member.user)
    url = reverse("wishlists:share_create", args=[hugi.household.slug, hugi.pk])
    first = client.post(url, **HX)
    token = services.active_share(hugi).token
    assert public(token) in first.text

    client.post(url, **HX)  # nýr hlekkur: sá gamli hættir að virka
    assert services.active_share(hugi).token != token
    assert Client().get(public(token)).status_code == 404

    revoke = client.post(reverse("wishlists:share_revoke", args=[hugi.household.slug, hugi.pk]), **HX)
    assert services.active_share(hugi) is None
    assert "Búa til hlekk" in revoke.text


def test_person_dialog_shows_share_section(client, member, hugi):
    client.force_login(member.user)
    html = client.get(reverse("gifts:person", args=[hugi.household.slug, hugi.pk]), **HX).text
    assert 'id="wishlist-share"' in html and "Búa til hlekk" in html


# ---------- Opna síðan ----------


def test_public_page_shows_only_this_persons_ideas_and_leaks_nothing(share):
    response = Client().get(public(share.token))
    html = response.text
    assert response.status_code == 200
    assert "<h1>Hugi</h1>" in html and "Óskalisti" in html
    assert "legó" in html and "Elko" in html and "8.990 kr." in html and "Bezzerwizzer" in html
    assert "Frátekið" in html  # bók er keypt
    for secret in ("leyndó-hugmynd-Unu", "Una", "Leynigefandi", "Fjölskyldan á Þórsgötu"):
        assert secret not in html, secret
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Referrer-Policy"] == "same-origin"  # leynihlekkurinn lekur ekki til annarra síðna
    assert 'rel="noopener noreferrer"' in html
    assert "no-store" in response["Cache-Control"]


def test_revoked_or_unknown_link_is_gone(share, hugi):
    services.revoke(hugi)
    response = Client().get(public(share.token))
    assert response.status_code == 404 and "virkar ekki lengur" in response.text
    assert Client().get(public("ekki-til")).status_code == 404


# ---------- Frátekning ----------


def reserve(client, share, text, name="Amma Jóa"):
    url = reverse("wishlists:reserve", args=[share.token, idea(text).pk])
    return client.post(url, {"name": name}, follow=True)


def test_reserving_adds_giver_and_hides_who_from_others(share, home):
    grandma = Client()
    page = reserve(grandma, share, "legó").text
    assert "Þú tókst þetta frá" in page
    legó = idea("legó")
    amma = Person.objects.get(household=home, name="Amma Jóa")
    assert legó.reserved_by == amma
    assert IdeaGiver.objects.filter(idea=legó, person=amma).exists()

    other = Client().get(public(share.token)).text
    assert "Amma Jóa" not in other
    assert other.count("Frátekið") >= 2  # legó og bók


def test_reserving_matches_existing_person_by_name(share, home):
    afi = PersonFactory(household=home, name="Afi Bragi")
    reserve(Client(), share, "spil", name="  afi bragi ")
    assert idea("spil").reserved_by == afi
    assert Person.objects.filter(household=home, key="afi bragi").count() == 1


def test_cannot_reserve_taken_or_without_name(share):
    reserve(Client(), share, "legó")
    page = reserve(Client(), share, "legó", name="Einhver annar").text
    assert "var á undan þér" in page
    assert "var á undan þér" in reserve(Client(), share, "bók").text  # keypt
    assert "Skrifaðu nafnið þitt" in reserve(Client(), share, "spil", name="   ").text
    assert idea("spil").reserved_by is None


def test_cannot_reserve_idea_of_another_person(share):
    url = reverse("wishlists:reserve", args=[share.token, idea("leyndó-hugmynd-Unu").pk])
    page = Client().post(url, {"name": "Amma"}, follow=True).text
    assert "ekki á listanum" in page
    assert idea("leyndó-hugmynd-Unu").reserved_by is None


def test_same_device_can_cancel_others_cannot(share, home):
    grandma = Client()
    reserve(grandma, share, "legó")
    cancel_url = reverse("wishlists:cancel", args=[share.token, idea("legó").pk])

    assert "tókst þetta ekki frá" in Client().post(cancel_url, follow=True).text
    assert idea("legó").reserved_by is not None

    page = grandma.post(cancel_url, follow=True).text
    assert "felld niður" in page
    legó = idea("legó")
    assert legó.reserved_by is None and legó.reservation_secret == ""
    assert not IdeaGiver.objects.filter(idea=legó).exists()  # gefandi sem varð til við frátekningu fer


def test_cancel_keeps_giver_who_was_there_before(share, home):
    amma = PersonFactory(household=home, name="Amma Jóa")
    giver(idea("spil"), amma)
    grandma = Client()
    reserve(grandma, share, "spil")
    grandma.post(reverse("wishlists:cancel", args=[share.token, idea("spil").pk]))
    assert IdeaGiver.objects.filter(idea=idea("spil"), person=amma).exists()


def test_old_cookie_does_not_claim_a_new_reservation(share, client, member):
    grandma = Client()
    reserve(grandma, share, "legó")
    services.clear_reservation(idea("legó"))  # heimilið fjarlægir
    reserve(Client(), share, "legó", name="Frændi")
    assert "Þú tókst þetta frá" not in grandma.get(public(share.token)).text


def test_reservations_are_rate_limited(share):
    c = Client()
    url = reverse("wishlists:reserve", args=[share.token, idea("spil").pk])
    for _ in range(30):
        c.post(url, {"name": ""})
    assert "Of margar beiðnir" in c.post(url, {"name": "Amma"}, follow=True).text
    assert idea("spil").reserved_by is None


# ---------- Heimilið sér frátekningu ----------


def test_household_sees_and_removes_reservation(client, member, share):
    reserve(Client(), share, "legó")
    client.force_login(member.user)
    slug = member.household.slug
    row = client.get(reverse("gifts:season", args=[slug, YEAR])).text
    assert "frátekið af Amma Jóa" in row and "idea-line reserved" in row  # appelsínugul, án gátreits
    dialog = client.get(reverse("gifts:idea", args=[slug, idea("legó").pk]), **HX).text
    assert "Frátekið af Amma Jóa" in dialog
    client.post(reverse("gifts:reservation_remove", args=[slug, idea("legó").pk]), **HX)
    assert idea("legó").reserved_by is None and not idea("legó").reserved
    assert WishlistShare.objects.count() == 1


def test_household_marks_reserved_by_hand(client, member, share):
    """Amma segir í síma „ég kaupi það“: heimilið hakar „Frátekið“; af óskalista verður það tekið."""
    client.force_login(member.user)
    slug = member.household.slug
    lego = idea("legó")
    data = {
        "text": "legó",
        "price": "",
        "link": "",
        "note": "",
        "store": "",
        "locations": "",
        "reserved": "on",
    }
    client.post(reverse("gifts:idea", args=[slug, lego.pk]), data, **HX)
    lego.refresh_from_db()
    assert lego.reserved and lego.reserved_by is None and not lego.picked
    assert "Frátekið" in Client().get(reverse("wishlists:public", args=[share.token])).text
    assert "legó" not in client.get(reverse("gifts:shop", args=[slug, YEAR])).text  # ekki á innkaupalista
    # Keypt: verður rautt
    client.post(reverse("gifts:idea", args=[slug, lego.pk]), {**data, "picked": "on"}, **HX)
    lego.refresh_from_db()
    assert lego.picked and "idea-line picked" in client.get(reverse("gifts:season", args=[slug, YEAR])).text
    # Afhakað: frátekningin fellur niður
    data.pop("reserved")
    client.post(reverse("gifts:idea", args=[slug, lego.pk]), data, **HX)
    lego.refresh_from_db()
    assert not lego.reserved
