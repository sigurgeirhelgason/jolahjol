import io
import re
from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress
from django.core import mail
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.households import services
from apps.households.models import Household, Membership
from tests.factories import MembershipFactory, UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "jolasveinn-123"


def _signup(client, url=None, **data):
    data = {"name": "Okkar", "your_name": "Sibbi", "email": "Ny@Example.com", "password1": PASSWORD, **data}
    return client.post(url or reverse("account_signup"), {k: v for k, v in data.items() if v is not None})


def _user_with_password(email="a@example.com", verified=True):
    user = UserFactory(email=email)
    user.set_password(PASSWORD)
    user.save()
    EmailAddress.objects.create(email=email, user=user, verified=verified, primary=True)
    return user


# ---------- Nýskráning ----------


def test_signup_page_has_email_password_name_and_household_in_order(client):
    page = client.get(reverse("account_signup")).text
    assert "Velkomin í Jólahjól" in page
    positions = [page.index(f'name="{f}"') for f in ("email", "password1", "your_name", "name")]
    assert positions == sorted(positions)
    assert 'name="password2"' not in page


def test_signup_creates_account_and_household_in_one_step(client):
    response = _signup(client)
    assert response.status_code == 302
    user = User.objects.get(email="ny@example.com")
    assert user.name == "Sibbi"
    assert user.check_password(PASSWORD)
    assert client.session["_auth_user_id"] == str(user.pk)

    household = Household.objects.get(name="Okkar")
    assert Membership.objects.get(user=user, household=household).role == Membership.Role.OWNER
    assert client.get(response.url, follow=True).redirect_chain[-1][0].startswith(f"/h/{household.slug}/")
    # Enginn póstur: hvorki kóði né staðfesting. Netfangið er óstaðfest (sjá wipe_password í allauth).
    assert mail.outbox == []
    assert not EmailAddress.objects.get(user=user).verified


def test_signup_needs_household_and_name(client):
    response = _signup(client, name="", your_name="")
    assert response.status_code == 200
    assert response.text.count("errorlist") >= 2
    assert not User.objects.exists()


def test_signup_rejects_weak_password(client):
    response = _signup(client, password1="12345678")
    assert response.status_code == 200
    assert not User.objects.exists()
    assert not Household.objects.exists()


def test_signup_with_taken_email_points_to_login_and_reset(client):
    _user_with_password("ny@example.com")
    response = _signup(client)
    assert response.status_code == 200
    assert "Þetta netfang er þegar skráð" in response.text
    assert User.objects.count() == 1 and not Household.objects.exists()
    assert mail.outbox == []


def test_signup_keeps_safe_next(client):
    response = _signup(client, url=reverse("account_signup") + "?next=/h/x/", next="/h/x/")
    assert response.url == "/h/x/"


def test_signup_from_invite_skips_household_and_joins_after(client):
    owner = MembershipFactory(role=Membership.Role.OWNER)
    invite = services.create_invite(owner.household, owner.user)
    invite_url = reverse("households:invite_accept", args=[invite.token])

    page = client.get(reverse("account_signup") + f"?next={invite_url}").text
    assert 'name="name"' not in page
    assert "Stofnaðu aðgang" in page

    response = _signup(client, name=None, your_name="Maki", next=invite_url)
    assert response.url == invite_url
    user = User.objects.get(email="ny@example.com")
    assert user.name == "Maki"
    assert not Membership.objects.filter(user=user).exists()  # boðið er þegið á næstu síðu
    assert 'value="Maki"' in client.get(invite_url).text


# ---------- Innskráning ----------


def test_log_in_with_password(client):
    _user_with_password()
    response = client.post(reverse("account_login"), {"login": "A@example.com", "password": PASSWORD})
    assert response.status_code == 302
    assert response.url == reverse("home")


def test_unverified_email_can_log_in(client):
    _user_with_password(verified=False)
    response = client.post(reverse("account_login"), {"login": "a@example.com", "password": PASSWORD})
    assert response.status_code == 302


def test_wrong_password_is_rejected_in_icelandic(client):
    _user_with_password()
    for email in ("a@example.com", "enginn@example.com"):
        response = client.post(reverse("account_login"), {"login": email, "password": "rangt-lykilord"})
        assert response.status_code == 200
        assert "Netfangið eða lykilorðið er ekki rétt" in response.text
    assert "_auth_user_id" not in client.session


def test_login_code_is_gone(client):
    page = client.get(reverse("account_login")).text
    assert "kóða" not in page.replace("Fékkstu áður kóða", "")


def test_login_and_signup_link_to_each_other_and_keep_next(client):
    login = client.get(reverse("account_login") + "?next=/h/x/").text
    assert reverse("account_signup") + "?next=/h/x/" in login
    assert reverse("account_reset_password") in login
    signup = client.get(reverse("account_signup") + "?next=/h/x/").text
    assert reverse("account_login") + "?next=/h/x/" in signup


# ---------- Týnt lykilorð ----------


