"""Gjafalistinn.

Tvær gerðir svara við breytingum:
- Breyting í línu (keypt, áætlun, hugmynd bætt við/fjarlægð) skilar línunni sjálfri og
  uppfærir yfirlit, haus flokksins og síuflipa með hx-swap-oob.
- Vistun í glugga, eyðing og endurheimt teikna listann allan upp á nýtt og loka glugganum.
"""

import json
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views import View
from django.views.generic import TemplateView
from django_htmx.http import HttpResponseClientRedirect, HttpResponseClientRefresh, trigger_client_event

from apps.core.money import evaluate_amount
from apps.core.text import fold_key, is_sort_key, split_list
from apps.households.mixins import HouseholdMixin, OwnerRequiredMixin
from apps.wishlists import services as wishlist_services

from . import listing
from .forms import BudgetForm, GiftForm, IdeaForm, NewRowForm, NewSeasonForm, PersonEditForm, PriceForm
from .listing import ListState
from .models import Gift, Group, Idea, IdeaGiver, Person, Season, Store
from .services import gifts as gift_services
from .services import people as people_services
from .services import shopping
from .services import stores as stores_services
from .services.billing import bill_text, mark_all_paid, season_billing
from .services.gifts import needs_price
from .services.queries import season_gifts
from .services.seasons import delete_season, history, new_season
from .services.summary import days_until_christmas

LIST = "gifts/list.html"
UNLOCK_FOR = timedelta(hours=1)


# Sumir hlutar eru sér skrár (include); hinir eru partialdef í list.html
_FILES = {
    "gift_row": "gifts/partials/gift_row.html",
    "group_head": "gifts/partials/group_head.html",
    "summary": "gifts/partials/summary.html",
    "toast": "gifts/partials/toast.html",
}
PAGES = {"listi": "season", "budir": "shop", "folk": "people", "rukkun": "billing", "afmaeli": "birthdays"}


def _partial(request, name: str, ctx: dict) -> str:
    return render_to_string(_FILES.get(name, f"{LIST}#{name}"), ctx, request=request)


