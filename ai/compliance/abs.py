"""
compliance/abs.py

The ABS-compliance helper. Runs off the classification step, not as a
separate lookup the user has to know to ask for.

Design
------
This is deliberately NOT a tool the user invokes. Someone who does not
already know that section 6 of the Biological Diversity Act exists will
never think to search for it -- and that person is precisely who the flag is
for. So `assess()` is called on the same classification the retriever
already computed, and its output rides along with every answer.

Three things are fused into one report:

  1. obligations, from traversing the regulatory graph;
  2. section 3(p) prior-art exposure, from the probe;
  3. what is still unknown, as questions.

(3) is not an afterthought. The decisive ABS facts are facts about the
applicant, which the classifier cannot see, so an honest report is usually
incomplete on first pass. A system that hides that and emits a confident
"no obligations found" is worse than one that emits nothing.

Confidence is capped, never raised, by missing input: `completeness` falls
out of how many critical fields were supplied, and the answer is marked
provisional whenever any are absent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..knowledge_graph.graph import (
    GraphQueryResult,
    RegulatoryGraph,
    ResolvedObligation,
    get_graph,
)
from .context import ComplianceContext, question_for
from .tkdl import PriorArtProbe, ProbeResult, get_probe, probe_terms

log = logging.getLogger(__name__)

DISCLAIMER = (
    "Automated regulatory screening, not legal advice. Every obligation below "
    "must be confirmed against the bare text of the cited provision and with a "
    "registered patent agent or counsel before it is acted on."
)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class ObligationView:
    """An obligation flattened for transport, with its citation and reasoning."""
    id: str
    label: str
    act_name: str
    section: str
    citation: str
    authority: str | None
    deadline: str | None
    deadline_anchor: str | None
    form: str | None
    severity: str
    blocks_grant: bool
    rationale: str
    amendment_note: str
    depends_on: list[str]
    review_status: str
    path: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "act_name": self.act_name,
            "section": self.section,
            "citation": self.citation,
            "authority": self.authority,
            "deadline": self.deadline,
            "deadline_anchor": self.deadline_anchor,
            "form": self.form,
            "severity": self.severity,
            "blocks_grant": self.blocks_grant,
            "rationale": self.rationale,
            "amendment_note": self.amendment_note,
            "depends_on": self.depends_on,
            "review_status": self.review_status,
            "path": self.path,
        }


@dataclass
class ComplianceReport:
    triggered: bool = False
    obligations: list[ObligationView] = field(default_factory=list)
    exemptions: list[dict[str, Any]] = field(default_factory=list)
    inapplicable: list[dict[str, Any]] = field(default_factory=list)
    prior_art: dict[str, Any] | None = None
    open_questions: list[dict[str, str]] = field(default_factory=list)
    regimes: list[str] = field(default_factory=list)
    uncitable_acts: list[str] = field(default_factory=list)
    completeness: float = 0.0
    provisional: bool = True
    disclaimer: str = DISCLAIMER

    @property
    def blocking(self) -> list[ObligationView]:
        return [o for o in self.obligations if o.blocks_grant]

    def headline(self) -> str:
        """One line the answer layer can lead with.

        Written so that the incomplete case never reads like a clean bill of
        health -- 'no obligations' and 'not enough information to know'
        are different sentences.
        """
        critical = [q for q in self.open_questions if q.get("importance") == "critical"]
        if not self.triggered:
            # "Nothing fired" and "nothing fired because nobody told us the
            # facts that decide it" must not share a sentence. The second one
            # read as a clean bill of health is the single most damaging
            # thing this report could say.
            if critical:
                return (
                    "Not enough information to screen for biodiversity or IP-disclosure "
                    "obligations. This is NOT a finding that none apply — the "
                    f"{len(critical)} question(s) below decide it."
                )
            return "No biodiversity or IP-disclosure obligations were triggered by this question."
        blocking = self.blocking
        if blocking:
            head = (
                f"{len(blocking)} obligation(s) must be discharged before the IP right "
                f"can be granted."
            )
        else:
            head = f"{len(self.obligations)} regulatory obligation(s) apply."
        if self.provisional:
            head += " This screening is incomplete pending the questions below."
        return head

    def to_dict(self) -> dict[str, Any]:
        return {
            "triggered": self.triggered,
            "headline": self.headline(),
            "obligations": [o.to_dict() for o in self.obligations],
            "exemptions": self.exemptions,
            "inapplicable": self.inapplicable,
            "prior_art": self.prior_art,
            "open_questions": self.open_questions,
            "regimes": self.regimes,
            "uncitable_acts": self.uncitable_acts,
            "completeness": round(self.completeness, 2),
            "provisional": self.provisional,
            "disclaimer": self.disclaimer,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ABSAssessor:
    def __init__(
        self,
        graph: RegulatoryGraph | None = None,
        probe: PriorArtProbe | None = None,
        corpus_path: str | None = None,
    ) -> None:
        self.graph = graph or get_graph()
        self.probe = probe or get_probe()
        self._uncitable: list[str] = []
        if corpus_path:
            try:
                report = self.graph.validate_against_corpus(corpus_path)
                self._uncitable = report["missing"]
            except (OSError, ValueError) as exc:
                # A missing manifest must not take down query serving. The
                # obligations are still correct; they just cannot be backed
                # by a retrieved chunk, which is what the empty list means.
                log.warning("could not validate graph against corpus: %s", exc)

    # -- public API --------------------------------------------------------

    def assess(self, context: ComplianceContext) -> ComplianceReport:
        context.infer_defaults()
        result: GraphQueryResult = self.graph.query(context.to_dict())

        report = ComplianceReport()
        report.regimes = [r.label for r in result.regimes]

        ordered = self.graph.ordered_plan(result.obligations)
        report.obligations = [self._view(r) for r in ordered]
        report.triggered = bool(report.obligations)

        report.exemptions = [
            {
                "obligation": s.obligation.label,
                "obligation_id": s.obligation.id,
                "exemption": s.exemption.label,
                "citation": s.exemption.legal_basis.as_citation(),
                "note": s.exemption.note,
                "review_status": s.exemption.review_status,
            }
            for s in result.suppressed
        ]

        report.inapplicable = [
            {
                "label": ex.label,
                "citation": ex.legal_basis.as_citation(),
                "note": ex.note,
                "covers": list(ex.suppresses),
                "review_status": ex.review_status,
            }
            for ex in result.inapplicable
        ]

        report.prior_art = self._run_probe(context, ordered)
        report.open_questions = self._questions(context, result)
        report.completeness, report.provisional = self._completeness(context)

        # Only report acts that are actually cited by a fired obligation --
        # listing every uningested act in the whole ontology would bury the
        # one that matters for this answer.
        cited = {o.act_name for o in report.obligations}
        report.uncitable_acts = sorted(cited & set(self._uncitable))

        return report

    def assess_from_classification(
        self,
        classification: Any,
        **facts: Any,
    ) -> ComplianceReport:
        """Convenience entry point for the retrieval path."""
        ctx = ComplianceContext.from_classification(classification, **facts)
        return self.assess(ctx)

    # -- internals ---------------------------------------------------------

    def _view(self, r: ResolvedObligation) -> ObligationView:
        ob = r.obligation
        return ObligationView(
            id=ob.id,
            label=ob.label,
            act_name=ob.legal_basis.act_name,
            section=ob.legal_basis.section,
            citation=r.citation,
            authority=r.authority.label if r.authority else None,
            deadline=r.deadline.label if r.deadline else None,
            deadline_anchor=r.deadline.anchor if r.deadline else None,
            form=ob.form,
            severity=ob.severity,
            blocks_grant=ob.blocks_grant,
            rationale=ob.rationale,
            amendment_note=ob.amendment_note,
            depends_on=list(r.depends_on),
            review_status=ob.review_status,
            path=list(r.path),
        )

    def _run_probe(
        self,
        context: ComplianceContext,
        obligations: Sequence[ResolvedObligation],
    ) -> dict[str, Any] | None:
        """Run the prior-art probe only when an obligation asked for it.

        The `probe: tkdl` marker on the section 3(p) node is what requests
        it, so the ontology decides when a prior-art check is relevant
        rather than this module hardcoding the condition. Adding a second
        probe-backed obligation later needs no change here.
        """
        wants = [r for r in obligations if r.obligation.probe]
        if not wants:
            return None

        terms = probe_terms(context.formulation_name, context.ingredients)
        if not terms:
            return {
                "backend": getattr(self.probe, "name", "unknown"),
                "available": False,
                "risk": "unknown",
                "message": (
                    "Section 3(p) exposure could not be assessed: no formulation "
                    "name or ingredient list was supplied."
                ),
                "hits": [],
                "searched_terms": [],
                "for_obligation": wants[0].obligation.id,
            }

        try:
            result: ProbeResult = self.probe.search(terms)
        except (RuntimeError, NotImplementedError) as exc:
            log.info("prior-art probe unavailable: %s", exc)
            return {
                "backend": getattr(self.probe, "name", "unknown"),
                "available": False,
                "risk": "unknown",
                "message": str(exc),
                "hits": [],
                "searched_terms": terms,
                "for_obligation": wants[0].obligation.id,
            }

        payload = result.to_dict()
        payload["for_obligation"] = wants[0].obligation.id
        return payload

    def _questions(
        self,
        context: ComplianceContext,
        result: GraphQueryResult,
    ) -> list[dict[str, str]]:
        """Turn unresolved trigger fields into ordered follow-up questions.

        Critical fields first: those are the ones that flip a blocking
        obligation on or off, so they are worth the user's attention before
        anything else.
        """
        critical = set(context.missing_critical())
        asked = [f for f in result.unresolved_fields]
        for f in critical:
            if f not in asked:
                asked.append(f)

        ordered = sorted(asked, key=lambda f: (f not in critical, f))
        return [
            {
                "field": f,
                "question": question_for(f),
                "importance": "critical" if f in critical else "clarifying",
            }
            for f in ordered
        ]

    def _completeness(self, context: ComplianceContext) -> tuple[float, bool]:
        """Fraction of the graph's trigger vocabulary the context supplied.

        Weighted so the critical fields dominate: supplying nine incidental
        fields and neither decisive one is not 90% complete in any sense
        that matters.
        """
        wanted = self.graph.context_fields()
        if not wanted:
            return 1.0, False

        supplied = {f for f in wanted if getattr(context, f, None) is not None}
        base = len(supplied) / len(wanted)

        missing_critical = context.missing_critical()
        critical_ratio = 1.0 - (len(missing_critical) / max(1, len(("a", "b"))))
        score = 0.4 * base + 0.6 * max(0.0, critical_ratio)
        return score, bool(missing_critical)


_ASSESSOR: ABSAssessor | None = None


def get_assessor(corpus_path: str | None = None) -> ABSAssessor:
    global _ASSESSOR
    if _ASSESSOR is None:
        _ASSESSOR = ABSAssessor(corpus_path=corpus_path)
    return _ASSESSOR
