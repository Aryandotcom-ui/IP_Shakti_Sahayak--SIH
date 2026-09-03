"""
Retrieval module.

Two-stage search, matching the pre-filtering approach discussed for the
project: narrow the candidate set using jurisdiction + formulation metadata
BEFORE running semantic similarity search, rather than searching everything
and hoping the right chunk floats to the top.
"""

from typing import List, Optional
import numpy as np
import sys
from pathlib import Path

# Absolute imports rooted at the `ai` package — matches how the backend
# (backend/app/services/ai_service.py) imports this module, so this file
# behaves the same whether it's run standalone or loaded by the API.
# Requires the repo root on sys.path, which the two lines below guarantee
# even if this file is executed directly rather than via `-m`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai.person_b_retrieval.schema import Chunk, Classification, MatchedChunk, RetrievalResult
from ai.person_b_retrieval.embeddings import Embedder, cosine_sim
from ai.person_b_retrieval.confidence import compute_confidence, decide_abstain
from ai.shared.taxonomy import acts_for_formulation  # single source of truth,
# shared with the production store.py — see ai/shared/taxonomy.py for why
# this must not be a second copy of the mapping.

MIN_SIMILARITY_FLOOR = 0.05  # below this, a "match" isn't worth returning at all


def filter_chunks(
    chunks: List[Chunk],
    jurisdiction: Optional[str] = None,
    classification: Optional[Classification] = None,
) -> List[Chunk]:
    """Stage 1: narrow the candidate set using metadata, before any semantic search."""
    result = chunks

    if jurisdiction:
        result = [c for c in result if c.jurisdiction == jurisdiction]

    if classification and classification.formulation_type:
        relevant_acts = acts_for_formulation(classification.formulation_type)
        if relevant_acts:
            preferred = [c for c in result if c.act_name in relevant_acts]
            # If narrowing by formulation type leaves nothing, fall back to the
            # jurisdiction-only set rather than returning zero candidates.
            if preferred:
                result = preferred

    return result


def retrieve(
    query: str,
    all_chunks: List[Chunk],
    embedder: Embedder,
    jurisdiction: Optional[str] = None,
    classification: Optional[Classification] = None,
    top_k: int = 3,
) -> RetrievalResult:
    """Stage 1 (filter) + Stage 2 (semantic search) + confidence scoring."""

    candidates = filter_chunks(all_chunks, jurisdiction=jurisdiction, classification=classification)

    if not candidates:
        return RetrievalResult(query=query, matched_chunks=[], confidence=0.0, should_abstain=True)

    candidate_vectors = embedder.embed([c.text for c in candidates])
    query_vector = embedder.embed([query])
    sims = cosine_sim(query_vector, candidate_vectors)[0]  # shape (n_candidates,)

    ranked_idx = np.argsort(sims)[::-1][:top_k]

    matched: List[MatchedChunk] = []
    for i in ranked_idx:
        score = float(sims[i])
        if score < MIN_SIMILARITY_FLOOR:
            continue
        c = candidates[i]
        matched.append(
            MatchedChunk(
                chunk_id=c.chunk_id,
                text=c.text,
                act_name=c.act_name,
                section=c.section,
                jurisdiction=c.jurisdiction,
                similarity_score=round(score, 4),
            )
        )

    confidence = compute_confidence(matched)
    abstain = decide_abstain(confidence, matched)

    return RetrievalResult(
        query=query,
        matched_chunks=matched,
        confidence=confidence,
        should_abstain=abstain,
    )
