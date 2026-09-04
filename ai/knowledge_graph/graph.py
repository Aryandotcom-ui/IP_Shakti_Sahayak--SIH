"""
knowledge_graph/graph.py

Loads ontology.yaml into a small typed graph and answers multi-hop queries
over it.

Why a graph and not the dict this replaces
------------------------------------------
`FORMULATION_RELEVANT_ACTS` answered exactly one question: which acts should
I filter the vector search by. It could not answer "what do I actually have
to DO", "in what order", "who do I file it with", "by when", or "why" --
because a formulation-to-act edge throws away everything in between.

The graph keeps the intermediate nodes:

    formulation --GOVERNED_BY--> regime --IMPOSES--> obligation
                                                       |
                                        +--------------+--------------+
                                        |              |              |
                                   DUE_BY         ENFORCED_BY    GROUNDED_IN
                                        |              |              |
                                    deadline       authority     legal_basis
                                                                       |
                                                              (act_name, section)
                                                                       |
                                                        resolves into the corpus

and adds two edge types a tree could not carry: `PRECEDES` between
obligations (ordering), and `SUPPRESSES` from exemptions to obligations
(defeasibility). Legal reasoning is defeasible -- a rule applies unless an
exemption removes it -- so an engine that can only add conclusions models
the domain wrongly.

The act filter still falls out of this: `acts_for_formulation()` walks
formulation -> regimes -> obligations -> legal_basis.act_name. One source of
truth, derived rather than maintained.

No third-party graph library. The ontology is small (tens of nodes) and
adding networkx to a hackathon deployment for a BFS over 60 nodes is not a
trade worth making.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

log = logging.getLogger(__name__)

ONTOLOGY_PATH = Path(__file__).with_name("ontology.yaml")

Severity = str  # "blocking" | "mandatory" | "advisory"

_SEVERITY_ORDER: dict[str, int] = {"blocking": 0, "mandatory": 1, "advisory": 2}


class OntologyError(ValueError):
    """The ontology file is internally inconsistent."""


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LegalBasis:
    act_name: str
    section: str

    def as_citation(self) -> str:
        return f"{self.act_name}, {self.section}"


@dataclass(frozen=True)
class Deadline:
    id: str
    label: str
    anchor: str
    offset_days: int

    @property
    def is_precondition(self) -> bool:
        """A negative offset means the duty must be discharged before the
        anchor event, i.e. it gates that event rather than following it."""
        return self.offset_days < 0


@dataclass(frozen=True)
class Authority:
    id: str
    label: str
    jurisdiction: str


@dataclass(frozen=True)
class Regime:
    id: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class Obligation:
    id: str
    regime: str
    label: str
    legal_basis: LegalBasis
    authority: str | None
    deadline: str | None
    trigger: Mapping[str, Any]
    severity: Severity = "mandatory"
    blocks_grant: bool = False
    form: str | None = None
    rationale: str = ""
    amendment_note: str = ""
    linked_risk: str = ""
    probe: str | None = None
    review_status: str = "draft"


@dataclass(frozen=True)
class Exemption:
    id: str
    label: str
    legal_basis: LegalBasis
    suppresses: tuple[str, ...]
    trigger: Mapping[str, Any]
    note: str = ""
    review_status: str = "draft"


# ---------------------------------------------------------------------------
# Query results
# ---------------------------------------------------------------------------

@dataclass
class ResolvedObligation:
    """An obligation that fired, with the path that produced it.

    `path` exists so the UI can show why a duty was raised. An unexplained
    compliance flag in a regulated domain is not usable output -- the user
    has to be able to check the reasoning, and a reviewer has to be able to
    find the wrong edge when it is wrong.
    """
    obligation: Obligation
    path: tuple[str, ...]
    deadline: Deadline | None
    authority: Authority | None
    depends_on: tuple[str, ...] = ()

    @property
    def citation(self) -> str:
        return self.obligation.legal_basis.as_citation()


@dataclass
class SuppressedObligation:
    obligation: Obligation
    exemption: Exemption


@dataclass
class GraphQueryResult:
    obligations: list[ResolvedObligation] = field(default_factory=list)
    suppressed: list[SuppressedObligation] = field(default_factory=list)
    regimes: list[Regime] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)
    # Exemptions whose trigger fired but which suppressed nothing, because
    # the obligations they cover had not fired either. Not redundant: this
    # is what lets the report explain a NEGATIVE finding. "The Biological
    # Diversity Act does not apply, because the resource was not accessed
    # from India" is a far more useful and more checkable answer than
    # silence, and silence is what a suppression-only model produces.
    inapplicable: list["Exemption"] = field(default_factory=list)

    @property
    def blocking(self) -> list[ResolvedObligation]:
        return [o for o in self.obligations if o.obligation.blocks_grant]


# ---------------------------------------------------------------------------
# Predicate evaluation
# ---------------------------------------------------------------------------

_MISSING = object()


def _evaluate(
    node: Mapping[str, Any],
    context: Mapping[str, Any],
    unresolved: list[str],
) -> bool:
    """Evaluate a declarative predicate tree against a context.

    Grammar, intentionally tiny:

        {"all": [...]}                 every child must hold
        {"any": [...]}                 at least one child must hold
        {"field": f, "equals": v}      context[f] == v
        {"field": f, "in": [...]}      context[f] in [...]
        {"field": f, "not_equals": v}  context[f] != v

    A field the context does not supply evaluates FALSE and is recorded in
    `unresolved`. That is the cautious direction for a
    precondition-shaped rule, but it means a caller who omits a field gets
    silence rather than a warning -- hence the list, which the ABS layer
    turns into "answer this to complete the assessment" questions. Missing
    input should produce a question, not a confident negative.
    """
    if "all" in node:
        results = [_evaluate(c, context, unresolved) for c in node["all"]]
        return all(results)
    if "any" in node:
        results = [_evaluate(c, context, unresolved) for c in node["any"]]
        return any(results)

    field_name = node.get("field")
    if field_name is None:
        raise OntologyError(f"predicate has neither all/any nor field: {node!r}")

    value = context.get(field_name, _MISSING)
    if value is _MISSING or value is None:
        if field_name not in unresolved:
            unresolved.append(field_name)
        return False

    if "equals" in node:
        return value == node["equals"]
    if "not_equals" in node:
        return value != node["not_equals"]
    if "in" in node:
        return value in node["in"]

    raise OntologyError(f"predicate on {field_name!r} has no comparison: {node!r}")


def _predicate_fields(node: Mapping[str, Any]) -> set[str]:
    """Every context field a predicate tree can read. Used to check that a
    caller's context vocabulary matches the ontology's."""
    out: set[str] = set()
    for key in ("all", "any"):
        for child in node.get(key, []):
            out |= _predicate_fields(child)
    if "field" in node:
        out.add(node["field"])
    return out


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

class RegulatoryGraph:
    def __init__(self, data: Mapping[str, Any]) -> None:
        self.meta: dict[str, Any] = dict(data.get("meta") or {})

        self.authorities: dict[str, Authority] = {
            k: Authority(id=k, label=v["label"], jurisdiction=v.get("jurisdiction", "india"))
            for k, v in (data.get("authorities") or {}).items()
        }
        self.regimes: dict[str, Regime] = {
            k: Regime(id=k, label=v["label"], description=v.get("description", ""))
            for k, v in (data.get("regimes") or {}).items()
        }
        self.deadlines: dict[str, Deadline] = {
            k: Deadline(
                id=k,
                label=v["label"],
                anchor=v["anchor"],
                offset_days=int(v["offset_days"]),
            )
            for k, v in (data.get("deadlines") or {}).items()
        }
        self.governed_by: dict[str, tuple[str, ...]] = {
            k: tuple(v) for k, v in (data.get("governed_by") or {}).items()
        }
        self.precedes: dict[str, tuple[str, ...]] = {
            k: tuple(v) for k, v in (data.get("precedes") or {}).items()
        }

        self.obligations: dict[str, Obligation] = {}
        for k, v in (data.get("obligations") or {}).items():
            basis = v.get("legal_basis") or {}
            self.obligations[k] = Obligation(
                id=k,
                regime=v["regime"],
                label=v["label"],
                legal_basis=LegalBasis(
                    act_name=basis.get("act_name", ""),
                    section=basis.get("section", ""),
                ),
                authority=v.get("authority"),
                deadline=v.get("deadline"),
                trigger=v.get("trigger") or {"all": []},
                severity=v.get("severity", "mandatory"),
                blocks_grant=bool(v.get("blocks_grant", False)),
                form=v.get("form"),
                rationale=(v.get("rationale") or "").strip(),
                amendment_note=(v.get("amendment_note") or "").strip(),
                linked_risk=(v.get("linked_risk") or "").strip(),
                probe=v.get("probe"),
                review_status=v.get("review_status", "draft"),
            )

        self.exemptions: dict[str, Exemption] = {}
        for k, v in (data.get("exemptions") or {}).items():
            basis = v.get("legal_basis") or {}
            self.exemptions[k] = Exemption(
                id=k,
                label=v["label"],
                legal_basis=LegalBasis(
                    act_name=basis.get("act_name", ""),
                    section=basis.get("section", ""),
                ),
                suppresses=tuple(v.get("suppresses") or ()),
                trigger=v.get("trigger") or {"all": []},
                note=(v.get("note") or "").strip(),
                review_status=v.get("review_status", "draft"),
            )

        # Reverse index: regime -> obligations it imposes.
        self._by_regime: dict[str, list[str]] = {}
        for oid, ob in self.obligations.items():
            self._by_regime.setdefault(ob.regime, []).append(oid)

        self.check_integrity()

    # -- construction ------------------------------------------------------

    @classmethod
    def load(cls, path: Path | str | None = None) -> "RegulatoryGraph":
        p = Path(path) if path else ONTOLOGY_PATH
        with open(p, "r", encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh) or {})

    # -- validation --------------------------------------------------------

    def check_integrity(self) -> None:
        """Dangling references are a silent-wrong-answer bug, not a crash:
        an obligation pointing at a regime nothing reaches simply never
        fires. Fail loudly at load instead."""
        errors: list[str] = []

        for f, regimes in self.governed_by.items():
            for r in regimes:
                if r not in self.regimes:
                    errors.append(f"governed_by[{f}] -> unknown regime {r!r}")

        for oid, ob in self.obligations.items():
            if ob.regime not in self.regimes:
                errors.append(f"obligation {oid} -> unknown regime {ob.regime!r}")
            if ob.authority and ob.authority not in self.authorities:
                errors.append(f"obligation {oid} -> unknown authority {ob.authority!r}")
            if ob.deadline and ob.deadline not in self.deadlines:
                errors.append(f"obligation {oid} -> unknown deadline {ob.deadline!r}")
            if ob.severity not in _SEVERITY_ORDER:
                errors.append(f"obligation {oid} -> unknown severity {ob.severity!r}")
            if not ob.legal_basis.act_name or not ob.legal_basis.section:
                errors.append(f"obligation {oid} has an incomplete legal_basis")

        for eid, ex in self.exemptions.items():
            for target in ex.suppresses:
                if target not in self.obligations:
                    errors.append(f"exemption {eid} suppresses unknown obligation {target!r}")

        for src, targets in self.precedes.items():
            if src not in self.obligations:
                errors.append(f"precedes has unknown source {src!r}")
            for t in targets:
                if t not in self.obligations:
                    errors.append(f"precedes[{src}] -> unknown obligation {t!r}")

        if errors:
            raise OntologyError("; ".join(errors))

    def context_fields(self) -> set[str]:
        """Every field any trigger can read."""
        out: set[str] = set()
        for ob in self.obligations.values():
            out |= _predicate_fields(ob.trigger)
        for ex in self.exemptions.values():
            out |= _predicate_fields(ex.trigger)
        return out

    def validate_against_corpus(self, corpus_path: Path | str) -> dict[str, list[str]]:
        """Check every legal_basis against the act_names in corpus.yaml.

        This is the mechanism that stops the drift `taxonomy.py` warned
        about. An obligation whose act has not been ingested still fires --
        the duty exists in law whether or not we have the PDF -- but it
        cannot be backed by a retrieved citation, and the caller needs to
        know which of those two situations it is in. Silently degrading an
        uncitable obligation to a citable-looking one is the failure mode
        worth engineering against.

        Returns {"ingested": [...], "missing": [...]} of act names.
        """
        with open(Path(corpus_path), "r", encoding="utf-8") as fh:
            manifest = yaml.safe_load(fh) or {}

        docs = manifest.get("documents") or []
        # Presence in the manifest is not the same as being searchable. An
        # entry with status `pending` is an acquisition note, and treating it
        # as ingested would report an obligation as citable when no chunk
        # backs it — the exact failure this check exists to catch.
        ingested = {
            d["act_name"] for d in docs
            if d.get("act_name") and d.get("status", "ingested") == "ingested"
        }
        listed = {d["act_name"] for d in docs if d.get("act_name")}

        referenced = {ob.legal_basis.act_name for ob in self.obligations.values()}
        referenced |= {ex.legal_basis.act_name for ex in self.exemptions.values()}

        missing = sorted(referenced - ingested)
        unlisted = sorted(referenced - listed)
        if unlisted:
            # Referenced by the graph and not even planned for. This is the
            # drift case: a typo in either file lands here.
            log.error(
                "%d act(s) cited by the graph are absent from corpus.yaml entirely "
                "(likely an act_name mismatch): %s",
                len(unlisted), ", ".join(unlisted),
            )
        elif missing:
            log.warning(
                "%d act(s) cited by the graph are listed but not yet ingested: %s",
                len(missing), ", ".join(missing),
            )
        return {
            "ingested": sorted(referenced & ingested),
            "missing": missing,
            "unlisted": unlisted,
        }

    # -- traversal ---------------------------------------------------------

    def regimes_for(self, formulation_type: str | None) -> list[Regime]:
        if not formulation_type:
            return []
        return [self.regimes[r] for r in self.governed_by.get(formulation_type, ())]

    def acts_for_formulation(self, formulation_type: str | None) -> list[str] | None:
        """formulation -> regimes -> obligations -> distinct act names.

        Replaces the hand-maintained FORMULATION_RELEVANT_ACTS dict. Returns
        None (not []) when there is nothing to narrow by, because the caller
        must fall back to jurisdiction-only filtering rather than filter on
        an empty set and retrieve nothing.
        """
        regimes = self.governed_by.get(formulation_type or "", ())
        if not regimes:
            return None

        acts: list[str] = []
        for r in regimes:
            for oid in self._by_regime.get(r, ()):
                act = self.obligations[oid].legal_basis.act_name
                if act and act not in acts:
                    acts.append(act)
        return acts or None

    def query(self, context: Mapping[str, Any]) -> GraphQueryResult:
        """Walk formulation -> regime -> obligation, apply triggers, then
        apply exemptions. Order matters: an exemption can only suppress an
        obligation that fired."""
        result = GraphQueryResult()
        unresolved: list[str] = []

        formulation = context.get("formulation_type")
        regime_ids = self.governed_by.get(formulation or "", ())
        result.regimes = [self.regimes[r] for r in regime_ids]

        fired: dict[str, ResolvedObligation] = {}
        for rid in regime_ids:
            for oid in self._by_regime.get(rid, ()):
                ob = self.obligations[oid]
                if not _evaluate(ob.trigger, context, unresolved):
                    continue
                fired[oid] = ResolvedObligation(
                    obligation=ob,
                    path=(f"formulation:{formulation}", f"regime:{rid}", f"obligation:{oid}"),
                    deadline=self.deadlines.get(ob.deadline) if ob.deadline else None,
                    authority=self.authorities.get(ob.authority) if ob.authority else None,
                )

        # Defeasibility pass.
        for ex in self.exemptions.values():
            if not _evaluate(ex.trigger, context, unresolved):
                continue
            hit = False
            for target in ex.suppresses:
                if target in fired:
                    result.suppressed.append(
                        SuppressedObligation(obligation=fired.pop(target).obligation, exemption=ex)
                    )
                    hit = True
            if not hit:
                result.inapplicable.append(ex)

        # Ordering: only keep predecessors that actually fired, so a
        # dependency suppressed by an exemption does not resurface as a
        # phantom prerequisite.
        for oid, resolved in fired.items():
            deps = [
                src for src, targets in self.precedes.items()
                if oid in targets and src in fired
            ]
            resolved.depends_on = tuple(deps)

        result.obligations = sorted(
            fired.values(),
            key=lambda r: (
                _SEVERITY_ORDER.get(r.obligation.severity, 99),
                not r.obligation.blocks_grant,
                r.obligation.id,
            ),
        )
        result.unresolved_fields = unresolved
        return result

    def ordered_plan(self, resolved: Sequence[ResolvedObligation]) -> list[ResolvedObligation]:
        """Topologically sort fired obligations by PRECEDES.

        Cycles are broken rather than raised: a bad edge in a
        domain-editable file should degrade the ordering, not take the
        query path down.
        """
        by_id = {r.obligation.id: r for r in resolved}
        out: list[ResolvedObligation] = []
        seen: set[str] = set()
        stack: set[str] = set()

        def visit(oid: str) -> None:
            if oid in seen or oid not in by_id:
                return
            if oid in stack:
                log.warning("cycle in precedes at %s; breaking", oid)
                return
            stack.add(oid)
            for dep in by_id[oid].depends_on:
                visit(dep)
            stack.discard(oid)
            seen.add(oid)
            out.append(by_id[oid])

        for r in resolved:
            visit(r.obligation.id)
        return out


_GRAPH: RegulatoryGraph | None = None


def get_graph(path: Path | str | None = None) -> RegulatoryGraph:
    """Process-wide singleton. The ontology is read-only at runtime and
    parsing it per request is pure waste in a request-serving process."""
    global _GRAPH
    if _GRAPH is None or path is not None:
        _GRAPH = RegulatoryGraph.load(path)
    return _GRAPH
