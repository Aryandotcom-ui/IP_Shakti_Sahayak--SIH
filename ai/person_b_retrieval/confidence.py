"""
Confidence scoring and abstention logic.

Kept deliberately simple and swappable — this is the piece most likely to get
smarter later (e.g. factoring in chunk agreement, corpus freshness/version
status, or an LLM-based relevance check). The rest of the pipeline only
depends on compute_confidence() returning a 0-1 float and decide_abstain()
returning a bool, so the internals here can change freely.
"""

import sys
from pathlib import Path
from typing import List

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai.person_b_retrieval.schema import MatchedChunk

ABSTAIN_THRESHOLD = 0.20  # below this confidence, don't answer — say so instead
# NOTE: this threshold is tuned for the TF-IDF char n-gram stand-in embedder,
# which is a much cruder similarity signal than a real sentence-embedding
# model. Re-tune this once embeddings.py is swapped for the real thing —
# expect real embeddings to separate relevant/irrelevant queries far more
# cleanly, so this threshold will likely need to go up.


def compute_confidence(matched_chunks: List[MatchedChunk]) -> float:
    """Confidence = top similarity score, nudged up slightly if multiple
    chunks agree (i.e. more than one relevant chunk was found)."""
    if not matched_chunks:
        return 0.0

    top_score = matched_chunks[0].similarity_score
    agreement_bonus = 0.025 * min(len(matched_chunks) - 1, 2)  # up to +0.05
    confidence = min(top_score + agreement_bonus, 1.0)
    return round(confidence, 4)


def decide_abstain(
    confidence: float,
    matched_chunks: List[MatchedChunk],
    threshold: float = ABSTAIN_THRESHOLD,
) -> bool:
    if not matched_chunks:
        return True
    return confidence < threshold
