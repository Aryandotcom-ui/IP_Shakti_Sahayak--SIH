"""
Tests for the regulatory graph and the ABS-compliance helper.

    python -m pytest ai/tests/test_compliance.py -v

The tests worth reading are the negative ones. Anyone can assert that a
foreign applicant owes NBA approval. The cases that catch real regressions
are the ones asserting the system does NOT say something:

  - that an unavailable prior-art probe reports `unknown`, never `low`;
  - that an empty context does not read as "no obligations";
  - that the 2023 amendment split is preserved (registration != approval).

Each of those is a wrong answer that looks completely normal in a demo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.compliance import ComplianceContext, assess  # noqa: E402
from ai.compliance.abs import ABSAssessor  # noqa: E402
from ai.compliance.tkdl import (  # noqa: E402
    LocalClassicalProbe,
    NullProbe,
    TKDLProbe,
    get_probe,
)
from ai.knowledge_graph.graph import RegulatoryGraph, get_graph  # noqa: E402
from ai.shared.taxonomy import acts_for_formulation, is_graph_backed  # noqa: E402

CORPUS = REPO_ROOT / "ai" / "corpus.yaml"


class Classification:
    """Stand-in for Shape 2, structural rather than imported — two modules
    define Classification and the context layer binds to neither."""

    def __init__(self, formulation_type, source_organism="plant", jurisdiction="india"):
        self.formulation_type = formulation_type
        self.source_organism = source_organism
        self.jurisdiction = jurisdiction


@pytest.fixture(scope="module")
def graph() -> RegulatoryGraph:
    return get_graph()


# ---------------------------------------------------------------------------
# Ontology integrity
# ---------------------------------------------------------------------------

def test_ontology_loads_and_is_internally_consistent(graph):
    """check_integrity() runs at construction, so loading is the assertion."""
    assert graph.obligations
    assert graph.regimes
    assert graph.governed_by


def test_every_obligation_has_a_legal_basis(graph):
    for oid, ob in graph.obligations.items():
        assert ob.legal_basis.act_name, f"{oid} has no act_name"
        assert ob.legal_basis.section, f"{oid} has no section"


def test_every_trigger_field_exists_on_the_context(graph):
    """A trigger reading a field the context cannot hold never fires, and
    nothing at runtime says so."""
    known = set(ComplianceContext.__dataclass_fields__)
    unknown = graph.context_fields() - known
    assert not unknown, f"triggers read fields with no context attribute: {sorted(unknown)}"


def test_no_act_name_drift_against_corpus(graph):
    """Every act the graph cites must at least be LISTED in corpus.yaml.
    Not-yet-ingested is fine; absent entirely means the strings disagree."""
    report = graph.validate_against_corpus(CORPUS)
    assert not report["unlisted"], (
        f"acts cited by the ontology but missing from corpus.yaml: {report['unlisted']}"
    )


# ---------------------------------------------------------------------------
# Derived taxonomy — the module that was broken on main
# ---------------------------------------------------------------------------

def test_taxonomy_is_importable_from_the_path_consumers_use():
    """store.py and retrieval.py both import ai.shared.taxonomy. This test
    exists because that module did not exist at that path and both files
    raised ModuleNotFoundError at import."""
    import ai.shared.taxonomy  # noqa: F401
    import ai.store  # noqa: F401


def test_taxonomy_is_graph_backed_not_fallback():
    assert is_graph_backed(), "taxonomy silently fell back to the hardcoded map"


def test_acts_for_unknown_formulation_returns_none_not_empty():
    """None means 'no pre-filter, fall back to jurisdiction'. [] passed into
    a Chroma $in filter matches nothing, turning 'we cannot narrow this' into
    'no law covers this'."""
    assert acts_for_formulation("not_a_formulation") is None
    assert acts_for_formulation(None) is None
    assert acts_for_formulation("") is None


def test_taxonomy_acts_match_corpus_strings_exactly(graph):
    """Chroma's where filter is exact-match. A stray 'The ' is a silent zero-hit."""
    import yaml

    manifest = yaml.safe_load(CORPUS.read_text(encoding="utf-8"))
    listed = {d["act_name"] for d in manifest["documents"]}
    for formulation in graph.governed_by:
        for act in acts_for_formulation(formulation) or []:
            assert act in listed, f"{formulation} -> {act!r} not in corpus.yaml"


# ---------------------------------------------------------------------------
# ABS branching — the 2023 amendment split
# ---------------------------------------------------------------------------

def _ids(report) -> set[str]:
    return {o.id for o in report.obligations}


