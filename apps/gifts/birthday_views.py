"""Afmælisgjafir: síðan (næstu 12 mánuðir), aðgerðir á afmæliskorti, hugmyndabanki og áminningar.

Aðgerðir á korti (hugmynd, áætlun, keypt) sjá til þess að afmælisgjöfin sé til og nota svo
sömu views og jólalistinn, svo reglurnar (verðgluggi, +upphæð …) eru þær sömu.
"""

from django import forms
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from django.views import View
from django.views.generic import TemplateView

from apps.core.text import fold_key

from . import idea_bank
from .forms import BirthdayField, _text
from .models import Group, Person
from .services import birthdays
from .services import people as people_services
from .services.gifts import add_ideas
from .views import GiftBoughtView, GiftPlanView, GiftsMixin, IdeaAddView

FILTERS = {"allt": _l("Allt"), "eftir": _l("Ókeypt"), "keypt": _l("Keypt")}
MONTHS = ["jan", "feb", "mar", "apr", "maí", "jún", "júl", "ágú", "sep", "okt", "nóv", "des"]
MONTH_NAMES = [
    "Janúar", "Febrúar", "Mars", "Apríl", "Maí", "Júní",
    "Júlí", "Ágúst", "September", "Október", "Nóvember", "Desember",
]  # fmt: skip
REMINDER_CHOICES = [3, 7, 14, 30]


def _matches(entry, state: str, q: str) -> bool:
    if state == "eftir" and entry.bought or state == "keypt" and not entry.bought:
        return False
    if q:
        values = (
            [entry.person.name, *(i.text for i in entry.gift.ideas.all())]
            if entry.gift
            else [entry.person.name]
        )
        return any(fold_key(q) in fold_key(v) for v in values)
    return True


class BirthdaysView(GiftsMixin, TemplateView):
    template_name = "gifts/birthdays.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ov = birthdays.overview(self.household)
        state = self.request.GET.get("syna", "allt")
        state = state if state in FILTERS else "allt"
        q = (self.request.GET.get("leit") or "").strip()[:100]
        shown = [(month, [e for e in month.entries if _matches(e, state, q)]) for month in ov.months]
        dist = birthdays.distribution(self.household)
        peak = max(dist)
        fill_h = round(130 * ov.progress, 1)
        ctx.update(
            page_name="afmaeli",
            ov=ov,
            pills=[
                (m, MONTHS[m.month - 1] + (f" {m.year}" if i == 12 else "")) for i, m in enumerate(ov.months)
            ],
            sections=[
                (m, f"{MONTH_NAMES[m.month - 1]} {m.year}", entries) for m, entries in shown if entries
            ],
            filters=FILTERS,
            state=state,
            q=q,
            counts={
                "allt": ov.count,
                "eftir": sum(not e.bought for e in ov.entries),
                "keypt": ov.done,
            },
            distribution=[_bar(i, n, peak, ov.today.month) for i, n in enumerate(dist)],
            busiest=[MONTH_NAMES[i] for i, n in enumerate(dist) if peak and n == peak],
            bank=list(enumerate(idea_bank.IDEAS)),
            box={"y": round(190 - fill_h, 1), "h": fill_h, "line": 0 < ov.progress < 1},
            reminder_choices=REMINDER_CHOICES,
        )
        return ctx


def _bar(i: int, n: int, peak: int, this_month: int) -> dict:
    """Ein súla í afmælisdreifingu (svg 280x90, súlur allt að 70 há)."""
    h = max(round(70 * n / peak) if peak else 0, 3)
    current, top = i + 1 == this_month, bool(peak) and n == peak
    return {
        "x": 5 + 23 * i,
        "label_x": 13 + 23 * i,
        "y": 80 - h,
        "h": h,
        "fill": "#704b23" if current else "#3f6653" if top else "#e6dccf" if n else "#ebe8e2",
        "title": f"{MONTH_NAMES[i]}: {n}",
        "letter": MONTHS[i][0].upper(),
        "current": current,
    }


