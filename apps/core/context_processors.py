from django.conf import settings


def site(request):
    # site_url: fullar slóðir í Open Graph-merkjum (base.html), sem Facebook o.fl. krefjast
    return {"google_login": bool(settings.GOOGLE_CLIENT_ID), "site_url": settings.SITE_URL}
