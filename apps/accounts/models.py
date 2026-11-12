from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Netfang vantar")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """Notandi auðkenndur með netfangi; ekkert notandanafn."""

    username = None
    first_name = None
    last_name = None
    email = models.EmailField(_("netfang"), unique=True)
    name = models.CharField(_("nafn"), max_length=150, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = _("notandi")
        verbose_name_plural = _("notendur")

    def __str__(self):
        return self.name or self.email
