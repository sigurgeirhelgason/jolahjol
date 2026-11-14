import secrets

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.gifts.models import Person


def new_token() -> str:
    return secrets.token_urlsafe(32)


class WishlistShare(models.Model):
    """Opinn hlekkur á óskalista eins einstaklings. Móttakandinn þarf ekki að vera innskráður."""

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="wishlist_shares")
    token = models.CharField(max_length=64, unique=True, default=new_token, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("óskalistahlekkur")
        verbose_name_plural = _("óskalistahlekkir")

    def __str__(self):
        return f"{self.person} ({self.token[:6]}…)"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class WishRequest(models.Model):
    """Hlekkur sem einstaklingur fær til að skrifa sjálfur óskirnar sínar á listann, án innskráningar.

    Heimilið ræður hvað hann lifir lengi (`expires_at`) og getur lokað honum fyrr. Óskirnar verða
    `Idea.wish` á jólagjöf hans: hann sér þær einar, aldrei stöðu, verð eða hugmyndir annarra.
    """

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="wish_requests")
    token = models.CharField(max_length=64, unique=True, default=new_token, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(_("gildir til"))
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("óskabeiðni")
        verbose_name_plural = _("óskabeiðnir")

    def __str__(self):
        return f"{self.person} ({self.token[:6]}…)"
