"""Peningastaða og framvinda ársins. Samsvarar `renderSummary` í gamla appinu."""

import datetime
from dataclasses import dataclass

from django.utils import timezone

from ..models import Gift, Group, Season
from .billing import owed_total, season_billing
from .queries import season_gifts


@dataclass(frozen=True)
class GroupProgress:
    group: str
    done: int
    count: int
    plan: int
    spent: int


@dataclass(frozen=True)
class SeasonSummary:
    count: int
    done: int
    budget: int
    total_plan: int
    spent: int
    planned_left: int  # áætlun ókeyptra
    bought_plan: int  # áætlun keyptra með þekkt raunverð
    bought_spent: int
    owed: int  # til innheimtu
    due_payers: int  # gefendur sem skulda (teljari á Rukkun-flipanum)
    days_left: int
    groups: list[GroupProgress]

    @property
    def todo(self) -> int:
        return self.count - self.done

    @property
    def progress(self) -> float:
        return self.done / self.count if self.count else 0.0

    @property
    def left(self) -> int:
        """Eftir af viðmiði (neikvætt = yfir)."""
        return self.budget - self.spent

    @property
    def bought_diff(self) -> int:
        """Raunverð keyptra miðað við áætlun þeirra (jákvætt = dýrara en áætlað)."""
        return self.bought_spent - self.bought_plan

    @property
    def unallocated(self) -> int:
        return self.budget - self.total_plan

    @property
    def spent_pct(self) -> int:
        return round(self.spent / self.budget * 100) if self.budget else 0

    @property
    def gifts_per_day(self) -> float | None:
        """Ráðlagður hraði; None þegar jólin eru komin eða allt keypt."""
        if not self.todo or self.days_left <= 0:
            return None
        return self.todo / self.days_left


def days_until_christmas(year: int, today: datetime.date | None = None) -> int:
    today = today or timezone.localdate()
    return (datetime.date(year, 12, 24) - today).days


def group_progress(gifts: list[Gift]) -> list[GroupProgress]:
    out = []
    for value, _label in Group.choices:
        members = [g for g in gifts if g.person.group == value]
        if members:
            out.append(
                GroupProgress(
                    group=value,
                    done=sum(g.bought for g in members),
                    count=len(members),
                    plan=sum(g.plan or 0 for g in members),
                    spent=sum(g.actual_price or 0 for g in members),
                )
            )
    return out


def season_summary(season: Season, gifts: list[Gift] | None = None, today=None) -> SeasonSummary:
    gifts = gifts if gifts is not None else season_gifts(season)
    prices = {g.pk: g.actual_price for g in gifts}
    bought_known = [g for g in gifts if g.bought and prices[g.pk] is not None]
    return SeasonSummary(
        count=len(gifts),
        done=sum(g.bought for g in gifts),
        budget=season.budget,
        total_plan=sum(g.plan or 0 for g in gifts),
        spent=sum(p or 0 for p in prices.values()),
        planned_left=sum(g.plan or 0 for g in gifts if not g.bought),
        bought_plan=sum(g.plan or 0 for g in bought_known),
        bought_spent=sum(prices[g.pk] for g in bought_known),
        owed=owed_total(payers := season_billing(season, gifts)),
        due_payers=sum(1 for p in payers if p.unpaid_lines),
        days_left=days_until_christmas(season.year, today),
        groups=group_progress(gifts),
    )
