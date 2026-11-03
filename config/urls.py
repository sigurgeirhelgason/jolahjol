from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

# Eina leiðin inn er netfang → kóði; lykilorðasíður allauth vísa þangað
_to_code = RedirectView.as_view(pattern_name="account_request_login_code", query_string=True)

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("accounts/login/", _to_code, name="account_login"),
    path("accounts/signup/", _to_code, name="account_signup"),
    path("accounts/", include("allauth.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.households.urls")),
    path("", include("apps.gifts.urls")),
]
