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
from ai.audit import AuditLog  # noqa: E402
from ai.translation import (  # noqa: E402
    Translator,
    get_translator,
    translate_answer_from_english,
    translate_query_to_english,
)

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
        self._audit: AuditLog | None = None
        self._translator: Translator | None = None

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

    @property
    def audit(self) -> AuditLog:
        if self._audit is None:
            self._audit = AuditLog(
                settings.audit_db_path,
                corpus_path=settings.corpus_manifest_path,
            )
        return self._audit

    @property
    def translator(self) -> Translator:
        if self._translator is None:
            self._translator = get_translator(
                settings.bhashini_api_key, settings.bhashini_user_id
            )
        return self._translator

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
        consented_acts: set[str] | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        jurisdiction = classification.jurisdiction if classification else None
        formulation_type = classification.formulation_type if classification else None

        # Translate to English before retrieval — ai/embedder.py's default
        # model is English-only, so this is what makes retrieval work at
        # all for a non-English query, not a UX nicety. See
        # ai/translation.py's module docstring. `language` here is the
        # caller-supplied or detected source language; retrieval and
        # generation run on the English text throughout, and the answer
        # translates back to this language at the very end.
        query_translation = translate_query_to_english(
            query, translator=self.translator, language=language
        )
        source_language = query_translation.source_lang
        english_query = query_translation.text

        try:
            retrieval, source_map = self.retrieve(english_query, classification, top_k)

            # If retrieval has already decided the evidence is insufficient, do
            # not spend an LLM call trying to answer it. This preserves the
            # team's abstention contract and makes the API deterministic/
            # offline for unsupported questions.
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

            # Keep source metadata from retrieval for the UI. Generation uses
            # the existing Shape-3/Shape-4 contract and therefore does not
            # change those team-owned field names.
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

            # Withhold any citation/source drawn from a licensed act the
            # request hasn't consented to. See ai/audit.py — this never
            # touches retrieval itself (the model can still reason over a
            # licensed chunk's text), only what is disclosed in the response.
            gate = self.audit.gate_citations(
                {s["act_name"] for s in sources}, consented_acts=consented_acts
            )
            if gate.licensed_withheld:
                withheld = set(gate.licensed_withheld)
                sources = [s for s in sources if s["act_name"] not in withheld]
                citations = [c for c in citations if c["act_name"] not in withheld]

            audit_id = self._log_query_safe(
                query_text=query,
                jurisdiction=jurisdiction,
                formulation_type=formulation_type,
                top_k=top_k,
                matched_chunk_ids=[c.chunk_id for c in retrieval.matched_chunks],
                confidence=final.confidence,
                should_abstain=final.abstained,
                citations=citations,
                gate=gate,
                disclaimer_shown=bool(final.disclaimer),
                llm_model=None if final.abstained else settings.llm_model,
            )

            # Translate the prose back to the requester's language. Never
            # touches citations/sources — act_name is a legal identifier,
            # not prose, and translating it would break the exact-match
            # contract ai/corpus.yaml's header describes.
            answer_translation = translate_answer_from_english(
                final.answer_text, translator=self.translator, target_lang=source_language
            )
            disclaimer_translation = translate_answer_from_english(
                final.disclaimer, translator=self.translator, target_lang=source_language
            )

            return {
                "answer_text": answer_translation.text,
                "citations": citations,
                "confidence": final.confidence,
                "abstained": final.abstained,
                "disclaimer": disclaimer_translation.text,
                "sources": sources,
                # Attached even when retrieval abstained. Abstention means the
                # corpus could not answer the question asked; it says nothing
                # about whether an ABS obligation applies, and those are
                # decided by the graph rather than by retrieval.
                "compliance": self.compliance(classification, compliance_facts),
                "licensed_sources_withheld": gate.licensed_withheld,
                "audit_id": audit_id,
                "language": source_language,
                # False means the text above is still English because no
                # translation backend is configured or it failed — the
                # answer is still correct, just not delivered in the
                # requester's language. See ai/translation.py.
                "translated": answer_translation.translated,
            }
        except Exception as exc:
            # A query that blew up is exactly the kind of event an audit
            # trail exists to capture — log it (best-effort) and let the
            # caller's own error handling take it from here.
            self._log_query_safe(
                query_text=query,
                jurisdiction=jurisdiction,
                formulation_type=formulation_type,
                top_k=top_k,
                matched_chunk_ids=[],
                confidence=None,
                should_abstain=True,
                citations=[],
                gate=None,
                disclaimer_shown=False,
                llm_model=None,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

    def _log_query_safe(self, **kwargs: Any) -> str | None:
        """Write an audit row without letting a logging failure take down
        the request it is trying to record. The absent audit_id is the
        signal something is wrong with the audit store itself, which is an
        operational problem to alert on, not a reason to refuse an answer
        the user can still use."""
        try:
            return self.audit.log_query(**kwargs)
        except Exception:  # pragma: no cover - defensive
            logging.getLogger(__name__).exception("audit logging failed")
            return None


ai_service = AIService()
