from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.accounts import views as account_views

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    # Á undan allauth: nýskráning með heimili og nafni (sjá apps.accounts.views)
    path("accounts/signup/", account_views.signup, name="account_signup"),
    # Innskráning með kóða er hætt; gömul bókamerki og póstar lenda á innskráningunni
    path("accounts/login/code/", RedirectView.as_view(pattern_name="account_login", query_string=True)),
    path(
        "accounts/login/code/confirm/",
        RedirectView.as_view(pattern_name="account_login", query_string=True),
    ),
    path("accounts/", include("allauth.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.households.urls")),
    path("", include("apps.gifts.urls")),
    path("", include("apps.wishlists.urls")),
]
