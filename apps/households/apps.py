from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class HouseholdsConfig(AppConfig):
    name = "apps.households"
    label = "households"
    verbose_name = _("Heimili")
