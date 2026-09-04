"""
shared/taxonomy.py

Formulation-type -> relevant-act pre-filter.

This is the path both consumers actually import (`ai/store.py` and
`ai/person_b_retrieval/retrieval.py` both do `from ai.shared.taxonomy import
acts_for_formulation`). The file previously sat at
`ai/person_b_retrieval/shared/taxonomy.py`, which no importer referenced, so
both modules raised ModuleNotFoundError at import time and the backend could
not serve a query at all.

What changed beyond the move
----------------------------
The mapping is no longer hand-maintained. It is derived from
`ai/knowledge_graph/ontology.yaml` by walking

    formulation --GOVERNED_BY--> regime --IMPOSES--> obligation --GROUNDED_IN--> act

The old module carried a standing warning that its act-name strings were
provisional and had to be re-verified by hand against `corpus.yaml` on every
ingest. That instruction had no enforcement behind it, so the only question
was when it would be forgotten. Deriving the list removes the duplicate
rather than restating the warning, and
`RegulatoryGraph.validate_against_corpus()` turns the check into something a
test can fail on.

The exact-match constraint is unchanged and still the sharp edge here:
Chroma's metadata `where` filter is exact, not fuzzy, so an act name that
differs by so much as a "The " prefix silently matches zero chunks. The
difference is that the strings now live in one place, next to the legal
basis that justifies them.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Fallback used only if the ontology cannot be loaded. Retrieval degrading to
# jurisdiction-only filtering is recoverable; retrieval failing to import is
# not, and this module sits on the import path of every query.
_FALLBACK: dict[str, list[str]] = {
    "classical": ["The Patents Act, 1970"],
    "proprietary": ["The Patents Act, 1970"],
    "new_drug": ["The Patents Act, 1970"],
    "phytopharmaceutical": ["The Patents Act, 1970"],
    "aahar": [],
    "cosmetic": [],
}

try:
    from ai.knowledge_graph.graph import get_graph

    _graph = get_graph()
    FORMULATION_RELEVANT_ACTS: dict[str, list[str]] = {
        formulation: (_graph.acts_for_formulation(formulation) or [])
        for formulation in _graph.governed_by
    }
    _GRAPH_BACKED = True
except Exception as exc:  # pragma: no cover - defensive
    log.error("regulatory graph unavailable, using fallback taxonomy: %s", exc)
    FORMULATION_RELEVANT_ACTS = dict(_FALLBACK)
    _GRAPH_BACKED = False


def acts_for_formulation(formulation_type: str | None) -> list[str] | None:
    """Acts relevant to a formulation type, or None if there is nothing to
    narrow by.

    None rather than [] is load-bearing: callers must fall back to
    jurisdiction-only filtering. Passing an empty list into a Chroma `$in`
    filter matches nothing, which turns "we have no pre-filter for this"
    into "there is no law about this" -- a wrong answer that looks like a
    confident one.
    """
    if not formulation_type:
        return None
    return FORMULATION_RELEVANT_ACTS.get(formulation_type) or None


def is_graph_backed() -> bool:
    """Whether the taxonomy came from the ontology or the fallback. Exposed
    so a health endpoint can surface silent degradation."""
    return _GRAPH_BACKED
