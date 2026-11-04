from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
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
    }

    def generate_login_code(self) -> str:
        # Fastur kóði í þróun (config/settings/dev.py); kerfisathugun bannar hann án DEBUG
        if settings.DEBUG and settings.DEV_LOGIN_CODE:
            return settings.DEV_LOGIN_CODE
        return super().generate_login_code()
