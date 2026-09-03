"""
ai/patent_prep/deadlines.py

Computes due dates for a case against ai/patent_prep/deadlines.yaml's
rules — see that file's header for what `review_status: draft` means and
why several of these rules carry it.

Calendar-month arithmetic, not offset_days
--------------------------------------------
Patent-prosecution periods are expressed in months ("12 months", "31
months") because that is what the governing rule says, not because it is
approximately 365/943 days. `_add_months()` does real month/year
rollover with day-of-month clamping (31 Jan + 1 month = 28/29 Feb), the
same category of correctness `ai/sectioner.py` insists on for chunk
boundaries — an off-by-a-few-days deadline is a wrong answer just as
much as a mis-cut citation is.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .intake import CaseIntake

DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "deadlines.yaml"

# A due date within this many days counts as "due_soon" rather than
# merely "upcoming" — a deliberately generous window given these are
# statutory deadlines a missed one cannot walk back.
DUE_SOON_WINDOW_DAYS = 60


def _parse_date(value: str) -> _dt.date:
    return _dt.date.fromisoformat(value)


def _add_months(start: _dt.date, months: int) -> _dt.date:
    """Add calendar months to a date, clamping the day into the target
    month's range rather than overflowing into the month after."""
    total = start.year * 12 + (start.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    import calendar

    day = min(start.day, calendar.monthrange(year, month)[1])
    return _dt.date(year, month, day)


@dataclass
class DeadlineRule:
    id: str
    label: str
    anchor: str  # a CaseIntake date-field name
    offset_months: int
    legal_basis: dict[str, str]
    review_status: str
    note: str = ""
    recurring_every_months: int | None = None


def load_deadline_rules(path: Path | str = DEFAULT_RULES_PATH) -> list[DeadlineRule]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [
        DeadlineRule(
            id=r["id"], label=r["label"], anchor=r["anchor"],
            offset_months=r["offset_months"], legal_basis=r["legal_basis"],
            review_status=r.get("review_status", "draft"), note=r.get("note", ""),
            recurring_every_months=r.get("recurring_every_months"),
        )
        for r in (data.get("rules") or [])
    ]


@dataclass
class DeadlineStatus:
    rule_id: str
    label: str
    anchor_field: str
    anchor_date: str | None
    due_date: str | None
    days_remaining: int | None
    status: str  # anchor_unknown | overdue | due_soon | upcoming
    review_status: str
    legal_basis: dict[str, str]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id, "label": self.label,
            "anchor_field": self.anchor_field, "anchor_date": self.anchor_date,
            "due_date": self.due_date, "days_remaining": self.days_remaining,
            "status": self.status, "review_status": self.review_status,
            "legal_basis": self.legal_basis, "note": self.note,
        }


def _next_occurrence(anchor: _dt.date, offset_months: int, recur_months: int, as_of: _dt.date) -> _dt.date:
    due = _add_months(anchor, offset_months)
    while due < as_of:
        due = _add_months(due, recur_months)
    return due


def compute_deadlines(
    case: CaseIntake,
    *,
    as_of: _dt.date | None = None,
    rules: list[DeadlineRule] | None = None,
    rules_path: Path | str = DEFAULT_RULES_PATH,
) -> list[DeadlineStatus]:
    """One DeadlineStatus per rule. A rule whose anchor date is not yet
    known on the case (e.g. `fer_issued_date` before an FER has arrived)
    still gets a row — `status="anchor_unknown"` rather than being
    silently omitted, so a case listing shows what tracking is waiting on
    rather than looking like nothing is due."""
    as_of = as_of or _dt.date.today()
    rules = rules if rules is not None else load_deadline_rules(rules_path)

    results = []
    for rule in rules:
        anchor_value = getattr(case, rule.anchor, None)
        if not anchor_value:
            results.append(DeadlineStatus(
                rule_id=rule.id, label=rule.label, anchor_field=rule.anchor,
                anchor_date=None, due_date=None, days_remaining=None,
                status="anchor_unknown", review_status=rule.review_status,
                legal_basis=rule.legal_basis, note=rule.note,
            ))
            continue

        anchor = _parse_date(anchor_value)
        if rule.recurring_every_months:
            due = _next_occurrence(anchor, rule.offset_months, rule.recurring_every_months, as_of)
        else:
            due = _add_months(anchor, rule.offset_months)

        days_remaining = (due - as_of).days
        if days_remaining < 0:
            status = "overdue"
        elif days_remaining <= DUE_SOON_WINDOW_DAYS:
            status = "due_soon"
        else:
            status = "upcoming"

        results.append(DeadlineStatus(
            rule_id=rule.id, label=rule.label, anchor_field=rule.anchor,
            anchor_date=anchor.isoformat(), due_date=due.isoformat(),
            days_remaining=days_remaining, status=status,
            review_status=rule.review_status, legal_basis=rule.legal_basis,
            note=rule.note,
        ))

    return results
