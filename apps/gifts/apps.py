from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class GiftsConfig(AppConfig):
    name = "apps.gifts"
    label = "gifts"
    verbose_name = _("Gjafir")
