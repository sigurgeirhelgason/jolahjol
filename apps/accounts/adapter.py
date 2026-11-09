from urllib.parse import urlencode

from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import resolve_url
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class AccountAdapter(DefaultAccountAdapter):
    """allauth er ekki með íslenska þýðingu, svo villuboðin sem notendur sjá eru þýdd hér."""

    error_messages = {
        **DefaultAccountAdapter.error_messages,
        "account_inactive": _("Þessi aðgangur er óvirkur."),
        "incorrect_code": _("Kóðinn er ekki réttur."),
        "invalid_login": _("Innskráning tókst ekki."),
        "too_many_login_attempts": _("Of margar tilraunir. Reyndu aftur eftir smá stund."),
        "rate_limited": _("Hægðu aðeins á, of margar beiðnir í einu."),
        "email_taken": _("Þetta netfang er þegar skráð."),
        "unverified_primary_email": _("Það á eftir að staðfesta netfangið."),
        "email_password_mismatch": _("Netfangið eða lykilorðið er ekki rétt."),
    }

    def generate_login_code(self) -> str:
        # Fastur kóði í þróun (config/settings/dev.py); kerfisathugun bannar hann án DEBUG
        if settings.DEBUG and settings.DEV_LOGIN_CODE:
            return settings.DEV_LOGIN_CODE
        return super().generate_login_code()

    def post_login(self, request, user, **kwargs):
        """Fyrsta innskráning með kóða: bjóða einu sinni upp á lykilorð, svo áfram þangað sem átti að fara."""
        response = super().post_login(request, user, **kwargs)
        via_google = "sociallogin" in (kwargs.get("signal_kwargs") or {})
        if (
            isinstance(response, HttpResponseRedirect)
            and not via_google
            and not user.password_offered
            and not user.has_usable_password()
        ):
            type(user).objects.filter(pk=user.pk).update(password_offered=True)
            query = urlencode({"next": response.url})
            return HttpResponseRedirect(f"{reverse('account_set_password')}?{query}")
        return response

    def get_password_change_redirect_url(self, request) -> str:
        # Sjálfgefið fer allauth aftur á lykilorðssíðuna; hér er það forsíðan (eða ?next=)
        return resolve_url(settings.LOGIN_REDIRECT_URL)