class GiftsMixin(HouseholdMixin):
    """Heimili úr slóð (HouseholdMixin) + jólaár, gjöf eða hugmynd innan þess."""

    def get_season(self, year: int) -> Season:
        return get_object_or_404(Season, household=self.household, year=year)

    def get_gift(self, pk: int) -> Gift:
        qs = Gift.objects.alive().select_related("season", "person")
        return get_object_or_404(qs, pk=pk, season__household=self.household)

    def get_idea(self, pk: int) -> Idea:
        qs = Idea.objects.select_related("gift__season", "gift__person")
        idea = get_object_or_404(qs, pk=pk, gift__season__household=self.household)
        if idea.gift.deleted_at:
            raise Http404
        return idea

    def ensure_editable(self, season: Season) -> None:
        """Liðin jól eru læst; viðmótið sýnir ekki breytingarhnappa en þjónninn ver líka."""
        if season.is_locked():
            raise PermissionDenied

    def page_name(self) -> str:
        """Síðan sem beiðnin kom frá (X-Page úr <body data-page>); gluggar eru opnaðir af mörgum síðum."""
        page = self.request.headers.get("X-Page", "listi")
        return page if page in PAGES else "listi"

    def changed(self, season: Season | None, *, toast=None) -> HttpResponse:
        """Svar eftir vistun: listinn teiknaður upp á nýtt, eða öll síðan ef hún er önnur en listinn."""
        if season is not None and self.page_name() == "listi":
            return self.refresh_list(season, toast=toast)
        response = HttpResponse("")
        response["HX-Reswap"] = "none"
        trigger_client_event(response, "closeModal", after="receive")
        trigger_client_event(response, "refreshPage", after="receive")
        return response

    def list_state(self) -> ListState:
        params = self.request.POST if self.request.method == "POST" else self.request.GET
        return ListState.from_params(params)

    # ---------- Context ----------

    def base_context(self, season: Season, gift_list=None) -> dict:
        gl = gift_list or listing.build_list(season, self.list_state())
        return {
            "household": self.household,
            "season": season,
            "gl": gl,
            "summary": gl.summary,
            "state": gl.state,
            "locked": gl.locked,
            "tree": listing.Tree(gl.summary.progress),
            "group_short": listing.GROUP_SHORT,
            "pace": listing.pace_text(gl.summary),
            "dash_note": listing.dash_note(gl.summary),
            "filters": listing.FILTERS,
            "sorts": listing.SORTS,
            # Fall: aðeins sótt þegar öll síðan er teiknuð (tillögur í búðarreit hugmyndar)
            "row_store_names": lambda: sorted(
                Store.objects.filter(household=self.household).values_list("name", flat=True), key=is_sort_key
            ),
        }

    # ---------- Svör ----------

    def refresh_list(self, season: Season, *, close_modal=True, toast=None) -> HttpResponse:
        """Allur listinn upp á nýtt (#sections) + yfirlit, síur og búðaval."""
        ctx = self.base_context(season)
        html = _partial(self.request, "sections", ctx)
        ctx["oob"] = True  # eftir sections, annars fengju línurnar inni í listanum hx-swap-oob
        for name in ("summary", "filter_tabs", "store_select"):
            html += _partial(self.request, name, ctx)
        if toast:
            html += _partial(self.request, "toast", {**ctx, **toast})
        response = HttpResponse(html)
        response["HX-Retarget"] = "#sections"
        response["HX-Reswap"] = "outerHTML"
        if close_modal:
            trigger_client_event(response, "closeModal", after="settle")
        return response

    def row_html(self, gift: Gift, oob=False) -> str:
        ctx = self.base_context(gift.season)
        section = ctx["gl"].section(gift.person.group)
        row = next((r for r in section.rows if r.gift.pk == gift.pk), None) if section else None
        return _partial(self.request, "gift_row", {**ctx, "row": row, "oob": oob}) if row else ""

    def row_response(self, gift: Gift, extra: str = "") -> HttpResponse:
        """Ein lína + OOB: yfirlit, haus flokksins og síuflipar.

        Ef línan passar ekki lengur við síuna (t.d. „Eftir að kaupa“ og hún var keypt) hverfur hún.
        """
        season = gift.season
        ctx = self.base_context(season)
        section = ctx["gl"].section(gift.person.group)
        row = next((r for r in section.rows if r.gift.pk == gift.pk), None) if section else None
        html = _partial(self.request, "gift_row", {**ctx, "row": row}) if row else ""
        ctx["oob"] = True
        if section:
            html += _partial(self.request, "group_head", {**ctx, "section": section})
        html += _partial(self.request, "summary", ctx) + _partial(self.request, "filter_tabs", ctx)
        return HttpResponse(html + extra)

    def dialog(self, template: str, ctx: dict, status=200) -> HttpResponse:
        ctx = {"household": self.household, **ctx}
        return HttpResponse(render_to_string(template, ctx, request=self.request), status=status)


# ---------- Listinn ----------


class SeasonRedirectView(GiftsMixin, View):
    """/h/<slug>/ (eða /h/<slug>/budir/ …) → sama síða á ári þessa árs ef það er til, annars
    nýjasta. Fyrsta heimsókn stofnar árið."""

    target = "season"

    def get(self, request, slug):
        this_year = timezone.localdate().year
        seasons = self.household.seasons.all()
        season = seasons.filter(year=this_year).first() or seasons.order_by("-year").first()
        if season is None:
            season = Season.objects.create(household=self.household, year=this_year)
        return redirect(f"gifts:{self.target}", slug=slug, year=season.year)


class SeasonPageMixin(GiftsMixin):
    """Síður jólaárs: hetjuhluti með ársvali (sem heldur sömu síðu), borði og yfirlit."""

    page = "listi"

    def season_context(self, season: Season) -> dict:
        ctx = self.base_context(season)
        days = days_until_christmas(season.year)
        ctx["hero_pill"], ctx["hero_strong"], ctx["hero_rest"] = listing.hero_texts(season, days)
        url_name = f"gifts:{PAGES[self.page]}"
        ctx["year_urls"] = [
            (s, reverse(url_name, args=[self.household.slug, s.year]))
            for s in self.household.seasons.order_by("-year")
        ]
        ctx["page_name"] = self.page
        return ctx


