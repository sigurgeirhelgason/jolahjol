import contextlib
import json
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.signing import BadSignature
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View
from django_htmx.http import trigger_client_event
from django_ratelimit.decorators import ratelimit

from apps.core.text import is_sort_key, name_match
from apps.gifts.forms import WishForm
from apps.gifts.models import Group, Person
from apps.gifts.services.gifts import and_join, save_wish
from apps.households.mixins import SESSION_KEY, HouseholdMixin
from apps.households.models import Membership

from . import services
from .services import Reservation, WishlistError

COOKIE = "fratekningar"
NAME_COOKIE = "oskalisti_nafn"
SALT = "wishlists.reservations"
YEAR_SECONDS = 365 * 24 * 3600


def _reservations(request) -> dict[str, dict]:
    """Frátekningar þessa tækis: {idea_id: {"s": leyndarmál, "g": bætt við sem gefanda}}."""
    try:
        return json.loads(request.get_signed_cookie(COOKIE, salt=SALT, default="{}"))
    except (BadSignature, ValueError):
        return {}


def _is_mine(idea, mine: dict) -> bool:
    """Tók þetta tæki frá? Leyndarmálið verður að passa: frátekningin gæti hafa verið
    felld niður af heimilinu og einhver annar tekið frá síðan."""
    secret = mine.get(str(idea.pk), {}).get("s")
    return bool(idea.reservation_secret) and secret == idea.reservation_secret


def _set_cookie(response, key, value):
    response.set_signed_cookie(
        key,
        value,
        salt=SALT,
        max_age=YEAR_SECONDS,
        httponly=True,
        samesite="Lax",
        secure=settings.SESSION_COOKIE_SECURE,
    )


def _private(response):
    """Opna síðan: hvorki leitarvélar, skyndiminni né tilvísun (referrer) á aðrar síður."""
    response["X-Robots-Tag"] = "noindex, nofollow"
    # same-origin, ekki no-referrer: með no-referrer sendir Chrome „Origin: null“ með formum og
    # CSRF-vörnin hafnar þeim. same-origin dugar: hlekkurinn lekur ekki til búða (og rel=noreferrer).
    response["Referrer-Policy"] = "same-origin"
    response["Cache-Control"] = "private, no-store"
    return response


def _share_or_404(token):
    share = services.get_active(token)
    if share is None:
        raise Http404
    return share


class PublicWishlistView(View):
    """/o/<token>/: hugmyndir eins einstaklings, án innskráningar."""

    def get(self, request, token):
        share = services.get_active(token)
        if share is None:
            return _private(render(request, "wishlists/gone.html", status=404))
        season, ideas = services.visible_ideas(share)
        mine = _reservations(request)
        # Það sem aðrir hafa tekið frá (eða keypt) sést ekki; aðeins það sem er laust og það
        # sem þetta tæki tók frá sjálft (svo hægt sé að hætta við)
        rows = [
            {"idea": i, "mine": _is_mine(i, mine)}
            for i in ideas
            if not services.is_taken(i) or _is_mine(i, mine)
        ]
        try:
            name = request.get_signed_cookie(NAME_COOKIE, salt=SALT, default="")
        except BadSignature:
            name = ""
        ctx = {
            "share": share,
            "person": share.person,
            "season": season,
            "rows": rows,
            "all_taken": bool(ideas) and not rows,
            "name": name,
            "follow": _follow_context(request, share),
        }
        return _private(render(request, "wishlists/public.html", ctx))


def _follow_context(request, share) -> dict:
    """„Bæta á þitt Jólahjól“ neðst á opnu síðunni (sjá services.follow)."""
    if not request.user.is_authenticated:
        return {"state": "anonymous", **_owners(share)}
    return {**_follow_state(request.user, share), **_owners(share)}


def _owners(share) -> dict:
    """„… allar hugmyndir sem Jói (og Anna) bæta við“: notendur heimilisins sem deildi listanum."""
    return owners_context(share.person.household)


def owners_context(household) -> dict:
    """Notendur heimilis sem deildi óskalista, t.d. {"owners": "Jói og Anna", "owners_count": 2}.

    Án notenda kemur nafn heimilisins; `owners_count` velur eintölu eða fleirtölu sagnar.
    """
    owners = services.member_names(household)  # aldrei netfang: sést á opnu síðunni
    return {
        "owners": and_join(owners) if owners else household.name,
        "owners_count": max(len(owners), 1),  # „Jói bætir við“ / „Jói og Anna bæta við“
    }


def _match(name: str, target: str) -> float:
    """Aðeins raunveruleg samsvörun telst (≥ 0,75: Siggi, Sigga litla, ekki Inga).

    Annað raðast í stafrófsröð.
    """
    score = name_match(name, target)
    return round(score, 2) if score >= 0.75 else 0.0


