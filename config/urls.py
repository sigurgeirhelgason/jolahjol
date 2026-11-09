from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

# Nýskráning er netfang → kóði, og kóðinn kemur í stað endurstillingar á lykilorði
_to_code = RedirectView.as_view(pattern_name="account_request_login_code", query_string=True)

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("accounts/signup/", _to_code, name="account_signup"),
    path("accounts/password/reset/", _to_code, name="account_reset_password"),
    path("accounts/", include("allauth.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.households.urls")),
    path("", include("apps.gifts.urls")),
    path("", include("apps.wishlists.urls")),
]
