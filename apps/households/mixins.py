from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import Household, Membership

SESSION_KEY = "household"


class HouseholdMixin(LoginRequiredMixin):
    """Öll gögn heimilis fara í gegnum þetta.

    Heimilið er sótt úr slóðinni (`/h/<slug>/…`) og aðeins ef notandinn er meðlimur. Annars
    404, ekki 403, svo ekki sé hægt að giska á hvaða heimili eru til.
    """

    owner_required = False

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.membership = (
            Membership.objects.select_related("household", "user")
            .filter(user=request.user, household__slug=kwargs["slug"])
            .first()
        )
        if self.membership is None:
            raise Http404
        if self.owner_required and not self.is_owner:
            raise PermissionDenied
        self.household = self.membership.household
        request.session[SESSION_KEY] = self.household.slug
        return super().dispatch(request, *args, **kwargs)

    @property
    def is_owner(self) -> bool:
        return self.membership.role == Membership.Role.OWNER

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            household=self.household,
            membership=self.membership,
            is_owner=self.is_owner,
            my_households=Household.objects.for_member(self.request.user).order_by("name"),
        )
        return ctx


class OwnerRequiredMixin(HouseholdMixin):
    owner_required = True
