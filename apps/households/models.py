import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class HouseholdQuerySet(models.QuerySet):
    def for_member(self, user):
        """Öll aðgangsstýring fer í gegnum þetta: aðeins heimili sem notandinn er meðlimur í."""
        if not user.is_authenticated:
            return self.none()
        return self.filter(memberships__user=user)


class Household(models.Model):
    name = models.CharField(_("nafn"), max_length=100)
    slug = models.SlugField(_("slóð"), unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Afmælisáminningar í tölvupósti til meðlima (manage.py send_birthday_reminders, daglega)
    birthday_reminders = models.BooleanField(_("afmælisáminningar"), default=False)
    reminder_days = models.PositiveSmallIntegerField(_("dögum fyrir afmæli"), default=14)

    objects = HouseholdQuerySet.as_manager()

    class Meta:
        verbose_name = _("heimili")
        verbose_name_plural = _("heimili")

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", _("Eigandi")
        MEMBER = "member", _("Meðlimur")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(_("hlutverk"), max_length=10, choices=Role.choices, default=Role.MEMBER)
    # Einstaklingurinn á listanum sem notandinn er. Gjafir handa honum merktar „Fela“ sjást ekki
    # hjá notandanum (sjá apps/gifts/services/privacy.py). Aðeins eigandi breytir tengingunni.
    person = models.ForeignKey(
        "gifts.Person",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memberships",
        verbose_name=_("á listanum sem"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("aðild")
        verbose_name_plural = _("aðildir")
        constraints = [
            models.UniqueConstraint(fields=["user", "household"], name="unique_membership"),
            models.UniqueConstraint(
                fields=["person"], condition=models.Q(person__isnull=False), name="unique_member_person"
            ),
        ]

    def __str__(self):
        return f"{self.user} – {self.household}"


def _invite_token() -> str:
    return secrets.token_urlsafe(24)


def _invite_expiry():
    return timezone.now() + timedelta(days=Invite.VALID_DAYS)


class InviteQuerySet(models.QuerySet):
    def usable(self):
        return self.filter(accepted_at__isnull=True, expires_at__gt=timezone.now())


class Invite(models.Model):
    """Boð í heimili með hlekk. Gildir einu sinni og rennur út eftir VALID_DAYS daga."""

    VALID_DAYS = 7

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="invites")
    token = models.CharField(max_length=64, unique=True, default=_invite_token, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    # Hver á listanum fær boðið; sá sem þiggur það tengist þessum einstaklingi
    person = models.ForeignKey(
        "gifts.Person", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Boðið var sent á þetta netfang (hlekkinn má líka afrita úr lista virkra boða)
    email = models.EmailField(_("netfang"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_invite_expiry)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    objects = InviteQuerySet.as_manager()

    class Meta:
        verbose_name = _("boð")
        verbose_name_plural = _("boð")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.household} ({self.token[:6]}…)"

    @property
    def is_usable(self) -> bool:
        return self.accepted_at is None and self.expires_at > timezone.now()
