"""Rukkun: hverja þarf að rukka, fyrir hvað og hve mikið. Samsvarar `billHtml` í gamla appinu."""

from dataclasses import dataclass, field

from apps.core.text import is_sort_key

from ..models import Gift, Idea, IdeaGiver, Person, Season
from .pricing import split_shares
from .queries import season_gifts


@dataclass
class BillLine:
    gift: Gift
    idea: Idea
    link: IdeaGiver
    amount: int | None  # None = verð vantar

    @property
    def pending(self) -> bool:
        """Merkt fyrir annan en ekki keypt enn: sýnt, en ekki talið með."""
        return not self.idea.picked

    @property
    def paid(self) -> bool:
        return self.link.paid


@dataclass
class Payer:
    person: Person
    lines: list[BillLine] = field(default_factory=list)

    @property
    def bought_lines(self) -> list[BillLine]:
        return [line for line in self.lines if not line.pending]

    @property
    def unpaid_lines(self) -> list[BillLine]:
        return [line for line in self.bought_lines if not line.paid]

    @property
    def total(self) -> int:
        return sum(line.amount or 0 for line in self.bought_lines)

    @property
    def unpaid(self) -> int:
        return sum(line.amount or 0 for line in self.unpaid_lines)


def season_billing(season: Season, gifts: list[Gift] | None = None) -> list[Payer]:
    """Greiðendur ársins; þeir sem skulda fyrst, svo í stafrófsröð."""
    payers: dict[int, Payer] = {}
    for gift in gifts if gifts is not None else season_gifts(season):
        for idea in gift.ideas.all():
            if not idea.for_other:
                continue
            shares = dict((p.pk, n) for p, n in split_shares(idea).givers)
            for link in idea.giver_links.all():
                payer = payers.setdefault(link.person_id, Payer(link.person))
                payer.lines.append(
                    BillLine(gift, idea, link, shares.get(link.person_id) if idea.price else None)
                )
    return sorted(payers.values(), key=lambda p: (not p.unpaid_lines, is_sort_key(p.person.name)))


def bill_text(payer: Payer, year: int) -> str:
    """„Afrita rukkun“: texti til að senda gefanda. Aðeins keypt og ógreitt."""
    from apps.core.money import format_kr

    lines = [f"Hæ {payer.person.name}! Hér er yfirlit yfir jólagjafirnar {year}:", ""]
    for line in payer.unpaid_lines:
        amount = format_kr(line.amount) if line.amount else "verð vantar"
        lines.append(f"• {line.idea.text} handa {line.gift.person.name}: {amount}")
    lines += ["", f"Samtals: {format_kr(payer.unpaid)}"]
    return "\n".join(lines)


def owed_total(payers: list[Payer]) -> int:
    """„Til innheimtu“ í peningastöðu."""
    return sum(p.unpaid for p in payers)


def mark_all_paid(season: Season, person: Person) -> int:
    """Merkir allt keypt sem `person` skuldar á árinu sem greitt. Skilar fjölda lína."""
    return IdeaGiver.objects.filter(
        person=person,
        idea__for_other=True,
        idea__picked=True,
        idea__gift__season=season,
        idea__gift__deleted_at__isnull=True,
    ).update(paid=True)
