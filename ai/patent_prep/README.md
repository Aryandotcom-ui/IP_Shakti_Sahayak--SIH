# ai/patent_prep — patent preparation and tracking

A separate module from the RAG core: it drafts and screens a specific
case, and never touches retrieval or the corpus itself.

```
intake -> precheck (ABS/TKDL, via ai.compliance) -> draft forms
    -> deadline tracking -> handoff to a registered patent agent
```

## Files

```
ai/patent_prep/
├── intake.py       # CaseIntake — reuses ai.compliance.ComplianceContext's
│                    # field names verbatim, so no translation layer
├── precheck.py       # run_prechecks() — thin wrapper around ai.compliance.assess()
├── forms.py            # draft_form_1/3/27() — structured + rendered draft content
├── deadlines.yaml        # deadline rules: anchor, offset_months, review_status
├── deadlines.py            # compute_deadlines() — calendar-month arithmetic
├── tracker.py               # CaseTracker — SQLite case + event log
└── handoff.py                # build_handoff_package() / handoff_case()
```

## Why this reuses ai.compliance instead of re-screening

`CaseIntake`'s compliance-relevant fields are named identically to
`ai.compliance.context.ComplianceContext`'s — `formulation_type` through
`ingredients` — so `precheck.py` hands a case straight to
`ai.compliance.assess()`. That function already runs the TKDL prior-art
probe automatically when an obligation requests it (the `probe: tkdl`
marker on the section 3(p) node in `ai/knowledge_graph/ontology.yaml`),
so one call gets both the ABS screening and the prior-art check — no
separate TKDL call needed here, and no duplicated obligation logic to
drift out of sync with the RAG query path's own screening.

## Draft forms are not filled official forms

`forms.py` has no access to the IPO's actual Form 1/3/27 layout —
`ai/corpus.yaml` lists `patents-rules-2003.pdf` as `status: pending` for
exactly this reason. A `FormDraft` is structured content plus a
plain-text rendering meant for a patent agent to transcribe onto the
real form and verify, never to file directly. Form 3's foreign-filing
disclosure field in particular is never defaulted to "none" — section 8
disclosure is strict-liability, so a guessed or omitted answer there can
be independently fatal to the patent regardless of the invention's
merits; the field is left explicitly `[APPLICANT MUST SUPPLY]` instead.

## Deadlines: `review_status: verified` vs `draft`

`deadlines.yaml` seeds two long-standing treaty-level periods with
`review_status: verified` (the 12-month Paris Convention priority
window, the 31-month PCT national-phase deadline) and three domestic
procedural deadlines — request for examination, FER response, Form 27's
filing cadence — with `review_status: draft`. The domestic ones were
entered without direct access to the post-2024-amendment Patents Rules
text (see `ai/corpus.yaml`'s `patents-rules-2003.pdf` entry, still
`status: pending`), so every computed deadline carries that flag through
rather than presenting a possibly-superseded figure as settled. **Confirm
every `draft` deadline against the amended Rules before relying on it.**

Calendar-month arithmetic (`_add_months()`), not `offset_days * 30` —
"31 months" is a legally exact period, and day-count approximation drifts
across leap years.

## Running it

```bash
python -m pytest ai/tests/test_patent_prep.py -v
```

Or via the backend API — see `backend/README.md`'s "Patent preparation
and tracking" section for the `/api/v1/patent-cases/*` endpoints, which
wrap the same functions:
`create -> precheck -> draft-forms -> deadlines -> handoff`, plus a free-
form `status` update for prosecution states this module cannot observe
itself (filed, fer_received, granted, abandoned, refused).

## What's a skeleton, not production-hardened

- **No authentication.** `recipient`/`decided_by`-style fields are free
  text, not checked against a login session, matching `ai/updates`'
  posture on the same issue.
- **No real IPO form templates or e-filing integration.** Drafts are a
  preparation aid; filing still happens through the IPO's own portal or
  a patent agent.
- **The three `draft` deadline rules need confirming** against the
  amended Patents Rules before this is used for anything but a demo —
  see above.
