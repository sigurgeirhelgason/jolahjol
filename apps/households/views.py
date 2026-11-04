from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import FormView, TemplateView

from . import services
from .forms import DeleteHouseholdForm, HouseholdForm, OnboardingForm
from .mixins import SESSION_KEY, HouseholdMixin, OwnerRequiredMixin
from .models import Household, Invite, Membership


def household_home_url(household: Household) -> str:
    return reverse("gifts:list", kwargs={"slug": household.slug})


def home(request):
    """Forsíða: kynning fyrir gesti, annars síðasta heimili notandans."""
    if not request.user.is_authenticated:
        return render(request, "core/landing.html")
    memberships = Membership.objects.filter(user=request.user).select_related("household")
    chosen = memberships.filter(household__slug=request.session.get(SESSION_KEY)).first()
    chosen = chosen or memberships.order_by("created_at").first()
    if chosen is None:
        return redirect("households:create")
    return redirect(household_home_url(chosen.household))


class HouseholdCreateView(LoginRequiredMixin, FormView):
    template_name = "households/create.html"
    form_class = OnboardingForm

    def get_initial(self):
        return {"your_name": self.request.user.name}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["first"] = not Membership.objects.filter(user=self.request.user).exists()
        return ctx

    def form_valid(self, form):
        user = self.request.user
        if form.cleaned_data["your_name"] and form.cleaned_data["your_name"] != user.name:
            user.name = form.cleaned_data["your_name"].strip()
            user.save(update_fields=["name"])
        household = services.create_household(user, form.cleaned_data["name"])
        return redirect(household_home_url(household))


class SettingsView(HouseholdMixin, TemplateView):
    template_name = "households/settings.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["members"] = self.household.memberships.select_related("user").order_by("created_at")
        ctx["owner_count"] = sum(1 for m in ctx["members"] if m.role == Membership.Role.OWNER)
        # Sömu reglur og services.leave: hnappurinn er óvirkur með skýringu frekar en villu eftir á
        if len(ctx["members"]) == 1:
            ctx["leave_blocked"] = _("Þú ert eini meðlimur heimilisins. Eyddu heimilinu í staðinn.")
        elif self.is_owner and ctx["owner_count"] == 1:
            ctx["leave_blocked"] = _("Gerðu einhvern annan að eiganda áður en þú ferð.")
        ctx["seasons"] = self.household.seasons.annotate(
            gift_count=Count("gifts", filter=Q(gifts__deleted_at__isnull=True))
        ).order_by("-year")
        if self.is_owner:
            ctx["invites"] = self.household.invites.usable().select_related("created_by")
            ctx["rename_form"] = HouseholdForm(initial={"name": self.household.name})
        return ctx


def _form_error(form) -> str:
    return " ".join(str(e) for errors in form.errors.values() for e in errors)


class _Action(View):
    """POST-aðgerð á stillingasíðu: villur birtast sem skilaboð og síðan hleðst aftur."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        try:
            response = self.act(request, *args, **kwargs)
        except services.HouseholdError as exc:
            messages.error(request, str(exc))
            response = None
        return response or redirect("households:settings", slug=self.household.slug)

    def act(self, request, *args, **kwargs):
        raise NotImplementedError


class RenameView(OwnerRequiredMixin, _Action):
    def act(self, request, *args, **kwargs):
        form = HouseholdForm(request.POST)
        if not form.is_valid():
            raise services.HouseholdError(_form_error(form))
        services.rename_household(self.household, form.cleaned_data["name"])
        messages.success(request, _("Nafni heimilisins var breytt."))


class InviteCreateView(OwnerRequiredMixin, _Action):
    def act(self, request, *args, **kwargs):
        services.create_invite(self.household, request.user)
        messages.success(request, _("Nýr boðshlekkur er tilbúinn. Afritaðu hann og sendu."))


class InviteRevokeView(OwnerRequiredMixin, _Action):
    def act(self, request, *args, pk, **kwargs):
        services.revoke_invite(get_object_or_404(self.household.invites, pk=pk))
        messages.success(request, _("Boðið var afturkallað."))


class MemberRoleView(OwnerRequiredMixin, _Action):
    def act(self, request, *args, pk, **kwargs):
        member = get_object_or_404(self.household.memberships, pk=pk)
        services.set_role(member, request.POST.get("role", ""))
        messages.success(request, _("Hlutverki %(name)s var breytt.") % {"name": member.user})


class MemberRemoveView(OwnerRequiredMixin, _Action):
    def act(self, request, *args, pk, **kwargs):
        member = get_object_or_404(self.household.memberships.select_related("user"), pk=pk)
        services.remove_member(member, by=request.user)
        messages.success(request, _("%(name)s er ekki lengur í heimilinu.") % {"name": member.user})


class LeaveView(HouseholdMixin, _Action):
    def act(self, request, *args, **kwargs):
        services.leave(self.membership)
        request.session.pop(SESSION_KEY, None)
        messages.success(request, _("Þú hefur yfirgefið „%(name)s“.") % {"name": self.household.name})
        return redirect("home")


class DeleteView(OwnerRequiredMixin, _Action):
    def act(self, request, *args, **kwargs):
        form = DeleteHouseholdForm(request.POST, household=self.household)
        if not form.is_valid():
            raise services.HouseholdError(_form_error(form))
        name = self.household.name
        services.delete_household(self.household)
        request.session.pop(SESSION_KEY, None)
        messages.success(request, _("Heimilinu „%(name)s“ var eytt.") % {"name": name})
        return redirect("home")


class InviteAcceptView(LoginRequiredMixin, View):
    template_name = "households/invite.html"

    def get(self, request, token):
        invite = Invite.objects.select_related("household", "created_by").filter(token=token).first()
        if invite and Membership.objects.filter(household=invite.household, user=request.user).exists():
            return redirect(household_home_url(invite.household))
        problem = None
        if invite is None:
            problem = _("Þetta boð er ekki til eða hefur verið afturkallað.")
        elif invite.accepted_at:
            problem = _("Þetta boð hefur þegar verið notað. Biddu um nýjan hlekk.")
        elif not invite.is_usable:
            problem = _("Þetta boð er útrunnið. Biddu um nýjan hlekk.")
        status = 404 if problem else 200
        return render(request, self.template_name, {"invite": invite, "problem": problem}, status=status)

    def post(self, request, token):
        try:
            membership = services.accept_invite(token, request.user)
        except services.HouseholdError as exc:
            return render(request, self.template_name, {"problem": str(exc)}, status=404)
        messages.success(request, _("Gaman að fá þig í „%(name)s“!") % {"name": membership.household.name})
        return redirect(household_home_url(membership.household))