class GiftListView(SeasonPageMixin, TemplateView):
    template_name = LIST

    def get(self, request, *args, **kwargs):
        self.season = self.get_season(kwargs["year"])
        htmx = request.htmx
        if htmx and not htmx.history_restore_request and htmx.target == "sections":
            ctx = self.base_context(self.season)
            html = _partial(request, "sections", ctx)
            ctx["oob"] = True
            html += _partial(request, "filter_tabs", ctx)
            return HttpResponse(html)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(self.season_context(self.season))
        return ctx


class ShopView(SeasonPageMixin, TemplateView):
    """Verslanir: ókeyptar gjafir eftir búð, eða eftir staðsetningu búðanna."""

    template_name = "gifts/shop.html"
    page = "budir"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        season = self.get_season(kwargs["year"])
        ctx.update(self.season_context(season))
        by_location = self.request.GET.get("eftir") == "stadsetningu"
        gifts = season_gifts(season)
        ctx["by_location"] = by_location
        if by_location:
            ctx["location_groups"] = groups = shopping.by_location(season, gifts)
        else:
            ctx["store_groups"] = groups = shopping.by_store(season, gifts)
        ctx["any_left"] = bool(groups)
        return ctx


class PeopleView(SeasonPageMixin, TemplateView):
    """Fólk & Fjölskylda: allir eftir flokkum, með afmæli og keyptum gjöfum fyrri ára."""

    template_name = "gifts/people.html"
    page = "folk"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        season = self.get_season(kwargs["year"])
        ctx.update(self.season_context(season))
        everyone = people_services.for_people_page(self.household)
        hist = listing.histories_bought(self.household, [p.pk for p in everyone])
        groups = []
        for value, label in Group.choices:
            members = sorted((p for p in everyone if p.group == value), key=lambda p: is_sort_key(p.name))
            if members:
                groups.append((value, label, [(p, hist.get(p.pk, [])) for p in members]))
        ctx["people_groups"] = groups
        ctx["group_choices"] = Group.choices
        return ctx


class BillingView(SeasonPageMixin, TemplateView):
    """Rukkun: hverja þarf að rukka, fyrir hvað og hve mikið."""

    template_name = "gifts/billing.html"
    page = "rukkun"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        season = self.get_season(kwargs["year"])
        ctx.update(self.season_context(season))
        payers = season_billing(season, season_gifts(season))
        ctx["payers"] = [(p, bill_text(p, season.year)) for p in payers]
        due = [p for p in payers if p.unpaid_lines]
        ctx["due_count"] = len(due)
        ctx["due_total"] = sum(p.unpaid for p in due)
        return ctx


class GiverPaidView(GiftsMixin, View):
    """Rukkun: „Greitt“ fyrir einn gefanda á einni hugmynd. Leyft líka á læstu ári (eins og áður)."""

    def post(self, request, slug, pk):
        link = get_object_or_404(
            IdeaGiver.objects.select_related("idea__gift__season"),
            pk=pk,
            idea__gift__season__household=self.household,
            idea__gift__deleted_at__isnull=True,
        )
        link.paid = bool(request.POST.get("paid"))
        link.save(update_fields=["paid"])
        return self.changed(link.idea.gift.season)


class PayerAllPaidView(GiftsMixin, View):
    """Rukkun: „Merkja allt greitt“ fyrir einn gefanda á árinu."""

    def post(self, request, slug, year, pk):
        season = self.get_season(year)
        person = get_object_or_404(Person, pk=pk, household=self.household)
        mark_all_paid(season, person)
        return self.changed(season)


class PersonGroupView(GiftsMixin, View):
    """Fólk: flokki breytt beint í listanum."""

    def post(self, request, slug, pk):
        person = get_object_or_404(Person, pk=pk, household=self.household)
        group = request.POST.get("group")
        if group in Group.values:
            person.group = group
            person.save(update_fields=["group"])
        return self.changed(None)


