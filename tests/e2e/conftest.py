import os
import re

import pytest
from django.core import mail
from django.core.cache import cache
from django.urls import reverse

# Playwright (sync) keyrir event loop í sama þræði; Django þarf leyfi til að nota ORM þar
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def pytest_collection_modifyitems(items):
    for item in items:
        if "/e2e/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)
            item.add_marker(pytest.mark.django_db(transaction=True))


@pytest.fixture(autouse=True)
def _clear_cache():
    """Rate limit allauth er í cache; án hreinsunar fá seinni próf með sama netfangi engan kóða."""
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


@pytest.fixture
def login(live_server):
    """Skráir inn í gegnum raunverulega flæðið: netfang → kóði úr pósti."""

    def _login(page, email, navigate=True):
        # navigate=False: síðan er þegar á innskráningu (t.d. eftir tilvísun með ?next=)
        if navigate:
            page.goto(live_server.url + reverse("account_request_login_code"))
        page.get_by_label("Netfang").fill(email)
        page.get_by_role("button", name="Senda mér kóða").click()
        page.get_by_label("Kóði").fill(last_code())
        page.get_by_role("button", name="Skrá inn").click()

    return _login


def last_code() -> str:
    return re.search(r"^\s*(\d{6})\s*$", mail.outbox[-1].body, re.MULTILINE).group(1)
