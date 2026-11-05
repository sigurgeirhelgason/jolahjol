import json

from django.conf import settings
from django.contrib import messages
from django.core.signing import BadSignature
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View
from django_ratelimit.decorators import ratelimit

from apps.gifts.models import Person
from apps.households.mixins import HouseholdMixin

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
        rows = [
            {
                "idea": i,
                "taken": services.is_taken(i),
                "mine": _is_mine(i, mine),
            }
            for i in ideas
        ]
        try:
            name = request.get_signed_cookie(NAME_COOKIE, salt=SALT, default="")
        except BadSignature:
            name = ""
        ctx = {"share": share, "person": share.person, "season": season, "rows": rows, "name": name}
        return _private(render(request, "wishlists/public.html", ctx))


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
        ctx = {"household": self.household, "person": person, "share": services.active_share(person)}
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
