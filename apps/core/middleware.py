from django.conf import settings
from django.middleware.csp import ContentSecurityPolicyMiddleware as BaseCSPMiddleware


class ContentSecurityPolicyMiddleware(BaseCSPMiddleware):
    """CSP frá Django, nema í admin.

    Unfold notar inline-skriftur og stíla, svo ströng CSP myndi brjóta admin. Admin er bara
    fyrir starfsfólk og er á sér slóð (DJANGO_ADMIN_URL), svo undanþágan er afmörkuð.
    """

    def process_response(self, request, response):
        if request.path.startswith(f"/{settings.ADMIN_URL}"):
            response._csp_config = {}
        return super().process_response(request, response)
