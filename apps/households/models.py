from django.conf import settings
from django.db import models
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("aðild")
        verbose_name_plural = _("aðildir")
        constraints = [models.UniqueConstraint(fields=["user", "household"], name="unique_membership")]

    def __str__(self):
        return f"{self.user} – {self.household}"