class BirthdayActionView(GiftsMixin, View):
    """Aðgerð á afmæliskorti: tryggir afmælisgjöfina og notar svo view jólalistans."""

    TARGETS = {"hugmynd": IdeaAddView, "aaetlun": GiftPlanView, "keypt": GiftBoughtView}
    http_method_names = ["post"]

    def post(self, request, slug, person, year, action):
        person = get_object_or_404(Person, pk=person, household=self.household)
        today = timezone.localdate()
        if action not in self.TARGETS or year not in (today.year, today.year + 1):
            return self.http_method_not_allowed(request)
        gift = birthdays.ensure_gift(person, year)
        return self.TARGETS[action].as_view()(request, slug=slug, pk=gift.pk)


def _upcoming_choices(household):
    return [(f"{e.person.pk}-{e.date.year}", e) for e in birthdays.overview(household).entries]


class BankAddView(GiftsMixin, View):
    """Hugmyndabanki: bæta almennri hugmynd við hjá einhverjum sem á afmæli framundan."""

    template = "gifts/dialogs/bank.html"

    def get(self, request, slug, index):
        if not 0 <= index < len(idea_bank.IDEAS):
            return self.http_method_not_allowed(request)
        ctx = {"index": index, "idea": idea_bank.IDEAS[index], "choices": _upcoming_choices(self.household)}
        return self.dialog(self.template, ctx)

    def post(self, request, slug, index):
        if not 0 <= index < len(idea_bank.IDEAS):
            return self.http_method_not_allowed(request)
        choices = dict(_upcoming_choices(self.household))
        entry = choices.get(request.POST.get("who", ""))
        if entry is None:
            ctx = {
                "index": index,
                "idea": idea_bank.IDEAS[index],
                "choices": list(choices.items()),
                "error": _("Veldu hvern hugmyndin er fyrir."),
            }
            return self.dialog(self.template, ctx, status=422)
        gift = birthdays.ensure_gift(entry.person, entry.date.year)
        add_ideas(gift, str(idea_bank.IDEAS[index][1]))
        return self.changed(gift.season)


class BirthdayAddView(GiftsMixin, View):
    """„Bæta við afmæli“: nafn og fæðingardagur; einstaklingurinn merktur „Gef afmælisgjafir“."""

    template = "gifts/dialogs/birthday_add.html"

    class Form(forms.Form):
        name = _text(_("Nafn"), _("t.d. Hugi, Mamma eða Frænka…"), max_length=100)
        birthday = BirthdayField(label=_("Fæðingardagur"), required=True)

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.fields["name"].widget.attrs.update({"list": "people-list", "autofocus": True})

    def render(self, form, status=200):
        people = Person.objects.filter(household=self.household).order_by("name")
        return self.dialog(self.template, {"form": form, "all_people": people}, status=status)

    def get(self, request, slug):
        return self.render(self.Form())

    def post(self, request, slug):
        form = self.Form(request.POST)
        if not form.is_valid():
            return self.render(form, status=422)
        person = people_services.find_or_create(self.household, form.cleaned_data["name"], Group.ANNAD)
        person.birthday = form.cleaned_data["birthday"]
        person.give_birthday = True
        person.save(update_fields=["birthday", "give_birthday"])
        return self.changed(None)


class ReminderSettingsView(GiftsMixin, View):
    """Afmælisáminningar í tölvupósti: af/á og hve mörgum dögum fyrir."""

    http_method_names = ["post"]

    def post(self, request, slug):
        household = self.household
        household.birthday_reminders = bool(request.POST.get("enabled"))
        try:
            days = int(request.POST.get("days", household.reminder_days))
        except ValueError:
            days = household.reminder_days
        household.reminder_days = days if days in REMINDER_CHOICES else 14
        household.save(update_fields=["birthday_reminders", "reminder_days"])
        return self.changed(None)
