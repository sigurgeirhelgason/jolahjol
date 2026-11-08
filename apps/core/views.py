from django.db import connection
from django.http import HttpResponse, JsonResponse


def healthz(request):
    """Fyrir uptime-vöktun og docker healthcheck: svarar 200 ef gagnagrunnurinn svarar."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"ok": True})


ROBOTS_TXT = """User-agent: *
Disallow: /h/
Disallow: /accounts/
"""


def robots_txt(request):
    """Heimilissíður og innskráning eru ekki fyrir leitarvélar. Óskalistar (/o/) eru ekki bannaðir
    hér því þá sæi Google aldrei noindex á þeim; hlekkirnir finnast hvort eð er hvergi.
    Admin-slóðin er leynileg og er því ekki nefnd."""
    return HttpResponse(ROBOTS_TXT, content_type="text/plain")
