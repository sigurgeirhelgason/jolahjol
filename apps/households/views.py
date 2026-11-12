from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import FormView, TemplateView

from apps.core.text import is_sort_key
from apps.gifts.models import Person

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
        household = services.create_household(
            self.request.user, form.cleaned_data["name"], form.cleaned_data["your_name"]
        )
        # T.d. komið af opnu óskalistasíðunni („Stofna þinn gjafalista“) til að bæta einhverjum við
        nxt = self.request.POST.get("next") or self.request.GET.get("next", "")
        if nxt and url_has_allowed_host_and_scheme(nxt, {self.request.get_host()}, self.request.is_secure()):
            return redirect(nxt)
        return redirect(household_home_url(household))


class SettingsView(HouseholdMixin, TemplateView):
    template_name = "households/settings.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["members"] = self.household.memberships.select_related("user", "person").order_by("created_at")
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
            ctx["invites"] = self.household.invites.usable().select_related("created_by", "person")
            ctx["rename_form"] = HouseholdForm(initial={"name": self.household.name})
            # Einstaklingar sem hægt er að tengja notanda („Á listanum sem“)
            linked = {m.person_id for m in ctx["members"] if m.person_id}
            # Viðtakendur (og þeir sem eru þegar tengdir), ekki þeir sem eru bara gefendur
            people = Person.objects.recipients().filter(household=self.household) | Person.objects.filter(
                pk__in=linked
            )
            people = sorted(people.distinct(), key=lambda p: is_sort_key(p.name))
            ctx["people"] = people
            ctx["free_people"] = [p for p in people if p.pk not in linked]
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


def _person_from_post(request, household):
    pk = request.POST.get("person") or ""
    if not pk.isdigit():
        return None
    return get_object_or_404(Person, pk=int(pk), household=household)


class InviteCreateView(OwnerRequiredMixin, _Action):
    def act(self, request, *args, **kwargs):
        email = request.POST.get("email", "").strip()[:254]
        if not email:
            raise services.HouseholdError(_("Skrifaðu netfangið sem boðið á að fara á."))
        person = _person_from_post(request, self.household)
        invite = services.create_invite(self.household, request.user, person=person, email=email)
        if invite.mailed:
            text = _("Boð var sent á %(email)s. Hlekkinn má líka afrita hér fyrir neðan.")
            messages.success(request, text % {"email": email})
        else:
            text = _(
                "Boðið var búið til en pósturinn á %(email)s fór ekki. Afritaðu hlekkinn hér fyrir neðan."
            )
            messages.error(request, text % {"email": email})


def person_invite_context(household, person, is_owner: bool) -> dict:
    """„Bjóða í heimilið“ í einstaklingsglugganum (gifts.views.PersonDialogView notar líka)."""
    member = person.memberships.select_related("user").first()
    return {
        "household": household,
        "person": person,
        "is_owner": is_owner,
        "member": member,
        "invite": None if member else services.invite_for(person),
    }


class _PersonInviteSection(OwnerRequiredMixin, View):
    """Boð úr einstaklingsglugganum: hlutinn er sendur aftur eftir aðgerð."""

    http_method_names = ["post"]

    def respond(self, person, **extra):
        ctx = {**person_invite_context(self.household, person, True), **extra}
        html = render_to_string("households/partials/person_invite.html", ctx, request=self.request)
        return HttpResponse(html)

    def get_person(self, pk):
        return get_object_or_404(Person, pk=pk, household=self.household)


class PersonInviteCreateView(_PersonInviteSection):
    def post(self, request, slug, pk):
        person = self.get_person(pk)
        email = request.POST.get("invite_email", "").strip()[:254]
        if not email:
            return self.respond(person, error=_("Skrifaðu netfangið sem boðið á að fara á."))
        try:
            invite = services.create_invite(self.household, request.user, person=person, email=email)
        except services.HouseholdError as exc:
            return self.respond(person, error=str(exc), email=email)
        if not invite.mailed:
            return self.respond(
                person, error=_("Pósturinn fór ekki. Afritaðu hlekkinn og sendu hann á annan hátt.")
            )
        return self.respond(person)


class PersonInviteRevokeView(_PersonInviteSection):
    def post(self, request, slug, pk):
        person = self.get_person(pk)
        self.household.invites.usable().filter(person=person).delete()
        return self.respond(person)


class ClaimPersonView(HouseholdMixin, View):
    """„Hver ert þú á listanum?“ (borðinn á síðum jólaársins): aðeins meðan notandinn er ótengdur."""

    http_method_names = ["post"]

    def post(self, request, slug):
        person = _person_from_post(request, self.household)
        try:
            services.claim_person(self.membership, person=person, name=request.POST.get("name", ""))
        except services.HouseholdError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Takk! Nú sérðu ekki hvað aðrir ætla að gefa þér."))
        return redirect(household_home_url(self.household))


class InviteRevokeView(OwnerRequiredMixin, _Action):
    def act(self, request, *args, pk, **kwargs):
        services.revoke_invite(get_object_or_404(self.household.invites, pk=pk))
        messages.success(request, _("Boðið var afturkallað."))


class MemberRoleView(OwnerRequiredMixin, _Action):
    def act(self, request, *args, pk, **kwargs):
        member = get_object_or_404(self.household.memberships, pk=pk)
        services.set_role(member, request.POST.get("role", ""))
        messages.success(request, _("Hlutverki %(name)s var breytt.") % {"name": member.user})


class MemberPersonView(OwnerRequiredMixin, _Action):
    """„Á listanum sem“: hvaða einstaklingur á listanum meðlimurinn er."""

    def act(self, request, *args, pk, **kwargs):
        member = get_object_or_404(self.household.memberships.select_related("user"), pk=pk)
        person = _person_from_post(request, self.household)
        services.set_person(member, person, by=request.user)
        if person:
            text = _("%(user)s er %(name)s á listanum.") % {"user": member.user, "name": person.name}
        else:
            text = _("Tenging %(user)s við listann var fjarlægð.") % {"user": member.user}
        messages.success(request, text)


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
        invites = Invite.objects.select_related("household", "created_by", "person")
        invite = invites.filter(token=token).first()
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
        ctx = {"invite": invite, "problem": problem, "name": request.user.name}
        return render(request, self.template_name, ctx, status=status)

    def post(self, request, token):
        name = request.POST.get("name", "")[:100]
        try:
            membership = services.accept_invite(token, request.user, name)
        except services.InvalidName as exc:
            invite = Invite.objects.select_related("household", "created_by", "person").get(token=token)
            ctx = {"invite": invite, "name": name, "name_error": str(exc)}
            return render(request, self.template_name, ctx, status=422)
        except services.HouseholdError as exc:
            return render(request, self.template_name, {"problem": str(exc)}, status=404)
        messages.success(request, _("Gaman að fá þig í „%(name)s“!") % {"name": membership.household.name})
        return redirect(household_home_url(membership.household))
