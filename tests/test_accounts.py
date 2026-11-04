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
from tests.factories import MembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _request_code(client, email):
    return client.post(reverse("account_request_login_code"), {"email": email})


def _code_from_outbox() -> str:
    match = re.search(r"^\s*(\d{6})\s*$", mail.outbox[-1].body, re.MULTILINE)
    assert match, mail.outbox[-1].body
    return match.group(1)


def test_new_email_creates_account_and_logs_in_with_code(client):
    response = _request_code(client, "Ny@Example.com")
    assert response.status_code == 302
    assert response.url.startswith(reverse("account_confirm_login_code"))

    user = User.objects.get(email="ny@example.com")
    assert not user.has_usable_password()
    assert len(mail.outbox) == 1
    assert "Innskráningarkóði" in mail.outbox[0].subject

    response = client.post(reverse("account_confirm_login_code"), {"code": _code_from_outbox()})
    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)
    assert EmailAddress.objects.get(user=user).verified
    # Enginn heimili enn → stofnun heimilis
    assert client.get(reverse("home")).url == reverse("households:create")


def test_existing_user_without_email_address_record_can_log_in(client):
    """Notendur úr import_legacy --owner eða admin hafa enga EmailAddress-færslu."""
    user = UserFactory(email="eigandi@example.com")
    _request_code(client, "eigandi@example.com")
    client.post(reverse("account_confirm_login_code"), {"code": _code_from_outbox()})
    assert client.session["_auth_user_id"] == str(user.pk)
    assert User.objects.count() == 1
    assert EmailAddress.objects.get(user=user).verified


def test_requesting_twice_does_not_duplicate_account(client):
    _request_code(client, "a@example.com")
    client.logout()
    _request_code(client, "A@example.com")
    assert User.objects.filter(email__iexact="a@example.com").count() == 1
    assert EmailAddress.objects.filter(email__iexact="a@example.com").count() == 1


def test_wrong_code_is_rejected(client):
    _request_code(client, "a@example.com")
    response = client.post(reverse("account_confirm_login_code"), {"code": "000000"})
    assert response.status_code == 200
    assert "Kóðinn er ekki réttur" in response.text
    assert "_auth_user_id" not in client.session


def test_login_and_signup_urls_redirect_to_code_page(client):
    for name in ("account_login", "account_signup"):
        response = client.get(reverse(name) + "?next=/h/x/")
        assert response.status_code == 302
        assert response.url == reverse("account_request_login_code") + "?next=/h/x/"


def test_prune_users_removes_only_stale_unused_accounts():
    old = timezone.now() - timedelta(days=3)
    stale = UserFactory(date_joined=old)
    UserFactory(date_joined=old, last_login=old)  # hefur skráð sig inn
    MembershipFactory(user=UserFactory(date_joined=old))  # er í heimili
    UserFactory()  # nýr, gæti enn verið að bíða eftir kóða
    UserFactory(date_joined=old, is_staff=True)

    call_command("prune_users", stdout=io.StringIO())
    assert not User.objects.filter(pk=stale.pk).exists()
    assert User.objects.count() == 4


def test_dev_login_code_works_only_with_debug(client, settings):
    from apps.accounts.adapter import AccountAdapter

    settings.DEV_LOGIN_CODE = "666"
    settings.DEBUG = True
    assert AccountAdapter().generate_login_code() == "666"
    _request_code(client, "dev@example.com")
    client.post(reverse("account_confirm_login_code"), {"code": "666"})
    assert "_auth_user_id" in client.session

    settings.DEBUG = False
    assert AccountAdapter().generate_login_code() != "666"


def test_check_rejects_dev_login_code_without_debug(settings):
    from apps.accounts.checks import dev_login_code_only_in_debug

    settings.DEV_LOGIN_CODE, settings.DEBUG = "666", False
    assert [e.id for e in dev_login_code_only_in_debug(None)] == ["accounts.E001"]
    settings.DEBUG = True
    assert dev_login_code_only_in_debug(None) == []
