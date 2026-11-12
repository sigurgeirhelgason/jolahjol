from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.shortcuts import resolve_url
from django.utils.translation import gettext_lazy as _


class AccountAdapter(DefaultAccountAdapter):
    """allauth er ekki með íslenska þýðingu, svo villuboðin sem notendur sjá eru þýdd hér."""

    error_messages = {
        **DefaultAccountAdapter.error_messages,
        "account_inactive": _("Þessi aðgangur er óvirkur."),
        "invalid_login": _("Innskráning tókst ekki."),
        "too_many_login_attempts": _("Of margar tilraunir. Reyndu aftur eftir smá stund."),
        "rate_limited": _("Hægðu aðeins á, of margar beiðnir í einu."),
        "email_taken": _(
            "Þetta netfang er þegar skráð. Skráðu þig inn, eða smelltu á „Týnt lykilorð?“ "
            "ef þú manst það ekki."
        ),
        "email_password_mismatch": _("Netfangið eða lykilorðið er ekki rétt."),
        "enter_current_password": _("Núverandi lykilorð er ekki rétt."),
        "unknown_email": _("Enginn aðgangur er skráður á þetta netfang."),
        "invalid_password_reset": _("Hlekkurinn er ógildur eða útrunninn."),
        "same_as_current": _("Nýja lykilorðið má ekki vera það sama og það gamla."),
    }

    def get_password_change_redirect_url(self, request) -> str:
        # Sjálfgefið fer allauth aftur á lykilorðssíðuna; hér er það forsíðan (eða ?next=)
        return resolve_url(settings.LOGIN_REDIRECT_URL)
