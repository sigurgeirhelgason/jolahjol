from datetime import timedelta

import pytest
from django.conf import settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from apps.gifts.models import Person
from apps.households import services
from apps.households.models import Household, Invite, Membership
from tests.factories import (
    GiftFactory,
    HouseholdFactory,
    MembershipFactory,
    SeasonFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

OWNER = Membership.Role.OWNER
MEMBER = Membership.Role.MEMBER


@pytest.fixture
def owner():
    return MembershipFactory(role=OWNER)


@pytest.fixture
def home(owner):
    return owner.household


def _member(home, role=MEMBER):
    return MembershipFactory(household=home, role=role)


# ---------- Þjónustur ----------


def test_create_household_makes_creator_owner_with_icelandic_slug():
    user = UserFactory()
    household = services.create_household(user, "  Heimilið á Þórsgötu ")
    assert household.name == "Heimilið á Þórsgötu"
    assert household.slug == "heimilid-a-thorsgotu"
    assert Membership.objects.get(user=user, household=household).role == OWNER


def test_slug_gets_suffix_when_taken():
    user = UserFactory()
    assert services.create_household(user, "Okkar").slug == "okkar"
    assert services.create_household(user, "Okkar").slug == "okkar-2"
    assert services.create_household(user, "ÆÐÖ").slug == "aedo"
    assert services.create_household(user, "🎄").slug == "heimili"


def test_rename_keeps_slug(home):
    slug = home.slug
    services.rename_household(home, "Nýtt nafn")
    home.refresh_from_db()
    assert (home.name, home.slug) == ("Nýtt nafn", slug)


def test_accept_invite_adds_member_and_is_single_use(home, owner):
    invite = services.create_invite(home, owner.user)
    guest = UserFactory()
    membership = services.accept_invite(invite.token, guest)
    assert (membership.household, membership.role) == (home, MEMBER)
    invite.refresh_from_db()
    assert invite.accepted_by == guest

    with pytest.raises(services.HouseholdError, match="þegar verið notað"):
        services.accept_invite(invite.token, UserFactory())


def test_accept_invite_when_already_member_does_not_use_it_up(home, owner):
    invite = services.create_invite(home, owner.user)
    assert services.accept_invite(invite.token, owner.user) == owner
    invite.refresh_from_db()
    assert invite.accepted_at is None


def test_expired_and_unknown_invites_are_rejected(home, owner):
    invite = services.create_invite(home, owner.user)
    Invite.objects.filter(pk=invite.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(services.HouseholdError, match="útrunnið"):
        services.accept_invite(invite.token, UserFactory())
    with pytest.raises(services.HouseholdError, match="ekki til"):
        services.accept_invite("ekki-til", UserFactory())


def test_household_always_keeps_an_owner(home, owner):
    with pytest.raises(services.HouseholdError):
        services.set_role(owner, MEMBER)
    second = _member(home)
    services.set_role(second, OWNER)
    services.set_role(owner, MEMBER)  # nú er annar eigandi til
    owner.refresh_from_db()
    assert owner.role == MEMBER


def test_cannot_remove_yourself_or_last_owner(home, owner):
    other_owner_home = _member(HouseholdFactory(), OWNER)
    with pytest.raises(services.HouseholdError):
        services.remove_member(owner, by=owner.user)
    with pytest.raises(services.HouseholdError):
        services.remove_member(other_owner_home, by=owner.user)
    member = _member(home)
    services.remove_member(member, by=owner.user)
    assert not Membership.objects.filter(pk=member.pk).exists()


def test_leave_rules(home, owner):
    with pytest.raises(services.HouseholdError, match="Eyddu heimilinu"):
        services.leave(owner)
    member = _member(home)
    with pytest.raises(services.HouseholdError, match="annan að eiganda"):
        services.leave(owner)
    services.leave(member)
    assert home.memberships.count() == 1


def test_delete_household_removes_gifts_and_people(home):
    gift = GiftFactory(season=SeasonFactory(household=home))
    services.delete_household(home)
    assert not Household.objects.filter(pk=home.pk).exists()
    assert not Person.objects.filter(pk=gift.person_id).exists()


# ---------- Views ----------


def test_home_for_guest_shows_landing(client):
    response = client.get(reverse("home"))
    assert response.status_code == 200
    assert reverse("account_signup") in response.text
    assert reverse("account_login") in response.text


def test_home_redirects_to_last_visited_household(client, owner):
    other = MembershipFactory(user=owner.user, household=HouseholdFactory())
    client.force_login(owner.user)
    assert client.get(reverse("home")).url == reverse("gifts:list", args=[owner.household.slug])
    client.get(reverse("gifts:list", args=[other.household.slug]))
    assert client.get(reverse("home")).url == reverse("gifts:list", args=[other.household.slug])


def test_onboarding_creates_household_and_saves_name(client):
    user = UserFactory()
    client.force_login(user)
    page = client.get(reverse("households:create"))
    assert "Velkomin í Jólahjól" in page.text
    response = client.post(reverse("households:create"), {"name": "Okkar", "your_name": "Sibbi"})
    household = Household.objects.get(name="Okkar")
    assert response.url == reverse("gifts:list", args=[household.slug])
    user.refresh_from_db()
    assert user.name == "Sibbi"


def test_invite_flow_through_views(client, home, owner):
    client.force_login(owner.user)
    client.post(reverse("households:invite_create", args=[home.slug]), {"email": "gestur@example.com"})
    invite = home.invites.get()
    page = client.get(reverse("households:settings", args=[home.slug]))
    assert invite.token in page.text

    guest = UserFactory()
    client.force_login(guest)
    assert "Þiggja boð" in client.get(reverse("households:invite_accept", args=[invite.token])).text
    response = client.post(reverse("households:invite_accept", args=[invite.token]))
    assert response.url == reverse("gifts:list", args=[home.slug])
    assert Membership.objects.filter(household=home, user=guest, role=MEMBER).exists()


def test_invite_link_requires_login_and_keeps_next(client, home, owner):
    invite = services.create_invite(home, owner.user)
    url = reverse("households:invite_accept", args=[invite.token])
    response = client.get(url)
    assert response.status_code == 302
    assert response.url.startswith(reverse("account_login"))
    assert "next=" in response.url


def test_used_invite_shows_explanation(client, home, owner):
    invite = services.create_invite(home, owner.user)
    services.accept_invite(invite.token, UserFactory())
    client.force_login(UserFactory())
    response = client.get(reverse("households:invite_accept", args=[invite.token]))
    assert response.status_code == 404
    assert "þegar verið notað" in response.text


def test_settings_actions_report_rule_violations(client, home, owner):
    client.force_login(owner.user)
    response = client.post(reverse("households:leave", args=[home.slug]), follow=True)
    assert "Eyddu heimilinu" in response.text
    assert home.memberships.count() == 1


def test_delete_requires_typing_household_name(client, home, owner):
    client.force_login(owner.user)
    client.post(reverse("households:delete", args=[home.slug]), {"confirm": "vitlaust"})
    assert Household.objects.filter(pk=home.pk).exists()
    response = client.post(reverse("households:delete", args=[home.slug]), {"confirm": home.name.upper()})
    assert response.url == reverse("home")
    assert not Household.objects.filter(pk=home.pk).exists()


# ---------- Aðgangsstýring: gildir sjálfkrafa um allar slóðir heimilis ----------


def _household_url_names(resolver=None, prefix=""):
    """Öll nöfn slóða sem taka `slug` heimilis, svo nýjar slóðir prófist án þess að muna eftir þeim."""
    resolver = resolver or get_resolver()
    for entry in resolver.url_patterns:
        if isinstance(entry, URLResolver):
            ns = f"{prefix}{entry.namespace}:" if entry.namespace else prefix
            yield from _household_url_names(entry, ns)
        elif isinstance(entry, URLPattern) and entry.name and "slug" in entry.pattern.converters:
            yield prefix + entry.name, sorted(entry.pattern.converters)


def _url(name, params, slug):
    return reverse(name, kwargs={p: (slug if p == "slug" else 1) for p in params})


def test_household_urls_are_discovered():
    names = {name for name, _ in _household_url_names()}
    assert {"gifts:list", "households:settings", "households:delete"} <= names


@pytest.mark.parametrize("method", ["get", "post"])
def test_non_member_gets_404_on_every_household_url(client, home, method):
    client.force_login(UserFactory())
    for name, params in _household_url_names():
        response = getattr(client, method)(_url(name, params, home.slug))
        assert response.status_code in (404, 405), f"{method.upper()} {name}: {response.status_code}"
    assert Household.objects.filter(pk=home.pk).exists()


def test_guest_is_sent_to_login_on_every_household_url(client, home):
    for name, params in _household_url_names():
        response = client.get(_url(name, params, home.slug))
        assert response.status_code in (302, 405), name
        if response.status_code == 302:
            assert response.url.startswith(reverse("account_login")), name


def test_member_cannot_do_owner_actions(client, home):
    member = _member(home)
    client.force_login(member.user)
    for name in ("rename", "invite_create", "delete"):
        url = reverse(f"households:{name}", args=[home.slug])
        response = client.post(url, {"name": "x", "confirm": home.name})
        assert response.status_code == 403, name
    assert Household.objects.get(pk=home.pk).name == home.name
    assert client.get(reverse("households:settings", args=[home.slug])).status_code == 200


def test_owner_cannot_touch_memberships_of_other_households(client, home, owner):
    stranger = _member(HouseholdFactory(), OWNER)
    client.force_login(owner.user)
    response = client.post(reverse("households:member_remove", args=[home.slug, stranger.pk]))
    assert response.status_code == 404
    assert Membership.objects.filter(pk=stranger.pk).exists()


# ---------- Öryggishausar ----------


def test_pages_have_strict_csp_but_admin_does_not(client, admin_user):
    csp = client.get(reverse("home")).headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp
    client.force_login(admin_user)
    assert "Content-Security-Policy" not in client.get(f"/{settings.ADMIN_URL}").headers


def _leave_button(html):
    """Textinn í <button> fyrir „Yfirgefa heimili“ (eigindir hans)."""
    end = html.index(">Yfirgefa heimili</button>")
    return html[html.rindex("<button", 0, end) : end]


def test_leave_button_disabled_when_alone_or_last_owner(client, home, owner):
    client.force_login(owner.user)
    page = client.get(reverse("households:settings", args=[home.slug])).text
    assert "disabled" in _leave_button(page) and 'data-tip="Þú ert eini meðlimur' in page

    member = _member(home)
    page = client.get(reverse("households:settings", args=[home.slug])).text
    assert "disabled" in _leave_button(page) and "annan að eiganda" in page

    client.force_login(member.user)
    page = client.get(reverse("households:settings", args=[home.slug])).text
    assert "disabled" not in _leave_button(page)
