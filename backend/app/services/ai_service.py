from __future__ import annotations

from dataclasses import asdict
import logging
from pathlib import Path
import sys
from typing import Any

# The AI folder is a sibling of backend/, so add the repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.embedder import Embedder, get_embedder  # noqa: E402
from ai.person_b_retrieval.confidence import compute_confidence, decide_abstain  # noqa: E402
from ai.person_b_retrieval.schema import (  # noqa: E402
    Classification,
    MatchedChunk,
    RetrievalResult,
)
from ai.store import VectorStore  # noqa: E402
from ai.person_c_generation.generate import generate_answer  # noqa: E402
from ai.compliance import get_assessor  # noqa: E402

from ..config import settings  # noqa: E402


class AIService:
    """Application-facing adapter around the existing AI pipeline.

    The backend does not duplicate the team's RAG/generation logic. It
    converts HTTP input into the agreed AI shapes and returns a JSON-safe
    response for the frontend.
    """

    def __init__(self) -> None:
        self._embedder: Embedder | None = None
        self._store: VectorStore | None = None

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = get_embedder(
                settings.embedding_model,
                device=settings.embedding_device,
            )
        return self._embedder

    @property
    def store(self) -> VectorStore:
        if self._store is None:
            self._store = VectorStore(
                settings.chroma_path,
                collection=settings.chroma_collection,
            )
        return self._store

    def corpus_count(self) -> int:
        return self.store.count()

    def retrieve(
        self,
        query: str,
        classification: Classification | None,
        top_k: int,
    ) -> tuple[RetrievalResult, dict[str, dict]]:
        """Query the persistent Chroma index and calculate the team's
        confidence/abstention result without rebuilding the entire corpus.
        """
        jurisdiction = classification.jurisdiction if classification else None
        formulation_type = classification.formulation_type if classification else None

        result = self.store.query(
            query=query,
            embedder=self.embedder,
            jurisdiction=jurisdiction,
            formulation_type=formulation_type,
            top_k=top_k,
        )

        matched = [
            MatchedChunk(
                chunk_id=item["chunk_id"],
                text=item["text"],
                act_name=item["act_name"],
                section=item["section"],
                jurisdiction=item["jurisdiction"],
                similarity_score=item["similarity_score"],
            )
            for item in result["matches"]
        ]
        confidence = compute_confidence(matched)
        should_abstain = decide_abstain(
            confidence, matched, threshold=settings.abstain_threshold
        )

        retrieval = RetrievalResult(
            query=query,
            matched_chunks=matched,
            confidence=confidence,
            should_abstain=should_abstain,
        )
        source_map = {item["chunk_id"]: item for item in result["matches"]}
        return retrieval, source_map

    def compliance(
        self,
        classification: Classification | None,
        facts: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """ABS screening off the same classification retrieval already used.

        Runs on every query rather than behind a separate endpoint. Someone
        who does not know section 6 of the Biological Diversity Act exists
        will never think to ask for an ABS check, and that person is exactly
        who the flag is for.

        Failure here degrades to None rather than propagating: a screening
        that could not run must not take down an answer the user can still
        use. The absent key is the signal; the API never emits an empty
        report that would render as "nothing to worry about".
        """
        if classification is None and not facts:
            return None
        try:
            assessor = get_assessor(str(REPO_ROOT / "ai" / "corpus.yaml"))
            report = assessor.assess_from_classification(
                classification, **(facts or {})
            )
            return report.to_dict()
        except Exception as exc:  # pragma: no cover - defensive
            logging.getLogger(__name__).exception("compliance screening failed: %s", exc)
            return None

    def answer(
        self,
        query: str,
        classification: Classification | None,
        top_k: int,
        compliance_facts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        retrieval, source_map = self.retrieve(query, classification, top_k)

        # If retrieval has already decided the evidence is insufficient, do not
        # spend an LLM call trying to answer it.  This preserves the team's
        # abstention contract and makes the API deterministic/offline for
        # unsupported questions.
        if retrieval.should_abstain:
            from ai.shared.schema import FinalAnswer

            final = FinalAnswer(
                answer_text=(
                    "The provided sources do not clearly answer this question, "
                    "so I can't provide a reliable answer here."
                ),
                citations=[],
                confidence=retrieval.confidence,
                abstained=True,
                disclaimer="This is informational, not legal advice.",
            )
        else:
            final = generate_answer(
                retrieval,
                model=settings.llm_model,
                mock=False,
                api_key=settings.anthropic_api_key,
            )

        # Keep source metadata from retrieval for the UI. Generation uses the
        # existing Shape-3/Shape-4 contract and therefore does not change
        # those team-owned field names.
        sources = []
        for c in retrieval.matched_chunks:
            meta = source_map.get(c.chunk_id, {})
            sources.append({
                "chunk_id": c.chunk_id,
                "act_name": c.act_name,
                "section": c.section,
                "jurisdiction": c.jurisdiction,
                "similarity_score": c.similarity_score,
                "source_url": meta.get("source_url"),
            })

        citations = []
        for c in final.citations:
            url = next(
                (s["source_url"] for s in sources
                 if s["act_name"] == c.act_name and s["section"] == c.section),
                None,
            )
            citations.append({
                "act_name": c.act_name,
                "section": c.section,
                "source_url": url,
            })

        return {
            "answer_text": final.answer_text,
            "citations": citations,
            "confidence": final.confidence,
            "abstained": final.abstained,
            "disclaimer": final.disclaimer,
            "sources": sources,
            # Attached even when retrieval abstained. Abstention means the
            # corpus could not answer the question asked; it says nothing
            # about whether an ABS obligation applies, and those are decided
            # by the graph rather than by retrieval.
            "compliance": self.compliance(classification, compliance_facts),
        }


ai_service = AIService()