class BudgetView(GiftsMixin, View):
    def post(self, request, slug, year):
        season = self.get_season(year)
        self.ensure_editable(season)
        form = BudgetForm(request.POST)
        if form.is_valid():
            season.budget = form.cleaned_data["budget"]
            season.save(update_fields=["budget"])
        ctx = self.base_context(season)
        return HttpResponse(_partial(request, "summary", ctx))


class UnlockView(GiftsMixin, View):
    def post(self, request, slug, year):
        season = self.get_season(year)
        season.unlocked_until = timezone.now() + UNLOCK_FOR
        season.save(update_fields=["unlocked_until"])
        return HttpResponseClientRefresh()


class NewSeasonView(GiftsMixin, View):
    template = "gifts/dialogs/new_season.html"

    def latest(self):
        return self.household.seasons.order_by("-year").first()

    def get(self, request, slug):
        latest = self.latest()
        return self.dialog(self.template, {"form": NewSeasonForm(latest=latest), "latest": latest})

    def post(self, request, slug):
        latest = self.latest()
        form = NewSeasonForm(request.POST, latest=latest)
        if not form.is_valid():
            return self.dialog(self.template, {"form": form, "latest": latest}, status=422)
        year = form.cleaned_data["year"]
        # Afritað frá árinu á undan því nýja, aldrei frá seinna ári (2025 fær ekki fólk úr 2026)
        previous = self.household.seasons.filter(year__lt=year).order_by("-year").first()
        new_season(self.household, year, copy_from=previous if form.cleaned_data["copy"] else None)
        return HttpResponseClientRedirect(reverse("gifts:season", args=[slug, year]))


class SeasonDeleteView(OwnerRequiredMixin, View):
    """Eyða jólaári (stillingasíða heimilis). Aðeins eigendur."""

    http_method_names = ["post"]

    def post(self, request, slug, year):
        season = get_object_or_404(Season, household=self.household, year=year)
        count = delete_season(season)
        messages.success(
            request,
            ngettext(
                "Jólum %(year)s og %(n)s gjöf var eytt.", "Jólum %(year)s og %(n)s gjöfum var eytt.", count
            )
            % {"year": year, "n": count},
        )
        return redirect("households:settings", slug=slug)


# ---------- Gjafir: breytingar í línu ----------


class GiftBoughtView(GiftsMixin, View):
    """Gátreiturinn „Keypt“. Án verðs spyr glugginn hvað gjöfin kostaði (eins og `askPrice`)."""

    def post(self, request, slug, pk):
        gift = self.get_gift(pk)
        self.ensure_editable(gift.season)
        if request.POST.get("bought"):
            gift.bought = True
            if needs_price(gift):
                # Ekki vistað fyrr en verð er skráð eða sleppt: glugginn opnast og línan
                # (óbreytt, óhökuð) er send með svo gátreiturinn sýni rétta stöðu
                gift.refresh_from_db()
                response = self.dialog("gifts/dialogs/price.html", self.price_context(gift))
                if self.page_name() == "listi":
                    response.content += self.row_html(gift, oob=True).encode()
                response["HX-Retarget"] = "#modal-body"
                response["HX-Reswap"] = "innerHTML"
                return response
            gift.refresh_from_db()
            gift_services.mark_bought(gift)
        else:
            gift_services.mark_unbought(gift)
        if self.page_name() != "listi":
            return self.changed(gift.season)
        return self.row_response(gift)

    @staticmethod
    def price_context(gift, form=None):
        return {"gift": gift, "form": form or PriceForm(), "what": gift_services.gift_text(gift)}


