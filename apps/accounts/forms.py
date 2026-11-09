from allauth.account import forms as allauth_forms
from allauth.account.forms import LoginForm, RequestLoginCodeForm
from allauth.account.models import EmailAddress
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from .models import User


class EmailCodeForm(RequestLoginCodeForm):
    """Innskráning og nýskráning í einu skrefi: netfang → kóði.

    Ef netfangið er ekki til verður aðgangurinn til hér, óstaðfestur. Kóðinn staðfestir
    netfangið (allauth `verify_email_indirectly`). Aðgangar sem aldrei skrá sig inn eru
    hreinsaðir með `manage.py prune_users`.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].label = _("Netfang")
        self.fields["email"].widget.attrs.update(
            {"placeholder": _("netfang@dæmi.is"), "autocomplete": "email", "autofocus": True}
        )

    def clean_email(self) -> str:
        # Rate limit allauth (á IP og netfang) keyrir fyrst, svo ekki er hægt að stofna aðganga í löngum bunum
        email = super().clean_email()
        if not email:
            return email
        with transaction.atomic():
            if self._user is None:
                self._user = User.objects.create_user(email=email)
            # Notendur úr admin eða import_legacy hafa enga EmailAddress-færslu; án hennar
            # staðfestir kóðinn ekki netfangið og allauth krefst sérstakrar staðfestingar.
            if not EmailAddress.objects.filter(user=self._user, email__iexact=self._user.email).exists():
                EmailAddress.objects.create(
                    user=self._user, email=self._user.email, primary=True, verified=False
                )
        return email


class PasswordLoginForm(LoginForm):
    """Innskráning með netfangi og lykilorði, fyrir þá sem hafa valið sér lykilorð."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["login"].label = _("Netfang")
        self.fields["login"].widget.attrs.update(
            {"placeholder": _("netfang@dæmi.is"), "autocomplete": "email", "autofocus": True}
        )
        password = self.fields["password"]
        password.label = _("Lykilorð")
        password.help_text = ""  # allauth vísar á endurstillingu; hér kemur kóðinn í staðinn
        password.widget.attrs["placeholder"] = ""

    def _setup_password_field(self) -> None:
        # allauth fjarlægir reitinn þegar nýskráning er án lykilorðs, sem á við hér
        pass


class _NewPasswordMixin:
    """Einn reitur fyrir nýtt lykilorð, ekki tveir: gleymist það er kóðinn alltaf til taks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields["password2"]
        password = self.fields["password1"]
        password.label = _("Lykilorð")
        password.widget.attrs.update({"placeholder": "", "autofocus": True})
        password.help_text = _("Minnst 8 stafir, ekki bara tölustafir og ekki algengt lykilorð.")


class SetPasswordForm(_NewPasswordMixin, allauth_forms.SetPasswordForm):
    pass


class ChangePasswordForm(_NewPasswordMixin, allauth_forms.SetPasswordForm):
    """Breyta lykilorði án þess að slá inn það gamla: innskráning með kóða er jafngild, og gleymt
    lykilorð á ekki að læsa notandann frá því að velja nýtt."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = _("Nýtt lykilorð")
