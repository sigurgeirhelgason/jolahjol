from django.views.generic import TemplateView

from apps.households.mixins import HouseholdMixin


class GiftListView(HouseholdMixin, TemplateView):
    template_name = "gifts/list.html"