def _follow_state(user, share) -> dict:
    memberships = list(Membership.objects.filter(user=user).select_related("household"))
    if any(m.household_id == share.person.household_id for m in memberships):
        return {"state": "own"}  # heimilið sem deildi listanum
    if not memberships:
        return {"state": "no_household"}
    already = services.following(user, share.person)
    if already:
        return {"state": "following", "people": already}
    households = []
    for m in sorted(memberships, key=lambda m: is_sort_key(m.household.name)):
        people = Person.objects.recipients().filter(household=m.household, source__isnull=True)
        # Þeir sem passa við nafnið (Sigga, Sigga litla, Siggi) efst, bestir fyrst; hinir í stafrófsröð
        ranked = sorted(people, key=lambda p: (-_match(p.name, share.person.name), is_sort_key(p.name)))
        households.append((m.household, ranked))
    return {"state": "form", "households": households, "groups": Group.choices}


class FollowView(LoginRequiredMixin, View):
    """Dísa bætir Siggu á sitt Jólahjól (ný manneskja eða einhver sem er þegar á listanum)."""

    http_method_names = ["post"]

    def post(self, request, token):
        share = _share_or_404(token)
        membership = get_object_or_404(
            Membership.objects.select_related("household"),
            user=request.user,
            household__slug=request.POST.get("household", ""),
        )
        person = None
        pk = request.POST.get("person", "")
        if pk.isdigit():
            person = get_object_or_404(Person, pk=int(pk), household=membership.household)
        try:
            person = services.follow(
                share,
                membership.household,
                person=person,
                name=request.POST.get("name", ""),
                group=request.POST.get("group", Group.ANNAD),
            )
        except WishlistError as exc:
            messages.error(request, str(exc))
            back = reverse("gifts:list", args=[membership.household.slug])
            return redirect(f"{back}?{urlencode({'fylgja': token})}")
        _followed_message(request, person)
        return redirect("gifts:list", slug=membership.household.slug)


def _followed_message(request, person):
    messages.success(
        request,
        _(
            "„%(name)s“ er nú á listanum þínum. Þú sérð hugmyndirnar af óskalistanum á meðan þær "
            "eru hvorki keyptar né fráteknar. Hugmyndir sem þú bætir við sjást ekki hjá þeim "
            "sem deildu listanum."
        )
        % {"name": person.name},
    )


class FollowStartView(View):
    """„Bæta á minn lista“ á opna óskalistanum: vísar á gjafalista notandans, þar sem valglugginn
    opnast (?fylgja=<token>, sjá follow_popup_context).

    Ekki innskráð: innskráning eða nýskráning (kóði í tölvupósti) og svo aftur hingað.
    Enginn listi: stofna hann fyrst og svo aftur hingað.
    """

    def get(self, request, token):
        share = _share_or_404(token)
        source = share.person
        here = request.path
        if not request.user.is_authenticated:
            messages.info(
                request,
                _("Stofnaðu aðgang og listann þinn (eða skráðu þig inn) og svo getur %(name)s bæst á hann.")
                % {"name": source.name},
            )
            return redirect(f"{reverse('account_signup')}?{urlencode({'next': here})}")
        state = _follow_state(request.user, share)
        if state["state"] == "no_household":
            messages.info(
                request,
                _("Gefðu listanum þínum nafn. Svo getur %(name)s bæst við hann.") % {"name": source.name},
            )
            return redirect(f"{reverse('households:create')}?{urlencode({'next': here})}")
        if state["state"] == "own":
            return redirect("wishlists:public", token=token)
        if state["state"] == "following":
            mine = state["people"][0]
            messages.info(request, _("„%(name)s“ er nú þegar á listanum þínum.") % {"name": mine.name})
            return redirect("gifts:list", slug=mine.household.slug)
        household = _home_household(request, [h for h, _people in state["households"]])
        return redirect(f"{reverse('gifts:list', args=[household.slug])}?{urlencode({'fylgja': token})}")


def _home_household(request, households):
    """Heimilið sem notandinn notaði síðast (eins og forsíðan), annars það fyrsta."""
    last = request.session.get(SESSION_KEY)
    return next((h for h in households if h.slug == last), households[0])


def follow_popup_context(request, household) -> dict | None:
    """Valglugginn á gjafalistanum þegar komið er af „Bæta á minn lista“ (?fylgja=<token>).

    Heimilið sem er opið er fyrst í valinu. None ef ekkert á að opnast.
    """
    token = request.GET.get("fylgja", "")
    if not token or not request.user.is_authenticated:
        return None
    share = services.get_active(token)
    if share is None:
        return None
    state = _follow_state(request.user, share)
    if state["state"] != "form":
        return None
    state["households"].sort(key=lambda hp: hp[0].pk != household.pk)
    return {"share": share, "source": share.person, "follow": {**state, **_owners(share)}}


