from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class LegacyConfig(AppConfig):
    name = "apps.legacy"
    label = "legacy"
    verbose_name = _("Eldri gögn")