class GiftPriceView(GiftsMixin, View):
    """Verðglugginn: skrá upphæð (bætist við) eða sleppa verði; gjöfin merkist keypt."""

    def post(self, request, slug, pk):
        gift = self.get_gift(pk)
        self.ensure_editable(gift.season)
        if request.POST.get("skip"):
            gift_services.mark_bought(gift)
        else:
            form = PriceForm(request.POST)
            if not form.is_valid():
                ctx = GiftBoughtView.price_context(gift, form)
                return self.dialog("gifts/dialogs/price.html", ctx, status=422)
            gift_services.mark_bought(gift, form.cleaned_data["amount"])
        if self.page_name() != "listi":
            return self.changed(gift.season)
        response = self.row_response(gift)
        # Formið er í glugganum, en svarið er línan sjálf
        response["HX-Retarget"] = f"#gift-{gift.pk}"
        response["HX-Reswap"] = "outerHTML"
        trigger_client_event(response, "closeModal", after="settle")
        return response


class GiftPlanView(GiftsMixin, View):
    """Áætlað verð í línu; „+2000“ bætist við núverandi áætlun."""

    def post(self, request, slug, pk):
        gift = self.get_gift(pk)
        self.ensure_editable(gift.season)
        gift.plan = evaluate_amount(request.POST.get("plan", ""), base=gift.plan)
        if gift.plan is not None and gift.plan < 0:
            gift.plan = 0
        gift.save(update_fields=["plan", "updated_at"])
        if self.page_name() != "listi":
            return self.changed(gift.season)
        return self.row_response(gift)


class IdeaAddView(GiftsMixin, View):
    def post(self, request, slug, pk):
        gift = self.get_gift(pk)
        self.ensure_editable(gift.season)
        gift_services.add_ideas(gift, request.POST.get("text", "")[:1000])
        if self.page_name() != "listi":
            return self.changed(gift.season)
        return self.row_response(gift)


class IdeaRemoveView(GiftsMixin, View):
    def post(self, request, slug, pk):
        idea = self.get_idea(pk)
        gift = idea.gift
        self.ensure_editable(gift.season)
        gift_services.remove_idea(idea)
        if self.page_name() != "listi":
            return self.changed(gift.season)
        return self.row_response(gift)


class IdeaBoughtView(GiftsMixin, View):
    """Gátreitur hugmyndar (listinn og Verslanir). Án verðs spyr glugginn hvað hún kostaði."""

    def post(self, request, slug, pk):
        idea = self.get_idea(pk)
        gift = idea.gift
        self.ensure_editable(gift.season)
        if not request.POST.get("bought"):
            gift_services.unpick_idea(idea)
        elif idea.price is None:
            response = self.dialog("gifts/dialogs/price.html", self.price_context(idea))
            if self.page_name() == "listi":
                # Ekki vistað fyrr en verð er skráð eða sleppt: línan (óhökuð) fylgir með
                response.content += self.row_html(gift, oob=True).encode()
            response["HX-Retarget"] = "#modal-body"
            response["HX-Reswap"] = "innerHTML"
            return response
        else:
            gift_services.pick_idea(idea)
        return self.after_change(gift)

    def after_change(self, gift):
        if self.page_name() != "listi":
            return self.changed(gift.season)
        response = self.row_response(gift)
        response["HX-Retarget"] = f"#gift-{gift.pk}"
        response["HX-Reswap"] = "outerHTML"
        trigger_client_event(response, "closeModal", after="settle")
        return response

    @staticmethod
    def price_context(idea, form=None):
        return {"gift": idea.gift, "idea": idea, "form": form or PriceForm(), "what": idea.text}


class IdeaStoreView(GiftsMixin, View):
    """Búð skráð beint í línu hugmyndar á listanum, án þess að opna hugmyndargluggann."""

    def post(self, request, slug, pk):
        idea = self.get_idea(pk)
        gift = idea.gift
        self.ensure_editable(gift.season)
        store = stores_services.get_or_create_store(self.household, request.POST.get("store", ""))
        if store:
            idea.store = store
            idea.save(update_fields=["store"])
        return self.row_response(gift)


