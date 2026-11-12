import os
import re

import pytest
from django.core import mail
from django.core.cache import cache
from django.urls import reverse

from apps.accounts.models import User

# Playwright (sync) keyrir event loop í sama þræði; Django þarf leyfi til að nota ORM þar
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def pytest_collection_modifyitems(items):
    for item in items:
        if "/e2e/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)
            item.add_marker(pytest.mark.django_db(transaction=True))


@pytest.fixture(autouse=True)
def _clear_cache():
    """Rate limit allauth er í cache; án hreinsunar lenda seinni próf í takmörkunum."""
    cache.clear()


@pytest.fixture
def browser_context_args(browser_context_args):
    return {**browser_context_args, "locale": "is-IS"}


@pytest.fixture
def page(page):
    """Síða sem fellir prófið ef vafrinn tilkynnir villu (t.d. CSP-brot eða JS-villu)."""
    errors = []
    page.on("console", lambda msg: msg.type == "error" and errors.append(msg.text))
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    yield page
    assert not errors, "Villur í vafra:\n" + "\n".join(errors)


PASSWORD = "jolasveinn-123"


@pytest.fixture
def login(live_server):
    """Skráir inn með netfangi og lykilorði í gegnum innskráningarsíðuna.

    Notandinn verður til (án heimilis) ef hann er ekki til, svo próf sem byrja á stofnun heimilis
    lenda á henni. Nýskráningarsíðan sjálf er prófuð í test_auth_flow.
    """

    def _login(page, email, navigate=True):
        user = User.objects.filter(email=email).first() or User.objects.create_user(email=email)
        user.set_password(PASSWORD)
        user.save()
        # navigate=False: síðan er þegar á innskráningu eða nýskráningu (eftir tilvísun með ?next=)
        if navigate:
            page.goto(live_server.url + reverse("account_login"))
        elif "/accounts/signup/" in page.url:
            page.get_by_role("link", name=re.compile("Skráðu þig inn")).click()
        page.get_by_label("Netfang").fill(email)
        page.get_by_label("Lykilorð").fill(PASSWORD)
        page.get_by_role("button", name="Skrá inn").click()
        page.wait_for_url(lambda url: "/accounts/login/" not in url)

    return _login


def last_link() -> str:
    return re.search(r"https?://\S+", mail.outbox[-1].body).group(0)
