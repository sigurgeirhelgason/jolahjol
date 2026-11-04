from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.money import evaluate_amount
from apps.core.text import split_list

from .models import Group
from .services.gifts import GiftData, IdeaData, PersonData


class AmountField(forms.CharField):
    """Upphæð í krónum: „4.990 kr.“, „5000+2.300“. Tómt verður None."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        super().__init__(*args, **kwargs)
        self.widget.attrs.setdefault("inputmode", "numeric")
        self.widget.attrs.setdefault("autocomplete", "off")
        self.widget.attrs.setdefault("maxlength", "60")

    def to_python(self, value):
        # Ekkert max_length-validator: það keyrir á niðurstöðunni (tölu), ekki textanum
        value = super().to_python(value)[:60]
        if not value:
            return None
        amount = evaluate_amount(value)
        if amount is None:
            raise forms.ValidationError(_("Skrifaðu upphæð, t.d. 4990 eða 2500+990."))
        if amount < 0:
            raise forms.ValidationError(_("Upphæðin má ekki vera neikvæð."))
        return amount


def _text(label, placeholder="", **kwargs):
    attrs = {"autocomplete": "off"}
    if placeholder:
        attrs["placeholder"] = placeholder
    return forms.CharField(label=label, widget=forms.TextInput(attrs=attrs), **kwargs)


def _link():
    return forms.URLField(
        label=_("Hlekkur"),
        required=False,
        max_length=500,
        assume_scheme="https",
        widget=forms.URLInput(attrs={"placeholder": "https://…"}),
    )


class GiftForm(forms.Form):
    name = _text(_("Fyrir hvern er gjöfin?"), _("t.d. Hugi, Mamma eða Frænka…"), max_length=100)
    group = forms.ChoiceField(label=_("Flokkur"), choices=Group.choices, initial=Group.FJOLSKYLDA)
    plan = AmountField(label=_("Áætlað verð (kr.)"), widget=forms.TextInput(attrs={"placeholder": "5000"}))
    ideas = _text(
        _("Gjafahugmyndir"),
        _("t.d. hlýir ullarsokkar, spil"),
        required=False,
        max_length=1000,
        help_text=_("Aðskildu hugmyndir með kommu"),
    )
    store = _text(_("Búð"), _("t.d. Elko, Epal…"), required=False, max_length=100)
    link = _link()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs["list"] = "people-list"
        self.fields["store"].widget.attrs["list"] = "store-list"
        self.fields["name"].widget.attrs["autofocus"] = True

    def to_data(self) -> GiftData:
        d = self.cleaned_data
        return GiftData(
            name=d["name"].strip(),
            group=d["group"],
            plan=d["plan"],
            ideas=[t.strip() for t in d["ideas"].split(",") if t.strip()],
            store=d["store"].strip(),
            link=d["link"],
        )


class NewRowForm(forms.Form):
    """Ný lína í flokki: nafn (og áætlun). Samsvarar `addGift` í gamla appinu."""

    name = _text(_("Nafn"), _("Skrifaðu nafn"), max_length=100)
    plan = AmountField(label=_("Áætlað verð (kr.)"))
    group = forms.ChoiceField(choices=Group.choices, widget=forms.HiddenInput)

    def to_data(self) -> PersonData:
        d = self.cleaned_data
        return PersonData(
            name=d["name"].strip(), group=d["group"], birthday=None, give_christmas=True,
            give_birthday=False, plan=d["plan"], ideas=[],
        )  # fmt: skip


class PersonEditForm(forms.Form):
    """Einstaklingsglugginn (smellt á nafn). Samsvarar `personDialog`."""

    name = _text(_("Nafn"), max_length=100)
    group = forms.ChoiceField(label=_("Flokkur"), choices=Group.choices)
    birthday = forms.DateField(
        label=_("Fæðingardagur"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    give_christmas = forms.BooleanField(required=False)
    give_birthday = forms.BooleanField(required=False)
    merge = forms.BooleanField(required=False, widget=forms.HiddenInput)

    def clean_birthday(self):
        value = self.cleaned_data["birthday"]
        if value and value > timezone.localdate():
            raise forms.ValidationError(_("Fæðingardagur getur ekki verið í framtíðinni."))
        return value


class IdeaForm(forms.Form):
    text = _text(_("Hugmynd"), max_length=200)
    for_other = forms.BooleanField(required=False)
    paid = forms.BooleanField(required=False)
    note = forms.CharField(
        label=_("Nánari lýsing"),
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": _("t.d. stærð, litur, hvaða útgáfa…")}),
    )
    store = _text(_("Búð"), _("t.d. Elko, Epal…"), required=False, max_length=100)
    locations = _text(
        _("Staðsetning búðar"),
        _("t.d. Kringlan, Smáralind…"),
        required=False,
        max_length=300,
        help_text=_("Aðskildu staði með kommu"),
    )
    price = AmountField(label=_("Verð (kr.)"), widget=forms.TextInput(attrs={"placeholder": "—"}))
    link = _link()
    picked = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["store"].widget.attrs["list"] = "store-list"
        self.fields["locations"].widget.attrs["list"] = "location-list"

    def clean(self):
        cleaned = super().clean()
        # Gefendur koma úr person-picker sem endurteknir reitir: givers=Amma&givers=Afi, shares=…
        names = self.data.getlist("givers") if hasattr(self.data, "getlist") else []
        shares = self.data.getlist("shares") if hasattr(self.data, "getlist") else []
        cleaned["givers"] = [n.strip()[:100] for n in names if n.strip()]
        parsed = []
        for raw in shares[: len(names)]:
            try:
                parsed.append(AmountField().clean(raw))
            except forms.ValidationError:
                self.add_error(None, _("Hlutur gefanda þarf að vera upphæð."))
                parsed.append(None)
        cleaned["shares"] = parsed
        return cleaned

    def to_data(self) -> IdeaData:
        d = self.cleaned_data
        return IdeaData(
            text=d["text"],
            givers=d["givers"],
            shares=d["shares"],
            for_other=d["for_other"],
            paid=d["paid"],
            note=d["note"],
            store=d["store"].strip(),
            locations=", ".join(split_list(d["locations"])),
            price=d["price"],
            link=d["link"],
            picked=d["picked"],
        )


class PriceForm(forms.Form):
    amount = AmountField(
        label=_("Verð (kr.)"),
        required=True,
        widget=forms.TextInput(attrs={"placeholder": _("t.d. 4990"), "autofocus": True, "class": "big"}),
    )


class BudgetForm(forms.Form):
    budget = AmountField(required=True)


class NewSeasonForm(forms.Form):
    year = forms.IntegerField(label=_("Hvaða ár?"), min_value=2000, max_value=2100)
    copy = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, latest=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.latest = latest
        default = (latest.year + 1) if latest else timezone.localdate().year
        self.fields["year"].initial = default
