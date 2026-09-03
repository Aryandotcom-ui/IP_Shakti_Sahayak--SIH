"""
Tests for ai/patent_prep — intake, pre-checks, form drafting, deadline
tracking, and the case tracker/handoff state machine.

    python -m pytest ai/tests/test_patent_prep.py -v

The deadline tests are the ones worth reading closely: they pin the
calendar-month arithmetic (31 Jan + N months must not overflow into the
wrong month), that a missing anchor date reports `anchor_unknown` rather
than being silently skipped, and that a recurring rule rolls forward to
the next occurrence rather than reporting `overdue` forever once one
cycle has passed.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.patent_prep.deadlines import (  # noqa: E402
    DeadlineRule,
    _add_months,
    compute_deadlines,
    load_deadline_rules,
)
from ai.patent_prep.forms import draft_all, draft_form_1, draft_form_3, draft_form_27  # noqa: E402
from ai.patent_prep.handoff import build_handoff_package, handoff_case  # noqa: E402
from ai.patent_prep.intake import CaseIntake  # noqa: E402
from ai.patent_prep.precheck import run_prechecks  # noqa: E402
from ai.patent_prep.tracker import CaseNotFound, CaseTracker  # noqa: E402

CORPUS = REPO_ROOT / "ai" / "corpus.yaml"


# ---------------------------------------------------------------------------
# intake
# ---------------------------------------------------------------------------


def test_compliance_facts_drops_unset_fields():
    case = CaseIntake(formulation_type="classical", jurisdiction="india")
    facts = case.compliance_facts()
    assert facts == {"formulation_type": "classical", "jurisdiction": "india"}


def test_compliance_facts_excludes_non_compliance_fields():
    case = CaseIntake(applicant_name="Jane Doe", formulation_type="classical")
    facts = case.compliance_facts()
    assert "applicant_name" not in facts
    assert facts["formulation_type"] == "classical"


def test_missing_intake_fields_reports_whats_missing():
    case = CaseIntake()
    assert set(case.missing_intake_fields()) == {
        "applicant_name", "inventors", "invention_title"
    }


def test_missing_intake_fields_empty_once_supplied():
    case = CaseIntake(applicant_name="Jane Doe", inventors=["Jane Doe"],
                       invention_title="A formulation")
    assert case.missing_intake_fields() == []


def test_round_trips_through_dict():
    case = CaseIntake(applicant_name="Jane Doe", ingredients=["turmeric", "neem"])
    restored = CaseIntake.from_dict(case.to_dict())
    assert restored == case


def test_from_dict_ignores_unknown_keys():
    restored = CaseIntake.from_dict({"applicant_name": "Jane Doe", "bogus_field": 1})
    assert restored.applicant_name == "Jane Doe"


# ---------------------------------------------------------------------------
# precheck (exercises the real ai.compliance.assess())
# ---------------------------------------------------------------------------


def test_precheck_incomplete_intake_is_not_clear_to_draft():
    case = CaseIntake()  # nothing supplied at all
    report = run_prechecks(case, corpus_path=str(CORPUS))
    assert report.clear_to_draft is False
    assert any("intake incomplete" in r for r in report.reasons_not_clear)


def test_precheck_blocking_obligation_prevents_clear_to_draft():
    case = CaseIntake(
        applicant_name="Jane Doe", inventors=["Jane Doe"], invention_title="A formulation",
        formulation_type="classical", applicant_category="foreign_national",
        resource_origin="india", resource_cultivation="wild_collected",
        seeking_ipr=True, uses_biological_material=True,
    )
    report = run_prechecks(case, corpus_path=str(CORPUS))
    assert report.blocking, "a foreign national seeking IPR over a wild-collected " \
        "Indian resource should trigger a blocking ABS obligation"
    assert report.clear_to_draft is False


def test_precheck_to_dict_is_json_shaped():
    case = CaseIntake(applicant_name="Jane Doe", inventors=["Jane Doe"],
                       invention_title="A formulation")
    report = run_prechecks(case, corpus_path=str(CORPUS))
    d = report.to_dict()
    assert set(d) == {
        "compliance", "blocking", "critical_open_questions",
        "clear_to_draft", "reasons_not_clear",
    }


# ---------------------------------------------------------------------------
# forms
# ---------------------------------------------------------------------------


def test_form_1_flags_missing_fields():
    draft = draft_form_1(CaseIntake())
    assert any("Incomplete intake" in c for c in draft.caveats)
    assert "[NOT SUPPLIED]" in draft.render()


def test_form_1_guesses_convention_when_priority_predates_filing():
    case = CaseIntake(priority_date="2024-01-01", filing_date="2024-06-01")
    draft = draft_form_1(case)
    assert draft.fields["application_category_guess"] == "convention"


def test_form_1_guesses_ordinary_when_no_earlier_priority():
    case = CaseIntake(filing_date="2024-06-01")
    draft = draft_form_1(case)
    assert draft.fields["application_category_guess"] == "ordinary"


def test_form_3_never_defaults_foreign_filings_to_none():
    draft = draft_form_3(CaseIntake())
    assert draft.fields["corresponding_foreign_applications"] != "none"
    assert "APPLICANT MUST SUPPLY" in draft.fields["corresponding_foreign_applications"]


def test_form_27_warns_when_not_yet_granted():
    draft = draft_form_27(CaseIntake())
    assert any("may not be granted yet" in c for c in draft.caveats)


def test_draft_all_omits_form_27_before_grant():
    forms = draft_all(CaseIntake())
    assert "form_27" not in forms
    assert set(forms) == {"form_1", "form_3"}


def test_draft_all_includes_form_27_after_grant():
    forms = draft_all(CaseIntake(grant_date="2020-01-01"))
    assert "form_27" in forms


def test_every_form_draft_carries_the_standard_caveat():
    for draft in draft_all(CaseIntake(grant_date="2020-01-01")).values():
        assert any("Draft content only" in c for c in draft.caveats)


# ---------------------------------------------------------------------------
# deadlines
# ---------------------------------------------------------------------------


def test_load_deadline_rules_from_the_real_file():
    rules = load_deadline_rules()
    ids = {r.id for r in rules}
    assert {"convention_priority", "pct_national_phase",
            "request_for_examination", "fer_response",
            "form_27_working_statement"} <= ids


def test_domestic_procedural_rules_are_flagged_draft_not_verified():
    rules = {r.id: r for r in load_deadline_rules()}
    assert rules["request_for_examination"].review_status == "draft"
    assert rules["fer_response"].review_status == "draft"
    assert rules["form_27_working_statement"].review_status == "draft"


def test_treaty_rules_are_flagged_verified():
    rules = {r.id: r for r in load_deadline_rules()}
    assert rules["convention_priority"].review_status == "verified"
    assert rules["pct_national_phase"].review_status == "verified"


def test_add_months_clamps_day_into_target_month():
    # 31 Jan + 1 month must land on the last day of Feb, not overflow into March.
    assert _add_months(datetime.date(2025, 1, 31), 1) == datetime.date(2025, 2, 28)
    assert _add_months(datetime.date(2024, 1, 31), 1) == datetime.date(2024, 2, 29)  # leap year


def test_add_months_rolls_over_year_boundary():
    assert _add_months(datetime.date(2024, 11, 15), 3) == datetime.date(2025, 2, 15)


def test_compute_deadlines_reports_anchor_unknown_not_skipped():
    case = CaseIntake()  # no dates at all
    statuses = compute_deadlines(case, as_of=datetime.date(2026, 1, 1))
    assert len(statuses) == len(load_deadline_rules())
    assert all(s.status == "anchor_unknown" for s in statuses)


def test_compute_deadlines_overdue_vs_upcoming():
    case = CaseIntake(priority_date="2020-01-01")
    statuses = {s.rule_id: s for s in compute_deadlines(case, as_of=datetime.date(2026, 1, 1))}
    assert statuses["convention_priority"].status == "overdue"
    assert statuses["convention_priority"].days_remaining < 0


def test_compute_deadlines_due_soon_window():
    # convention_priority is 12 months; set as_of 45 days before that due date.
    priority = datetime.date(2025, 1, 1)
    due = _add_months(priority, 12)
    as_of = due - datetime.timedelta(days=45)
    case = CaseIntake(priority_date=priority.isoformat())
    statuses = {s.rule_id: s for s in compute_deadlines(case, as_of=as_of)}
    assert statuses["convention_priority"].status == "due_soon"


def test_recurring_deadline_rolls_forward_past_missed_cycles():
    # Granted 10 years ago; a 3-year-recurring rule must report the NEXT
    # occurrence on/after as_of, not "overdue" forever.
    case = CaseIntake(grant_date="2016-01-01")
    statuses = {s.rule_id: s for s in compute_deadlines(case, as_of=datetime.date(2026, 6, 1))}
    form_27 = statuses["form_27_working_statement"]
    assert form_27.status in ("upcoming", "due_soon")
    assert form_27.due_date >= "2026-06-01"


def test_compute_deadlines_carries_review_status_through():
    case = CaseIntake(priority_date="2020-01-01", grant_date="2020-01-01")
    statuses = {s.rule_id: s for s in compute_deadlines(case, as_of=datetime.date(2026, 1, 1))}
    assert statuses["convention_priority"].review_status == "verified"
    assert statuses["request_for_examination"].review_status == "draft"


# ---------------------------------------------------------------------------
# tracker: case state machine
# ---------------------------------------------------------------------------


@pytest.fixture
def tracker(tmp_path: Path):
    t = CaseTracker(tmp_path / "cases.sqlite3")
    yield t
    t.close()


def test_create_and_get_case(tracker: CaseTracker):
    case = CaseIntake(applicant_name="Jane Doe")
    case_id = tracker.create_case(case)
    record = tracker.get_case(case_id)
    assert record["status"] == "intake"
    assert record["intake"]["applicant_name"] == "Jane Doe"


def test_get_missing_case_raises(tracker: CaseTracker):
    with pytest.raises(CaseNotFound):
        tracker.get_case("does-not-exist")


def test_record_precheck_advances_status(tracker: CaseTracker):
    case_id = tracker.create_case(CaseIntake())
    tracker.record_precheck(case_id, {"clear_to_draft": False, "reasons_not_clear": ["x"]})
    assert tracker.get_case(case_id)["status"] == "prechecked"


def test_record_forms_advances_status(tracker: CaseTracker):
    case_id = tracker.create_case(CaseIntake())
    tracker.record_forms(case_id, {"form_1": {"form_id": "Form 1"}})
    assert tracker.get_case(case_id)["status"] == "drafted"


def test_update_status_accepts_unmanaged_prosecution_states(tracker: CaseTracker):
    case_id = tracker.create_case(CaseIntake())
    tracker.update_status(case_id, "filed", detail="filed at IPO Chennai")
    assert tracker.get_case(case_id)["status"] == "filed"
    tracker.update_status(case_id, "granted")
    assert tracker.get_case(case_id)["status"] == "granted"


def test_events_are_recorded_in_order(tracker: CaseTracker):
    case_id = tracker.create_case(CaseIntake())
    tracker.record_precheck(case_id, {"clear_to_draft": True})
    tracker.record_forms(case_id, {})
    events = [e["event"] for e in tracker.events(case_id)]
    assert events == ["created", "prechecked", "forms_drafted"]


def test_list_cases_filters_by_status(tracker: CaseTracker):
    id1 = tracker.create_case(CaseIntake(applicant_name="A"))
    id2 = tracker.create_case(CaseIntake(applicant_name="B"))
    tracker.record_precheck(id2, {"clear_to_draft": True})
    intake_only = tracker.list_cases(status="intake")
    assert [c["id"] for c in intake_only] == [id1]


# ---------------------------------------------------------------------------
# handoff: full workflow
# ---------------------------------------------------------------------------


def test_build_handoff_package_shape():
    case = CaseIntake(applicant_name="Jane Doe", inventors=["Jane Doe"],
                       invention_title="A formulation", priority_date="2025-01-01")
    package = build_handoff_package(case, corpus_path=str(CORPUS),
                                     as_of=datetime.date(2026, 1, 1))
    assert set(package) == {
        "generated_at", "intake", "precheck", "forms", "deadlines", "handoff_notes"
    }
    assert package["forms"]["form_1"]["form_id"] == "Form 1"


def test_handoff_case_updates_tracker_and_returns_package(tracker: CaseTracker):
    case = CaseIntake(applicant_name="Jane Doe", inventors=["Jane Doe"],
                       invention_title="A formulation", priority_date="2025-01-01")
    case_id = tracker.create_case(case)
    package = handoff_case(
        tracker, case_id, recipient="agent@example.test", notes="ready",
        corpus_path=str(CORPUS), as_of=datetime.date(2026, 1, 1),
    )
    record = tracker.get_case(case_id)
    assert record["status"] == "handed_off"
    assert record["handoff_result"]["intake"]["applicant_name"] == "Jane Doe"
    assert package["intake"]["applicant_name"] == "Jane Doe"
    events = [e["event"] for e in tracker.events(case_id)]
    assert events[-1] == "handed_off"
