from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.text import normalize


class HouseholdForm(forms.Form):
    name = forms.CharField(
        label=_("Nafn heimilis"),
        max_length=100,
        widget=forms.TextInput(attrs={"placeholder": _("t.d. Heimilið á Þórsgötu"), "autocomplete": "off"}),
    )


class OnboardingForm(HouseholdForm):
    your_name = forms.CharField(
        label=_("Hvað heitir þú?"),
        max_length=150,
        required=False,
        help_text=_("Sést hjá öðrum í heimilinu"),
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )


class DeleteHouseholdForm(forms.Form):
    confirm = forms.CharField(label=_("Skrifaðu nafn heimilisins til að staðfesta"), max_length=100)

    def __init__(self, *args, household, **kwargs):
        self.household = household
        super().__init__(*args, **kwargs)

    def clean_confirm(self):
        value = self.cleaned_data["confirm"]
        if normalize(value) != normalize(self.household.name):
            raise forms.ValidationError(_("Nafnið passar ekki."))
        return value
