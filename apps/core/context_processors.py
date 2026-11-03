from django.conf import settings


def site(request):
    return {"google_login": bool(settings.GOOGLE_CLIENT_ID)}