def test_foreign_applicant_needs_nba_approval():
    report = assess(
        Classification("classical"),
        applicant_category="foreign_national",
        resource_origin="india",
        seeking_ipr=True,
    )
    assert "bda_s6_nba_approval_before_grant" in _ids(report)
    assert "bda_s6_1a_nba_registration" not in _ids(report)


def test_indian_applicant_gets_registration_not_approval():
    """The 2023 amendment's central relief. Collapsing registration into
    approval reimposes a process the law removed."""
    report = assess(
        Classification("classical"),
        applicant_category="indian_entity",
        resource_origin="india",
        seeking_ipr=True,
    )
    assert "bda_s6_1a_nba_registration" in _ids(report)
    assert "bda_s6_nba_approval_before_grant" not in _ids(report)


def test_section_6_deadline_is_before_grant_not_before_filing():
    """Pre-2023 the trigger was filing. Encoding the old rule tells an
    applicant who has already filed that they are in breach."""
    report = assess(
        Classification("classical"),
        applicant_category="foreign_national",
        resource_origin="india",
        seeking_ipr=True,
    )
    ob = next(o for o in report.obligations if o.id == "bda_s6_nba_approval_before_grant")
    assert ob.deadline_anchor == "ipr_grant"
    assert "grant" in (ob.deadline or "").lower()


def test_resource_from_outside_india_suppresses_the_bda_chain():
    report = assess(
        Classification("classical"),
        applicant_category="foreign_national",
        resource_origin="outside_india",
        seeking_ipr=True,
    )
    ids = _ids(report)
    assert not {i for i in ids if i.startswith("bda_")}
    # The BDA obligations never fire here (their own triggers require an
    # Indian-origin resource), so there is nothing to SUPPRESS. The negative
    # still has to be explained rather than left as silence, which is what
    # the inapplicability channel is for.
    assert report.inapplicable, "a negative finding must be explained, not silent"
    note = report.inapplicable[0]
    assert "Biological Diversity Act" in note["citation"]
    assert "bda_s6_nba_approval_before_grant" in note["covers"]


def test_cultivated_ayush_exemption_suppresses_sbb_intimation():
    report = assess(
        Classification("proprietary"),
        applicant_category="indian_individual",
        resource_origin="india",
        resource_cultivation="cultivated",
        practitioner_is_registered_ayush=True,
        intends_commercialisation=True,
        seeking_ipr=True,
    )
    assert "bda_s7_sbb_intimation" not in _ids(report)
    suppressed = {e["obligation_id"] for e in report.exemptions}
    assert "bda_s7_sbb_intimation" in suppressed


def test_cultivated_exemption_does_not_switch_off_section_6():
    """The exemption is about benefit sharing. Reading it as a general ABS
    waiver is the obvious over-application, so pin it down."""
    report = assess(
        Classification("proprietary"),
        applicant_category="indian_individual",
        resource_origin="india",
        resource_cultivation="cultivated",
        practitioner_is_registered_ayush=True,
        seeking_ipr=True,
    )
    assert "bda_s6_1a_nba_registration" in _ids(report)


def test_obligations_are_ordered_by_dependency():
    report = assess(
        Classification("classical"),
        applicant_category="foreign_national",
        resource_origin="india",
        seeking_ipr=True,
    )
    order = [o.id for o in report.obligations]
    if {"bda_s3_prior_approval", "bda_s6_nba_approval_before_grant"} <= set(order):
        assert order.index("bda_s3_prior_approval") < order.index(
            "bda_s6_nba_approval_before_grant"
        )


# ---------------------------------------------------------------------------
# Incompleteness must not read as absence
# ---------------------------------------------------------------------------

def test_bare_classification_asks_critical_questions():
    report = assess(Classification("classical"))
    critical = [q for q in report.open_questions if q["importance"] == "critical"]
    assert {q["field"] for q in critical} >= {"applicant_category", "resource_origin"}
    assert report.provisional


def test_bare_classification_headline_is_not_a_clean_bill_of_health():
    report = assess(Classification("classical"))
    headline = report.headline().lower()
    assert "not enough information" in headline
    assert not headline.startswith("no biodiversity")


def test_missing_critical_field_keeps_report_provisional():
    report = assess(
        Classification("classical"),
        applicant_category="foreign_national",
        seeking_ipr=True,
    )  # resource_origin omitted
    assert report.provisional
    assert "resource_origin" in {q["field"] for q in report.open_questions}


# ---------------------------------------------------------------------------
# Prior-art probe honesty
# ---------------------------------------------------------------------------