def _reset_link() -> str:
    match = re.search(r"https?://\S+/accounts/password/reset/key/\S+", mail.outbox[-1].body)
    assert match, mail.outbox[-1].body
    return match.group(0)


def test_lost_password_sends_link_and_logs_in_with_new_password(client):
    user = UserFactory(email="a@example.com")
    user.set_unusable_password()  # eins og þeir sem skráðu sig áður inn með kóða
    user.save()

    response = client.post(reverse("account_reset_password"), {"email": "A@example.com"})
    assert response.url == reverse("account_reset_password_done")
    assert len(mail.outbox) == 1
    assert "Nýtt lykilorð" in mail.outbox[0].subject

    response = client.get(_reset_link(), follow=True)
    assert "Veldu nýtt lykilorð" in response.text
    response = client.post(response.redirect_chain[-1][0], {"password1": "grylan-og-leppaludi"})
    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)
    user.refresh_from_db()
    assert user.check_password("grylan-og-leppaludi")


def test_lost_password_for_unknown_email_sends_nothing(client):
    response = client.post(reverse("account_reset_password"), {"email": "enginn@example.com"})
    assert response.status_code == 200
    assert "Enginn aðgangur er skráður á þetta netfang" in response.text
    assert mail.outbox == []


def test_bad_reset_link_explains(client):
    user = _user_with_password()
    response = client.get(reverse("account_reset_password_from_key", args=[user.pk, "rangur-lykill"]))
    assert "Hlekkurinn virkar ekki" in response.text


# ---------- Lykilorð í stillingum ----------


def test_change_password_needs_current_one(client):
    user = _user_with_password()
    client.force_login(user)
    page = client.get(reverse("account_change_password"))
    assert "Núverandi lykilorð" in page.text

    data = {"oldpassword": "rangt-lykilord", "password1": "grylan-og-leppaludi"}
    response = client.post(reverse("account_change_password"), data)
    assert response.status_code == 200
    assert "Núverandi lykilorð er ekki rétt" in response.text

    data["oldpassword"] = PASSWORD
    response = client.post(reverse("account_change_password"), data)
    assert response.url == reverse("home")
    user.refresh_from_db()
    assert user.check_password("grylan-og-leppaludi")


def test_set_password_without_one(client):
    user = UserFactory()
    user.set_unusable_password()  # t.d. kom inn með Google
    user.save()
    client.force_login(user)
    response = client.post(
        reverse("account_set_password") + "?next=/h/x/", {"password1": PASSWORD, "next": "/h/x/"}
    )
    assert response.url == "/h/x/"
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_password_is_managed_from_household_settings(client):
    membership = MembershipFactory(user__email="a@example.com")
    user, household = membership.user, membership.household
    user.set_unusable_password()
    user.save()
    client.force_login(user)
    url = reverse("households:settings", args=[household.slug])

    page = client.get(url).text
    assert "Velja lykilorð" in page
    assert reverse("account_set_password") + "?next=" in page

    user.set_password(PASSWORD)
    user.save()
    client.force_login(user)
    page = client.get(url).text
    assert "Breyta lykilorði" in page
    assert reverse("account_change_password") + "?next=" in page


def test_prune_users_removes_only_stale_unused_accounts():
    old = timezone.now() - timedelta(days=3)
    stale = UserFactory(date_joined=old)
    UserFactory(date_joined=old, last_login=old)  # hefur skráð sig inn
    MembershipFactory(user=UserFactory(date_joined=old))  # er í heimili
    UserFactory()  # nýr
    UserFactory(date_joined=old, is_staff=True)

    call_command("prune_users", stdout=io.StringIO())
    assert not User.objects.filter(pk=stale.pk).exists()
    assert User.objects.count() == 4


def test_password_reset_verifies_email(client):
    """Án þessa þurrkar Google-innskráning út lykilorðið (wipe_password í allauth)."""
    _signup(client)
    client.logout()
    client.post(reverse("account_reset_password"), {"email": "ny@example.com"})
    response = client.get(_reset_link(), follow=True)
    client.post(response.redirect_chain[-1][0], {"password1": "grylan-og-leppaludi"})
    assert EmailAddress.objects.get(email="ny@example.com").verified


def test_old_login_code_urls_redirect_to_login(client):
    for url in ("/accounts/login/code/?next=/h/x/", "/accounts/login/code/confirm/"):
        response = client.get(url)
        assert response.status_code in (301, 302)
        assert response.url.startswith(reverse("account_login"))
    assert client.get("/accounts/login/code/?next=/h/x/").url.endswith("?next=/h/x/")


@pytest.mark.parametrize("suffix", ["", "?a=1", "#x"])
def test_invite_next_is_recognised_with_query_fragment_or_host(suffix):
    from apps.accounts.forms import joins_by_invite

    path = reverse("households:invite_accept", args=["abc"])
    assert joins_by_invite(path + suffix)
    assert joins_by_invite("https://jolahjol.is" + path + suffix)
    assert not joins_by_invite("/h/x/" + suffix)
