"""Stillingar sem skipta máli í prod: aðallén og healthz."""

import pytest

HOSTS = ["jolahjol.is", ".jolahjol.is", ".xn--jlahjl-bxae.is", "testserver", "localhost"]


@pytest.fixture
def canonical(settings):
    settings.CANONICAL_HOST = "jolahjol.is"
    settings.ALLOWED_HOSTS = HOSTS


@pytest.mark.parametrize("host", ["www.jolahjol.is", "xn--jlahjl-bxae.is", "www.xn--jlahjl-bxae.is"])
def test_other_domains_redirect_to_canonical(client, canonical, host):
    response = client.get("/o/abc/?x=1", HTTP_HOST=host)
    assert response.status_code == 301
    assert response["Location"] == "https://jolahjol.is/o/abc/?x=1"


@pytest.mark.django_db
def test_canonical_host_is_served(client, canonical):
    response = client.get("/healthz", HTTP_HOST="jolahjol.is")
    assert response.status_code == 200


@pytest.mark.django_db
def test_healthz_is_not_redirected(client, canonical, settings):
    settings.SECURE_SSL_REDIRECT = True
    assert client.get("/healthz", HTTP_HOST="localhost").status_code == 200


def test_unknown_host_is_rejected_not_redirected(client, canonical):
    assert client.get("/", HTTP_HOST="evil.example").status_code == 400


@pytest.mark.django_db
def test_no_redirect_without_canonical_host(client, settings):
    settings.CANONICAL_HOST = ""
    settings.ALLOWED_HOSTS = HOSTS
    assert client.get("/healthz", HTTP_HOST="www.jolahjol.is").status_code == 200


def test_robots_txt_keeps_households_out_but_not_wishlists(client, settings):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/plain"
    body = response.text
    assert "Disallow: /h/" in body
    assert "/o/" not in body
    assert settings.ADMIN_URL not in body
