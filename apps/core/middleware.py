from django.conf import settings
from django.http import HttpResponsePermanentRedirect
from django.http.request import split_domain_port, validate_host
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


class CanonicalHostMiddleware:
    """Vísar www.jolahjol.is og jólahjól.is (xn--jlahjl-bxae.is) á aðallénið (CANONICAL_HOST).

    Aðeins lén sem eru í ALLOWED_HOSTS eru færð; önnur fá 400 eins og venjulega. healthz er
    undanskilið því docker healthcheck kemur inn á localhost.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        canonical = settings.CANONICAL_HOST
        if canonical and request.path != "/healthz":
            host, _port = split_domain_port(request.META.get("HTTP_HOST", ""))
            if host and host != canonical and validate_host(host, settings.ALLOWED_HOSTS):
                return HttpResponsePermanentRedirect(f"https://{canonical}{request.get_full_path()}")
        return self.get_response(request)
