from django.db import connection
from django.http import JsonResponse


def healthz(request):
    """Fyrir uptime-vöktun og docker healthcheck: svarar 200 ef gagnagrunnurinn svarar."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"ok": True})