@method_decorator(ratelimit(key="ip", rate="30/h", method="POST", block=False), name="post")
class ReserveView(View):
    """„Ég kaupi þetta“: nafn er skylda; nafnið verður gefandi á hugmyndinni."""

    def post(self, request, token, idea_id):
        share = _share_or_404(token)
        response = redirect("wishlists:public", token=token)
        if getattr(request, "limited", False):
            messages.error(request, _("Of margar beiðnir í einu. Reyndu aftur eftir smá stund."))
            return response
        name = request.POST.get("name", "")
        try:
            reservation = services.reserve(share, idea_id, name)
        except WishlistError as exc:
            messages.error(request, str(exc))
            return response
        mine = _reservations(request)
        mine[str(reservation.idea_id)] = {"s": reservation.secret, "g": reservation.added_giver}
        _set_cookie(response, COOKIE, json.dumps(mine))
        _set_cookie(response, NAME_COOKIE, name.strip()[:100])
        messages.success(request, _("Takk! Þetta er frátekið á þitt nafn."))
        return response


class CancelView(View):
    """Hætta við frátekningu, aðeins frá sama tæki (leyndarmál í undirrituðu cookie)."""

    def post(self, request, token, idea_id):
        share = _share_or_404(token)
        response = redirect("wishlists:public", token=token)
        mine = _reservations(request)
        entry = mine.pop(str(idea_id), None)
        if entry is None:
            messages.error(request, _("Þú tókst þetta ekki frá í þessu tæki."))
            return response
        try:
            services.cancel(share, Reservation(idea_id, entry["s"], bool(entry.get("g"))))
            messages.success(request, _("Frátekningin var felld niður."))
        except WishlistError as exc:
            messages.error(request, str(exc))
        _set_cookie(response, COOKIE, json.dumps(mine))
        return response


# ---------- Heimilið: búa til og afturkalla hlekk (í einstaklingsglugganum) ----------


class _ShareSection(HouseholdMixin, View):
    http_method_names = ["post"]

    def section(self, person):
        ctx = {
            "household": self.household,
            "person": person,
            "share": services.active_share(person),
            "followers": services.follower_names(person),
        }
        return HttpResponse(render_to_string("wishlists/partials/share.html", ctx, request=self.request))

    def get_person(self, pk):
        return get_object_or_404(Person, pk=pk, household=self.household)


class ShareCreateView(_ShareSection):
    def post(self, request, slug, pk):
        person = self.get_person(pk)
        services.create_share(person, request.user)
        return self.section(person)


class ShareRevokeView(_ShareSection):
    def post(self, request, slug, pk):
        person = self.get_person(pk)
        services.revoke(person)
        return self.section(person)


class UnfollowView(HouseholdMixin, View):
    """„Hætta að fylgja“ í einstaklingsglugganum. Hugmyndir sem voru teknar haldast."""

    http_method_names = ["post"]

    def post(self, request, slug, pk):
        person = get_object_or_404(Person, pk=pk, household=self.household)
        services.unfollow(person)
        ctx = {"household": self.household, "person": person}
        return HttpResponse(render_to_string("wishlists/partials/follow.html", ctx, request=request))


# ---------- Óskabeiðni: einstaklingurinn skrifar sjálfur óskirnar sínar (/oskir/<token>/) ----------
#
# Sama lína og „Ég“ á gjafalistanum (gifts/partials/wish_row.html) og sami óskagluggi
# (gifts/dialogs/wish.html): „+ Hugmynd“, × og smellur á hugmynd til að bæta við lýsingu og hlekk.
# Dísa sér aðeins eigin óskir, ekki hvort þær hafa verið keyptar eða teknar frá (privacy.py).


class _WishRequestMixin:
    """Sækir virka óskabeiðni úr slóðinni; útrunninn eða lokaður hlekkur fær „virkar ekki lengur“."""

    def dispatch(self, request, token, *args, **kwargs):
        self.wish_request = services.get_request(token)
        if self.wish_request is None:
            message = _("Hlekkurinn er útrunninn eða honum hefur verið lokað. Biddu um nýjan hlekk.")
            return _private(render(request, "wishlists/gone.html", {"message": message}, status=404))
        if request.method == "POST" and getattr(request, "limited", False):
            return HttpResponse(_("Of margar beiðnir í einu. Reyndu aftur eftir smá stund."), status=429)
        return super().dispatch(request, token, *args, **kwargs)

    def context(self) -> dict:
        return {"wish_request": self.wish_request, **owners_context(self.wish_request.person.household)}

    def row(self, status=200) -> HttpResponse:
        ctx = {**self.context(), "row": services.wish_row(self.wish_request)}
        html = render_to_string("gifts/partials/wish_row.html", ctx, request=self.request)
        return _private(HttpResponse(html, status=status))


