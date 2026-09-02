"""
Retrieval module.

Two-stage search, matching the pre-filtering approach discussed for the
project: narrow the candidate set using jurisdiction + formulation metadata
BEFORE running semantic similarity search, rather than searching everything
and hoping the right chunk floats to the top.
"""

from typing import List, Optional
import numpy as np

from schema import Chunk, Classification, MatchedChunk, RetrievalResult
from embeddings import Embedder, cosine_sim
from confidence import compute_confidence, decide_abstain

# Simple lookup table mapping a formulation type to the acts most relevant to it.
# This is the "knowledge graph" in its simplest possible form for the MVP —
# a dict today, a real graph structure later. Any act NOT in a formulation's
# list can still be matched, but chunks from listed acts are preferred.
FORMULATION_RELEVANT_ACTS = {
    "classical": ["Patents Act, 1970", "Biological Diversity Act, 2002", "Drugs and Cosmetics Act, 1940"],
    "proprietary": ["Drugs and Cosmetics Act, 1940", "Patents Act, 1970"],
    "new_drug": ["Patents Act, 1970", "Patents Rules, 2003", "Drugs and Cosmetics Act, 1940"],
    "phytopharmaceutical": ["Drugs and Cosmetics Act, 1940", "Patents Act, 1970"],
    "aahar": ["FSSAI Ayurveda Aahar Regulations"],
    "cosmetic": ["Drugs and Cosmetics Act, 1940"],
}

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
        relevant_acts = FORMULATION_RELEVANT_ACTS.get(classification.formulation_type)
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