class IdeaPriceView(IdeaBoughtView):
    """Verðglugginn fyrir hugmynd: skrá verð hennar (eða sleppa því); hún merkist keypt."""

    def post(self, request, slug, pk):
        idea = self.get_idea(pk)
        self.ensure_editable(idea.gift.season)
        if request.POST.get("skip"):
            gift_services.pick_idea(idea)
        else:
            form = PriceForm(request.POST)
            if not form.is_valid():
                ctx = IdeaBoughtView.price_context(idea, form)
                return self.dialog("gifts/dialogs/price.html", ctx, status=422)
            gift_services.pick_idea(idea, form.cleaned_data["amount"])
        return self.after_change(idea.gift)


class GiftDeleteView(GiftsMixin, View):
    def post(self, request, slug, pk):
        gift = self.get_gift(pk)
        self.ensure_editable(gift.season)
        gift_services.soft_delete(gift)
        toast = {
            "toast_text": _("Gjöf til %(name)s eytt") % {"name": gift.person.name},
            "undo_url": reverse("gifts:restore", args=[slug, gift.pk]),
        }
        return self.refresh_list(gift.season, close_modal=False, toast=toast)


class GiftRestoreView(GiftsMixin, View):
    def post(self, request, slug, pk):
        gift = get_object_or_404(
            Gift.objects.select_related("season", "person"), pk=pk, season__household=self.household
        )
        self.ensure_editable(gift.season)
        try:
            gift_services.restore(gift)
            toast = None
        except ValueError:
            text = _("Ekki hægt að endurheimta: %(name)s á aðra gjöf.") % {"name": gift.person}
            toast = {"toast_text": text}
        return self.refresh_list(gift.season, close_modal=False, toast=toast or {"toast_hide": True})


# ---------- Gluggar ----------


def _form_lists(household) -> dict:
    """Gögn í <datalist> og búðarstaðsetningar fyrir gluggana."""
    stores = list(Store.objects.filter(household=household).prefetch_related("locations").order_by("name"))
    return {
        "all_people": Person.objects.filter(household=household).order_by("name"),
        "all_stores": stores,
        "all_locations": stores_services.all_location_names(household),
        "store_locations": json.dumps(
            {s.key: ", ".join(loc.name for loc in s.locations.all()) for s in stores}, ensure_ascii=False
        ),
    }


class GiftDialogView(GiftsMixin, View):
    """Gjafaglugginn: ný gjöf (`year`) eða breyting (`pk`)."""

    template = "gifts/dialogs/gift.html"

    def setup_objects(self, kwargs):
        if "pk" in kwargs:
            self.gift = self.get_gift(kwargs["pk"])
            self.season = self.gift.season
        else:
            self.gift = None
            self.season = self.get_season(kwargs["year"])
        self.ensure_editable(self.season)

    def initial(self):
        if self.gift is None:
            return {"group": Group.FJOLSKYLDA}
        gift = self.gift
        store = gift.stores.first()
        return {
            "name": gift.person.name,
            "group": gift.person.group,
            "plan": gift.plan if gift.plan is not None else "",
            "ideas": ", ".join(i.text for i in gift.ideas.all()),
            "store": store.name if store else "",
            "link": gift.link,
        }

    def render(self, form, status=200):
        ctx = {"form": form, "gift": self.gift, "season": self.season, **_form_lists(self.household)}
        return self.dialog(self.template, ctx, status=status)

    def get(self, request, slug, **kwargs):
        self.setup_objects(kwargs)
        return self.render(GiftForm(initial=self.initial()))

    def post(self, request, slug, **kwargs):
        self.setup_objects(kwargs)
        form = GiftForm(request.POST)
        if form.is_valid():
            try:
                gift_services.save_gift(self.season, self.gift, form.to_data())
            except ValueError as exc:
                form.add_error("name", str(exc))
            else:
                return self.changed(self.season)
        return self.render(form, status=422)


