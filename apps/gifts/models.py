"""Lénslíkön gjafalistans.

Reglurnar sjálfar (raunverð, rukkun, endurnefning búða …) eru í `services/`; líkönin
geyma gögn og einföld afleidd gildi.
"""

from django.db import models
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.text import fold_key, normalize
from apps.households.models import Household


class Group(models.TextChoices):
    BORN = "born", _("Börn")
    FJOLSKYLDA = "fjolskylda", _("Fjölskylda")
    VINIR = "vinir", _("Vinir")
    VINNA = "vinna", _("Vinna & skóli")
    ANNAD = "annad", _("Annað")


GROUP_ICONS = {"born": "🧸", "fjolskylda": "🏡", "vinir": "💛", "vinna": "🍪", "annad": "✨"}


class PersonQuerySet(models.QuerySet):
    def recipients(self):
        """Fólk sem á (óeydda) gjöf: birtist í gjafalista og undir „Fólk“."""
        live = Gift.objects.filter(person=OuterRef("pk"), deleted_at__isnull=True)
        return self.filter(Exists(live))

    def givers(self):
        """Fólk sem er gefandi á einhverri hugmynd."""
        return self.filter(Exists(IdeaGiver.objects.filter(person=OuterRef("pk"))))


class Person(models.Model):
    """Viðtakandi, gefandi eða hvort tveggja. Hlutverkið ræðst af tengingum, ekki flaggi."""

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="people")
    name = models.CharField(_("nafn"), max_length=100)
    key = models.CharField(max_length=100, editable=False)
    group = models.CharField(_("flokkur"), max_length=12, choices=Group.choices, default=Group.ANNAD)
    birthday = models.DateField(_("fæðingardagur"), null=True, blank=True)
    give_christmas = models.BooleanField(_("gef jólagjafir"), default=True)
    give_birthday = models.BooleanField(_("gef afmælisgjafir"), default=False)
    # Fylgir óskalista einstaklings í öðru heimili (t.d. Sigga hjá Dísu frænku fylgir Siggu hjá
    # foreldrunum): hugmyndir þaðan birtast hér á meðan þær eru ekki keyptar eða fráteknar og
    # uppsprettan á virkan óskalistahlekk. Hugmyndir héðan sjást aldrei þar. Sjá wishlists/services.
    source = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="followers",
        verbose_name=_("fylgir óskalista"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PersonQuerySet.as_manager()

    class Meta:
        verbose_name = _("einstaklingur")
        verbose_name_plural = _("einstaklingar")
        constraints = [models.UniqueConstraint(fields=["household", "key"], name="unique_person_name")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.key = normalize(self.name)
        super().save(*args, **kwargs)


class Location(models.Model):
    """Staður þar sem búð er, t.d. Kringlan eða Netverslun."""

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="locations")
    name = models.CharField(_("nafn"), max_length=100)
    key = models.CharField(max_length=100, editable=False)

    class Meta:
        verbose_name = _("staðsetning")
        verbose_name_plural = _("staðsetningar")
        constraints = [models.UniqueConstraint(fields=["household", "key"], name="unique_location_name")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.key = fold_key(self.name)
        super().save(*args, **kwargs)


class Store(models.Model):
    """Búð. Elkó/Elko/ELKO er sama búðin (`key`); staðsetning tilheyrir búðinni, ekki gjöfinni."""

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="stores")
    name = models.CharField(_("nafn"), max_length=100)
    key = models.CharField(max_length=100, editable=False)
    locations = models.ManyToManyField(
        Location, blank=True, related_name="stores", verbose_name=_("staðsetningar")
    )

    class Meta:
        verbose_name = _("búð")
        verbose_name_plural = _("búðir")
        constraints = [models.UniqueConstraint(fields=["household", "key"], name="unique_store_name")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.key = fold_key(self.name)
        super().save(*args, **kwargs)


class Season(models.Model):
    """Eitt jólaár heimilis."""

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="seasons")
    year = models.PositiveSmallIntegerField(_("ár"))
    budget = models.PositiveIntegerField(_("peningaviðmið"), default=0)
    unlocked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("jólaár")
        verbose_name_plural = _("jólaár")
        ordering = ["-year"]
        constraints = [models.UniqueConstraint(fields=["household", "year"], name="unique_season_year")]

    def __str__(self):
        return f"{self.household} – {self.year}"

    def is_locked(self, now=None) -> bool:
        """Liðin jól eru læst nema einhver hafi opnað þau tímabundið."""
        now = now or timezone.now()
        if self.year >= timezone.localdate(now).year:
            return False
        return not (self.unlocked_until and self.unlocked_until > now)


class Occasion(models.TextChoices):
    CHRISTMAS = "jol", _("Jól")
    BIRTHDAY = "afmaeli", _("Afmæli")


class GiftQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def christmas(self):
        return self.filter(occasion=Occasion.CHRISTMAS)

    def birthdays(self):
        return self.filter(occasion=Occasion.BIRTHDAY)


class Gift(models.Model):
    """Gjöf til eins einstaklings á einu ári og einu tilefni (jól eða afmæli).

    Hugmyndirnar eru það sem er (eða verður) keypt. Afmælisgjöf tilheyrir árinu sem afmælið er á.
    """

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="gifts")
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="gifts")
    occasion = models.CharField(
        _("tilefni"), max_length=10, choices=Occasion.choices, default=Occasion.CHRISTMAS
    )
    plan = models.PositiveIntegerField(_("áætlað verð"), null=True, blank=True)
    bought = models.BooleanField(_("keypt"), default=False)
    # Upphæð slegin inn þegar gjöf er merkt keypt án verðs á hugmyndum
    manual_price = models.PositiveIntegerField(_("skráð verð"), null=True, blank=True)
    stores = models.ManyToManyField(Store, blank=True, related_name="gifts", verbose_name=_("búðir"))
    link = models.URLField(_("hlekkur"), max_length=500, blank=True)
    position = models.PositiveIntegerField(default=0)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = GiftQuerySet.as_manager()

    class Meta:
        verbose_name = _("gjöf")
        verbose_name_plural = _("gjafir")
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["season", "person", "occasion"],
                condition=Q(deleted_at__isnull=True),
                name="unique_live_gift_per_person_occasion",
            )
        ]

    def __str__(self):
        return f"{self.person} ({self.season.year})"

    @property
    def actual_price(self) -> int | None:
        from .services.pricing import actual_price

        return actual_price(self)


