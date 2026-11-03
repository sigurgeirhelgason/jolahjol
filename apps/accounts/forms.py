from allauth.account.forms import RequestLoginCodeForm
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
