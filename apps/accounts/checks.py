from django.conf import settings
from django.core.checks import Error, register


@register(deploy=False)
def dev_login_code_only_in_debug(app_configs, **kwargs):
    """Fastur innskráningarkóði má aldrei fara í loftið."""
    if settings.DEV_LOGIN_CODE and not settings.DEBUG:
        return [
            Error(
                "DEV_LOGIN_CODE er sett án DEBUG.",
                hint="Fastur kóði hleypir hverjum sem er inn. Hann á aðeins heima í config/settings/dev.py.",
                id="accounts.E001",
            )
        ]
    return []
