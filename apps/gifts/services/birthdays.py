"""Afmælisgjafir: afmæli næstu 12 mánuði hjá þeim sem eru merktir „Gef afmælisgjafir“.

Afmælisgjöf er venjuleg gjöf (hugmyndir, gefendur, keypt, rukkun) með `occasion=BIRTHDAY` og
tilheyrir árinu sem afmælið er á. Gjöfin verður ekki til fyrr en eitthvað er skráð á hana,
svo að skoða síðuna býr ekki til ár eða gjafir.
"""

import datetime
from collections import Counter
from dataclasses import dataclass, field

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.core.text import fold_key
from apps.households.models import Household

from ..models import BirthdayReminder, Gift, Occasion, Person, Season
from .pricing import actual_price
from .queries import with_details
from .stores import stores_of

WINDOW_DAYS = 365
URGENT_DAYS = 7


def next_birthday(birthday: datetime.date, today: datetime.date) -> datetime.date:
    """Næsti afmælisdagur frá og með deginum í dag. 29. feb er 28. feb þegar ár er ekki hlaupár."""

    def on(year):
        try:
            return birthday.replace(year=year)
        except ValueError:
            return datetime.date(year, 2, 28)

    this_year = on(today.year)
    return this_year if this_year >= today else on(today.year + 1)


@dataclass
class Entry:
    person: Person
    date: datetime.date
    age: int
    days: int
    gift: Gift | None

    @property
    def round_birthday(self) -> bool:
        """Stórafmæli: heill tugur frá 20 ára."""
        return self.age >= 20 and self.age % 10 == 0

    @property
    def urgent(self) -> bool:
        return 0 <= self.days <= URGENT_DAYS and not self.bought

    @property
    def near_christmas(self) -> bool:
        """Afmæli í kringum jól: hætta á að afmælisgjöfin renni saman við jólagjöfina."""
        return self.date.month == 12 and self.date.day >= 20

    @property
    def bought(self) -> bool:
        return bool(self.gift and self.gift.bought)

    @property
    def price(self) -> int | None:
        return actual_price(self.gift) if self.gift else None

    @property
    def stores(self):
        return stores_of(self.gift) if self.gift else []


@dataclass
class Month:
    year: int
    month: int
    entries: list[Entry] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.year}-{self.month:02d}"

    @property
    def done(self) -> int:
        return sum(e.bought for e in self.entries)

    @property
    def plan(self) -> int:
        return sum((e.gift.plan or 0) for e in self.entries if e.gift)


@dataclass
class Overview:
    months: list[Month]  # allir 12 mánuðir gluggans í röð, líka tómir
    missing_date: list[Person]  # merktir „Gef afmælisgjafir“ en fæðingardag vantar
    today: datetime.date

    @property
    def entries(self) -> list[Entry]:
        return [e for m in self.months for e in m.entries]

    @property
    def count(self) -> int:
        return len(self.entries)

    @property
    def done(self) -> int:
        return sum(e.bought for e in self.entries)

    @property
    def progress(self) -> float:
        return self.done / self.count if self.count else 0.0

    @property
    def plan(self) -> int:
        return sum((e.gift.plan or 0) for e in self.entries if e.gift)

    @property
    def spent(self) -> int:
        return sum(e.price or 0 for e in self.entries)

    @property
    def next_up(self) -> Entry | None:
        """Næsta afmæli þar sem gjöfin er ekki keypt (annars næsta afmæli)."""
        entries = self.entries
        return next((e for e in entries if not e.bought), entries[0] if entries else None)

    @property
    def soon(self) -> list[Entry]:
        """Afmæli næstu 30 daga."""
        return [e for e in self.entries if e.days <= 30]


def overview(household: Household, today: datetime.date | None = None) -> Overview:
    today = today or timezone.localdate()
    people = list(Person.objects.filter(household=household, give_birthday=True))
    dated = [p for p in people if p.birthday]
    entries = []
    for person in dated:
        date = next_birthday(person.birthday, today)
        entries.append(Entry(person, date, date.year - person.birthday.year, (date - today).days, None))

    # Afmælisgjafir sóttar í einu lagi fyrir alla (ár afmælisins)
    years = {e.date.year for e in entries}
    gifts = with_details(
        Gift.objects.alive()
        .birthdays()
        .filter(season__household=household, season__year__in=years, person__in=dated)
    )
    by_key = {(g.person_id, g.season.year): g for g in gifts}
    for e in entries:
        e.gift = by_key.get((e.person.pk, e.date.year))

    months = []
    for i in range(12):
        y, m = divmod(today.month - 1 + i, 12)
        months.append(Month(today.year + y, m + 1))
    slots = {(mo.year, mo.month): mo for mo in months}
    for e in sorted(entries, key=lambda e: (e.date, fold_key(e.person.name))):
        slots[(e.date.year, e.date.month)].entries.append(e)

    missing = sorted((p for p in people if not p.birthday), key=lambda p: fold_key(p.name))
    return Overview(months=months, missing_date=missing, today=today)


def distribution(household: Household) -> list[int]:
    """Fjöldi afmæla í hverjum mánuði (jan–des) hjá þeim sem fá afmælisgjöf."""
    counts = Counter(
        b.month
        for b in Person.objects.filter(
            household=household, give_birthday=True, birthday__isnull=False
        ).values_list("birthday", flat=True)
    )
    return [counts.get(m, 0) for m in range(1, 13)]


@transaction.atomic
def ensure_gift(person: Person, year: int) -> Gift:
    """Afmælisgjöf einstaklings á afmælisárinu; árið og gjöfin verða til ef þarf."""
    season, _ = Season.objects.get_or_create(household=person.household, year=year)
    gift = Gift.objects.alive().birthdays().filter(season=season, person=person).first()
    return gift or Gift.objects.create(season=season, person=person, occasion=Occasion.BIRTHDAY)


def due_reminders(household: Household, today: datetime.date | None = None) -> list[Entry]:
    """Afmæli innan `reminder_days` sem hafa ekki fengið áminningu.

    „Innan“ en ekki „nákvæmlega“: ef dagleg keyrsla fellur niður fær afmælið samt áminningu.
    """
    if not household.birthday_reminders:
        return []
    entries = [e for e in overview(household, today).entries if 0 <= e.days <= household.reminder_days]
    sent = set(BirthdayReminder.objects.filter(person__household=household).values_list("person_id", "date"))
    return [e for e in entries if (e.person.pk, e.date) not in sent]


def send_reminders(today: datetime.date | None = None) -> int:
    """Sendir afmælisáminningar til meðlima allra heimila sem vilja þær. Skilar fjölda pósta."""
    count = 0
    for household in Household.objects.filter(birthday_reminders=True):
        recipients = [m.user.email for m in household.memberships.select_related("user")]
        if not recipients:
            continue
        for entry in due_reminders(household, today):
            ctx = {
                "entry": entry,
                "household": household,
                "url": settings.SITE_URL + reverse("gifts:birthdays", args=[household.slug]),
            }
            subject = render_to_string("gifts/email/birthday_reminder_subject.txt", ctx).strip()
            body = render_to_string("gifts/email/birthday_reminder.txt", ctx)
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients)
            BirthdayReminder.objects.create(person=entry.person, date=entry.date)
            count += 1
    return count