def test_local_probe_flags_a_classical_formulation():
    result = LocalClassicalProbe().search(["Triphala"])
    assert result.available
    assert result.risk == "high"
    assert result.hits[0].match_type == "formulation_name"


def test_local_probe_flags_a_combination_of_known_components():
    result = LocalClassicalProbe().search(["Withania somnifera", "Curcuma longa"])
    assert any(h.match_type == "combination" for h in result.hits)


def test_unavailable_probe_reports_unknown_never_low():
    """The failure this guards: an unconfigured probe returning an empty
    result that a UI renders as a green tick."""
    result = NullProbe().search(["Triphala"])
    assert result.risk == "unknown"
    assert result.risk != "low"


def test_unconfigured_tkdl_raises_rather_than_returning_empty():
    with pytest.raises(RuntimeError, match="not publicly queryable|not configured"):
        TKDLProbe().search(["Triphala"])


def test_probe_selection_falls_back_to_local_without_credentials():
    assert get_probe().name == "local_classical_index"
    assert get_probe("https://example.invalid", "token").name == "tkdl"


def test_all_seed_prior_art_is_marked_unverified():
    """Seed data must never masquerade as checked source records."""
    result = LocalClassicalProbe().search(["Triphala", "Curcuma longa"])
    assert all(not h.verified for h in result.hits)


def test_prior_art_skipped_when_no_terms_supplied():
    report = assess(
        Classification("classical"),
        applicant_category="indian_entity",
        resource_origin="india",
        seeking_ipr=True,
    )
    assert report.prior_art is not None
    assert report.prior_art["risk"] == "unknown"


# ---------------------------------------------------------------------------
# Citability
# ---------------------------------------------------------------------------

def test_uncitable_acts_are_reported_when_corpus_is_incomplete(tmp_path):
    """An obligation citing a not-yet-ingested act still fires — the duty
    exists in law — but the caller must be able to tell it cannot be backed
    by a retrieved chunk.

    Built against a purpose-made manifest rather than the real corpus.yaml.
    The original version asserted that the Biological Diversity Act was
    uncitable, which was only true while the corpus was empty; it broke the
    moment that Act was actually ingested. Pinning the mechanism instead of
    the corpus's current contents keeps this test honest as documents land.
    """
    manifest = tmp_path / "corpus.yaml"
    manifest.write_text(
        "documents:\n"
        "  - file: patents-act-1970.pdf\n"
        "    status: ingested\n"
        "    jurisdiction: india\n"
        "    instrument_type: statute\n"
        '    act_name: "The Patents Act, 1970"\n'
        '    effective_date: "1972-04-20"\n'
        '    source_url: ""\n'
        "  - file: biological-diversity-act-2002.pdf\n"
        "    status: pending\n"
        "    jurisdiction: india\n"
        "    instrument_type: statute\n"
        '    act_name: "The Biological Diversity Act, 2002"\n'
        '    effective_date: "2003-10-01"\n'
        '    source_url: ""\n',
        encoding="utf-8",
    )
    assessor = ABSAssessor(corpus_path=str(manifest))
    report = assessor.assess(
        ComplianceContext.from_classification(
            Classification("classical"),
            applicant_category="foreign_national",
            resource_origin="india",
            seeking_ipr=True,
        )
    )
    assert "The Biological Diversity Act, 2002" in report.uncitable_acts
    assert "The Patents Act, 1970" not in report.uncitable_acts


def test_nothing_is_uncitable_once_the_real_corpus_holds_every_cited_act():
    """The complement of the test above, against the live manifest: every act
    the graph cites is now ingested, so an assessment reports no uncitable
    acts. This is what makes the obligations quotable rather than merely
    asserted — if a document is ever removed or reverted to `pending`, this
    fails and says so."""
    assessor = ABSAssessor(corpus_path=str(CORPUS))
    report = assessor.assess(
        ComplianceContext.from_classification(
            Classification("classical"),
            applicant_category="foreign_national",
            resource_origin="india",
            seeking_ipr=True,
        )
    )
    assert report.uncitable_acts == []


def test_context_rejects_unknown_fields():
    with pytest.raises(TypeError, match="unknown context field"):
        ComplianceContext.from_classification(Classification("classical"), nonsense=True)


def test_jurisdiction_india_does_not_imply_resource_origin_india():
    """The tempting inference, and the one that would produce wrong ABS
    advice most often: where the question is asked says nothing about where
    the plant came from."""
    ctx = ComplianceContext.from_classification(Classification("classical"))
    ctx.infer_defaults()
    assert ctx.jurisdiction == "india"
    assert ctx.resource_origin is None
