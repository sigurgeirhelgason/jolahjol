from urllib.parse import urlsplit

from allauth.account import forms as allauth_forms
from allauth.account.forms import LoginForm
from django.db import transaction
from django.urls import Resolver404, resolve
from django.utils.translation import gettext_lazy as _

from apps.households import services as household_services
from apps.households.forms import OnboardingForm

PASSWORD_HELP = _("Minnst 8 stafir, ekki bara tölustafir og ekki algengt lykilorð.")


def joins_by_invite(next_url: str | None) -> bool:
    """Á leið að þiggja boð (?next=/bod/…): þá bætist fólk í heimili og stofnar ekki nýtt."""
    if not next_url:
        return False
    try:
        # get_next_redirect_url hefur þegar hafnað öðrum vefjum; hér skiptir bara slóðin máli
        return resolve(urlsplit(next_url).path).view_name == "households:invite_accept"
    except Resolver404:
        return False


class SignupForm(allauth_forms.SignupForm):
    """Nýskráning í einu skrefi: heimili, nafn, netfang og lykilorð.

    Sá sem kemur af boðshlekk (`joining`) fær ekki heimilisreitinn; hann bætist í heimilið á
    boðssíðunni strax á eftir. Netfangið er ekki staðfest með pósti (sjá ACCOUNT_EMAIL_VERIFICATION).
    """

    name = OnboardingForm.base_fields["name"]
    your_name = OnboardingForm.base_fields["your_name"]

    def __init__(self, *args, joining: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.joining = joining
        if joining:
            del self.fields["name"]
            self.fields["your_name"].help_text = ""
        email = self.fields["email"]
        email.label = _("Netfang")
        email.widget.attrs.update({"placeholder": _("netfang@dæmi.is"), "autocomplete": "email"})
        email.widget.attrs["autofocus"] = True
        password = self.fields["password1"]
        password.label = _("Lykilorð")
        password.help_text = PASSWORD_HELP
        password.widget.attrs["placeholder"] = ""
        order = ["email", "password1", "your_name", "name"]
        self.order_fields([f for f in order if f in self.fields])

    @transaction.atomic
    def save(self, request):
        user = super().save(request)
        your_name = self.cleaned_data["your_name"]
        if self.joining:
            household_services.save_user_name(user, your_name)
        else:
            household_services.create_household(user, self.cleaned_data["name"], your_name)
        return user


class PasswordLoginForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["login"].label = _("Netfang")
        self.fields["login"].widget.attrs.update(
            {"placeholder": _("netfang@dæmi.is"), "autocomplete": "email", "autofocus": True}
        )
        password = self.fields["password"]
        password.label = _("Lykilorð")
        password.help_text = ""  # „Týnt lykilorð?“ er tengill í sniðmátinu
        password.widget.attrs["placeholder"] = ""


class _NewPasswordMixin:
    """Einn reitur fyrir nýtt lykilorð, ekki tveir: gleymist það er „Týnt lykilorð“ til taks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields["password2"]
        password = self.fields["password1"]
        password.label = _("Lykilorð")
        password.widget.attrs.update({"placeholder": "", "autofocus": True})
        password.help_text = PASSWORD_HELP


class SetPasswordForm(_NewPasswordMixin, allauth_forms.SetPasswordForm):
    """Fyrir þá sem eiga ekkert lykilorð (komu inn með Google)."""


class ChangePasswordForm(_NewPasswordMixin, allauth_forms.ChangePasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        old = self.fields["oldpassword"]
        old.label = _("Núverandi lykilorð")
        old.widget.attrs.update({"placeholder": "", "autofocus": True})
        self.fields["password1"].label = _("Nýtt lykilorð")
        self.fields["password1"].widget.attrs.pop("autofocus", None)


class ResetPasswordForm(allauth_forms.ResetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].label = _("Netfang")
        self.fields["email"].widget.attrs.update(
            {"placeholder": _("netfang@dæmi.is"), "autocomplete": "email", "autofocus": True}
        )


class ResetPasswordKeyForm(_NewPasswordMixin, allauth_forms.ResetPasswordKeyForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = _("Nýtt lykilorð")