class NewRowView(GiftsMixin, View):
    """„Bæta við aðila í <flokki>“: tóm lína með nafni og áætlun beint í flokknum.

    Línan verður að gjöf þegar farið er úr henni (eða Enter) með nafni; án nafns hverfur hún.
    """

    template = "gifts/partials/new_row.html"

    def render(self, season, form, status=200):
        # Útfylling: fólk sem hefur fengið gjöf önnur ár en er ekki á lista þessa árs
        on_list = season.gifts.alive().christmas().values("person_id")
        earlier = (
            Person.objects.filter(household=self.household)
            .filter(Exists(Gift.objects.alive().filter(person=OuterRef("pk"))))
            .exclude(pk__in=on_list)
        )
        ctx = {
            "form": form,
            "season": season,
            "group": form["group"].value(),
            "suggestions": sorted({p.name for p in earlier}, key=is_sort_key),
        }
        return self.dialog(self.template, ctx, status=status)

    def get(self, request, slug, year):
        season = self.get_season(year)
        self.ensure_editable(season)
        group = request.GET.get("flokkur")
        form = NewRowForm(initial={"group": group if group in Group.values else Group.ANNAD})
        return self.render(season, form)

    def post(self, request, slug, year):
        season = self.get_season(year)
        self.ensure_editable(season)
        form = NewRowForm(request.POST)
        if form.is_valid():
            try:
                person, gift = gift_services.add_person(season, form.to_data())
            except ValueError as exc:
                form.add_error("name", str(exc))
            else:
                if person.group != form.cleaned_data["group"]:
                    # Einstaklingur úr öðrum flokki (valinn úr útfyllingu): línan á heima þar
                    return self.refresh_list(season, close_modal=False)
                return self.row_response(gift)
        return self.render(season, form, status=422)


class PersonDialogView(GiftsMixin, View):
    """Smellt á nafn: nafn (gildir öll ár), flokkur, fæðingardagur, jóla- og afmælisgjafir, saga."""

    template = "gifts/dialogs/person.html"

    def get_person(self, pk):
        return get_object_or_404(Person, pk=pk, household=self.household)

    def render(self, person, form, conflict=None, status=200):
        params = self.request.POST if self.request.method == "POST" else self.request.GET
        ctx = {
            "person": person,
            "form": form,
            "conflict": conflict,
            # Fyrri gjafir: aðeins það sem var keypt (merkt „Tilbúið“), ekki hugmyndir sem urðu ekki að gjöf
            "history": [entry for entry in history(person) if entry.gift.bought],
            "share": wishlist_services.active_share(person),
            "year": params.get("ar", ""),  # árið sem listinn sýnir, svo hann uppfærist eftir vistun
        }
        return self.dialog(self.template, ctx, status=status)

    def get(self, request, slug, pk):
        person = self.get_person(pk)
        initial = {
            "name": person.name,
            "group": person.group,
            "birthday": person.birthday,
            "give_christmas": person.give_christmas,
            "give_birthday": person.give_birthday,
        }
        return self.render(person, PersonEditForm(initial=initial))

    def post(self, request, slug, pk):
        person = self.get_person(pk)
        form = PersonEditForm(request.POST)
        if not form.is_valid():
            return self.render(person, form, status=422)
        d = form.cleaned_data
        conflict = people_services.find_conflict(person, d["name"])
        if conflict and not d["merge"]:
            # Spurt fyrst, eins og `renamePerson`: „X“ er þegar til. Sameina?
            return self.render(person, form, conflict=conflict, status=422)
        with transaction.atomic():
            person = people_services.rename(person, d["name"], merge_into_existing=True)
            people_services.update_details(
                person,
                group=d["group"],
                birthday=d["birthday"],
                give_christmas=d["give_christmas"],
                give_birthday=d["give_birthday"],
            )
        season = self.household.seasons.filter(year=self.request.POST.get("ar") or 0).first()
        return self.changed(season)