@method_decorator(ratelimit(key="ip", rate="120/h", method="POST", block=False), name="dispatch")
class WishRequestView(_WishRequestMixin, View):
    """Síðan sjálf (GET) og „+ Hugmynd“ (POST, skilar línunni)."""

    def get(self, request, token):
        ctx = {
            **self.context(),
            "person": self.wish_request.person,
            "row": services.wish_row(self.wish_request),
            "year": services.christmas_year(),
        }
        return _private(render(request, "wishlists/request.html", ctx))

    def post(self, request, token):
        services.add_wishes(self.wish_request, request.POST.get("text", ""))
        return self.row()


@method_decorator(ratelimit(key="ip", rate="120/h", method="POST", block=False), name="dispatch")
class WishEditView(_WishRequestMixin, View):
    """Óskaglugginn: texti, nánari lýsing og hlekkur."""

    def dialog(self, idea, form, status=200):
        ctx = {**self.context(), "idea": idea, "form": form}
        return _private(render(self.request, "gifts/dialogs/wish.html", ctx, status=status))

    def get(self, request, token, idea_id):
        idea = self.get_wish(idea_id)
        return self.dialog(idea, WishForm.for_idea(idea))

    def post(self, request, token, idea_id):
        idea = self.get_wish(idea_id)
        form = WishForm(request.POST)
        if not form.is_valid():
            return self.dialog(idea, form, status=422)
        save_wish(idea, **form.cleaned_data)
        response = self.row()
        response["HX-Retarget"] = "#wish-row"
        response["HX-Reswap"] = "outerHTML"
        trigger_client_event(response, "closeModal", after="settle")
        return response

    def get_wish(self, idea_id):
        try:
            return services.own_wish(self.wish_request, idea_id)
        except WishlistError as exc:
            raise Http404 from exc


@method_decorator(ratelimit(key="ip", rate="120/h", method="POST", block=False), name="dispatch")
class WishStoreView(_WishRequestMixin, View):
    """„+ Búð“ á línunni, eins og á gjafalistanum."""

    http_method_names = ["post"]

    def post(self, request, token, idea_id):
        with contextlib.suppress(WishlistError):  # óskin farin: línan sýnir stöðuna eins og hún er
            services.set_store(self.wish_request, idea_id, request.POST.get("store", ""))
        return self.row()


@method_decorator(ratelimit(key="ip", rate="120/h", method="POST", block=False), name="dispatch")
class WishDeleteView(_WishRequestMixin, View):
    http_method_names = ["post"]

    def post(self, request, token, idea_id):
        # Þegar farin (t.d. tvísmellt): línan sýnir stöðuna eins og hún er
        with contextlib.suppress(WishlistError):
            services.delete_wish(self.wish_request, idea_id)
        return self.row()


# ---------- Heimilið: búa til og loka óskabeiðni (í einstaklingsglugganum) ----------


def request_context(person) -> dict:
    """Óskabeiðnin í einstaklingsglugganum. Ekki fyrir notendur heimilisins: þeir skrá sjálfir."""
    from apps.gifts.services.privacy import is_linked

    return {
        "can_request": not is_linked(person),
        "wish_request": services.active_request(person),
        "lifetimes": [(key, label) for key, (_days, label) in services.LIFETIMES.items()],
        "default_lifetime": services.DEFAULT_LIFETIME,
    }


class _RequestSection(HouseholdMixin, View):
    http_method_names = ["post"]

    def get_person(self, pk):
        from apps.gifts.services.privacy import is_linked

        person = get_object_or_404(Person, pk=pk, household=self.household)
        if is_linked(person):  # notendur heimilisins skrá sjálfir
            raise Http404
        return person

    def section(self, person):
        ctx = {"household": self.household, "person": person, **request_context(person)}
        return HttpResponse(render_to_string("wishlists/partials/request.html", ctx, request=self.request))


class RequestCreateView(_RequestSection):
    def post(self, request, slug, pk):
        person = self.get_person(pk)
        # Óþekkt gildi fær sjálfgefinn tíma (services.expiry)
        services.create_request(person, request.user, request.POST.get("lifetime", ""))
        return self.section(person)


class RequestRevokeView(_RequestSection):
    def post(self, request, slug, pk):
        person = self.get_person(pk)
        services.revoke_request(person)
        return self.section(person)