class Idea(models.Model):
    gift = models.ForeignKey(Gift, on_delete=models.CASCADE, related_name="ideas")
    text = models.CharField(_("hugmynd"), max_length=200)
    note = models.TextField(_("nánari lýsing"), blank=True)
    store = models.ForeignKey(
        Store, on_delete=models.SET_NULL, null=True, blank=True, related_name="ideas", verbose_name=_("búð")
    )
    link = models.URLField(_("hlekkur"), max_length=500, blank=True)
    price = models.PositiveIntegerField(_("verð"), null=True, blank=True)
    picked = models.BooleanField(_("keypt"), default=False)
    for_other = models.BooleanField(_("keypt fyrir annan"), default=False)
    # Viðtakandinn skráði hana sjálfur: hann sér aðeins sínar eigin óskir (services/privacy.py)
    wish = models.BooleanField(_("ósk viðtakanda"), default=False)
    givers = models.ManyToManyField(Person, through="IdeaGiver", related_name="given_ideas", blank=True)
    position = models.PositiveIntegerField(default=0)
    # „Frátekið“: einhver ætlar að kaupa þetta (af opnum óskalista eða merkt af heimilinu, t.d.
    # þegar Amma segir í síma „ég kaupi það“). Ekki keypt fyrr en „Keypt“ er hakað.
    reserved = models.BooleanField(_("frátekið"), default=False)
    # Frátekning af opnum óskalista: hver og hvenær (heimilið getur merkt frátekið án þessa)
    reserved_by = models.ForeignKey(
        Person, on_delete=models.SET_NULL, null=True, blank=True, related_name="reservations"
    )
    reserved_at = models.DateTimeField(null=True, blank=True)
    reservation_secret = models.CharField(max_length=64, blank=True)
    # Tekin af óskalista einstaklings í öðru heimili (fylgjandi merkti hana keypta eða frátekna):
    # upprunalega hugmyndin er þá frátekin þar í nafni þess sem tók hana
    source = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="copies"
    )
    # Bjó takan til gefandann á upprunanum? Þá (og aðeins þá) fer hann af þegar frátekningin losnar,
    # svo gefandi sem var þar fyrir (t.d. í púkki) haldist
    source_added_giver = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("hugmynd")
        verbose_name_plural = _("hugmyndir")
        ordering = ["position", "id"]

    def __str__(self):
        return self.text


class IdeaGiver(models.Model):
    """Gefandi hugmyndar. `share` er hlutur hans ef hann er ekki jafn hlutur; `paid` gildir fyrir rukkun."""

    idea = models.ForeignKey(Idea, on_delete=models.CASCADE, related_name="giver_links")
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="giver_links")
    share = models.PositiveIntegerField(_("hlutur"), null=True, blank=True)
    paid = models.BooleanField(_("greitt"), default=False)

    class Meta:
        verbose_name = _("gefandi")
        verbose_name_plural = _("gefendur")
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["idea", "person"], name="unique_idea_giver")]

    def __str__(self):
        return f"{self.person} → {self.idea}"


class BirthdayReminder(models.Model):
    """Áminning sem hefur verið send, svo sama afmæli fái aldrei tvær."""

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="birthday_reminders")
    date = models.DateField(_("afmælisdagur"))
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("afmælisáminning")
        verbose_name_plural = _("afmælisáminningar")
        constraints = [models.UniqueConstraint(fields=["person", "date"], name="unique_birthday_reminder")]

    def __str__(self):
        return f"{self.person} {self.date}"