class StoreDialogView(GiftsMixin, View):
    """Smellt á búð: nafn (gildir öll ár; spyr áður en sameinað er) og staðsetningar."""

    template = "gifts/dialogs/store.html"

    def get_store(self, pk):
        return get_object_or_404(Store.objects.prefetch_related("locations"), pk=pk, household=self.household)

    def render(self, store, name, chosen, new_locations="", conflict=None, error=None, status=200):
        params = self.request.POST if self.request.method == "POST" else self.request.GET
        names = stores_services.location_choices(self.household, keep=chosen)
        chosen_keys = {fold_key(n) for n in chosen}
        ctx = {
            "store": store,
            "name": name,
            "locations": [(name, fold_key(name) in chosen_keys) for name in names],
            "new_locations": new_locations,
            "conflict": conflict,
            "error": error,
            "year": params.get("ar", ""),
            "all_locations": stores_services.all_location_names(self.household),
        }
        return self.dialog(self.template, ctx, status=status)

    def get(self, request, slug, pk):
        store = self.get_store(pk)
        return self.render(store, store.name, [loc.name for loc in store.locations.all()])

    def post(self, request, slug, pk):
        store = self.get_store(pk)
        name = request.POST.get("name", "").strip()[:100]
        chosen = [n for n in request.POST.getlist("locations") if n.strip()]
        new_locations = request.POST.get("new_locations", "")[:300]
        if not name:
            return self.render(store, name, chosen, new_locations, error=_("Búðin þarf nafn."), status=422)
        conflict = stores_services.find_conflict(store, name)
        if conflict and not request.POST.get("merge"):
            # Spurt fyrst, eins og `renameStore`: „X“ er þegar til. Sameina þessar búðir?
            return self.render(store, name, chosen, new_locations, conflict=conflict, status=422)
        with transaction.atomic():
            target = stores_services.rename_or_merge(store, name)
            names = chosen + split_list(new_locations)
            if conflict:
                names += [loc.name for loc in target.locations.all()]
            stores_services.set_locations(target, split_list(", ".join(names)))
        season = self.household.seasons.filter(year=request.POST.get("ar") or 0).first()
        return self.changed(season)


class ReservationRemoveView(GiftsMixin, View):
    """Heimilið fjarlægir frátekningu af opnum óskalista (gefandinn helst á hugmyndinni)."""

    http_method_names = ["post"]

    def post(self, request, slug, pk):
        idea = self.get_idea(pk)
        wishlist_services.clear_reservation(idea)
        return self.changed(idea.gift.season)


class IdeaDialogView(GiftsMixin, View):
    template = "gifts/dialogs/idea.html"

    def render(self, idea, form, givers, status=200):
        ctx = {
            "idea": idea,
            "gift": idea.gift,
            "form": form,
            "givers_json": json.dumps(givers, ensure_ascii=False),
            **_form_lists(self.household),
        }
        return self.dialog(self.template, ctx, status=status)

    def get(self, request, slug, pk):
        idea = self.get_idea(pk)
        self.ensure_editable(idea.gift.season)
        links = list(idea.giver_links.select_related("person"))
        initial = {
            "text": idea.text,
            "for_other": idea.for_other,
            "paid": bool(links) and all(link.paid for link in links),
            "note": idea.note,
            "store": idea.store.name if idea.store else "",
            "locations": ", ".join(loc.name for loc in idea.store.locations.all()) if idea.store else "",
            "price": idea.price if idea.price is not None else "",
            "link": idea.link,
            "picked": idea.picked,
        }
        givers = [link.person.name for link in links]
        return self.render(idea, IdeaForm(initial=initial), givers)

    def post(self, request, slug, pk):
        idea = self.get_idea(pk)
        self.ensure_editable(idea.gift.season)
        form = IdeaForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                gift_services.save_idea(idea, form.to_data())
            return self.changed(idea.gift.season)
        givers = request.POST.getlist("givers")
        return self.render(idea, form, givers, status=422)


class PeopleSearchView(GiftsMixin, View):
    """Tillögur í gefendareitnum: fólk heimilisins, bæði viðtakendur og gefendur."""

    def get(self, request, slug):
        q = request.GET.get("q", "").strip()[:100]
        found = people_services.search(self.household, q) if q else []
        exists = any(fold_key(p.name) == fold_key(q) for p in found)
        from_us = q.casefold() in people_services.FROM_US
        ctx = {"people": found, "q": q, "offer_new": bool(q) and not exists and not from_us}
        return HttpResponse(render_to_string("gifts/partials/people_options.html", ctx, request=request))
