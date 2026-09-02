"""
shared/schema.py

Dataclasses for the 4 shapes that flow through the AI pipeline.
Written together on Day 0 — do not change field names/types after that
without re-syncing with the other two people, since A -> B -> C all
depend on these exact shapes.

    Shape 1: Chunk              (Person A produces, Person B consumes)
    Shape 2: Classification     (fixed test input for Person B)
    Shape 3: RetrievalResult    (Person B produces, Person C consumes)
    Shape 4: FinalAnswer        (Person C produces — end output)
"""

from dataclasses import dataclass, field, asdict
from typing import List, Literal, Optional


# ---------------------------------------------------------------------------
# Shape 1 — chunk
# ---------------------------------------------------------------------------

Jurisdiction = Literal["india", "international"]
InstrumentType = Literal["statute", "rule", "treaty", "case_law"]


@dataclass
class Chunk:
    chunk_id: str
    text: str
    jurisdiction: Jurisdiction
    instrument_type: InstrumentType
    act_name: str
    section: str
    effective_date: str  # "YYYY-MM-DD"
    source_url: str

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Chunk":
        return Chunk(**d)


# ---------------------------------------------------------------------------
# Shape 2 — classification
# ---------------------------------------------------------------------------

FormulationType = Literal[
    "classical", "proprietary", "new_drug", "phytopharmaceutical", "aahar", "cosmetic"
]
SourceOrganism = Literal["plant", "microbial", "animal", "mixed"]


@dataclass
class Classification:
    formulation_type: FormulationType
    source_organism: SourceOrganism
    jurisdiction: Jurisdiction

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Classification":
        return Classification(**d)


# ---------------------------------------------------------------------------
# Shape 3 — retrieval_result
# ---------------------------------------------------------------------------

@dataclass
class MatchedChunk:
    chunk_id: str
    text: str
    act_name: str
    section: str
    jurisdiction: str
    similarity_score: float

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "MatchedChunk":
        return MatchedChunk(**d)


@dataclass
class RetrievalResult:
    query: str
    matched_chunks: List[MatchedChunk]
    confidence: float
    should_abstain: bool

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "matched_chunks": [c.to_dict() for c in self.matched_chunks],
            "confidence": self.confidence,
            "should_abstain": self.should_abstain,
        }

    @staticmethod
    def from_dict(d: dict) -> "RetrievalResult":
        return RetrievalResult(
            query=d["query"],
            matched_chunks=[MatchedChunk.from_dict(c) for c in d["matched_chunks"]],
            confidence=d["confidence"],
            should_abstain=d["should_abstain"],
        )


# ---------------------------------------------------------------------------
# Shape 4 — final_answer
# ---------------------------------------------------------------------------

@dataclass
class Citation:
    act_name: str
    section: str
    source_url: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Citation":
        return Citation(**d)


@dataclass
class FinalAnswer:
    answer_text: str
    citations: List[Citation] = field(default_factory=list)
    confidence: float = 0.0
    abstained: bool = False
    disclaimer: str = "This is informational, not legal advice."

    def to_dict(self) -> dict:
        return {
            "answer_text": self.answer_text,
            "citations": [c.to_dict() for c in self.citations],
            "confidence": self.confidence,
            "abstained": self.abstained,
            "disclaimer": self.disclaimer,
        }

    @staticmethod
    def from_dict(d: dict) -> "FinalAnswer":
        return FinalAnswer(
            answer_text=d["answer_text"],
            citations=[Citation.from_dict(c) for c in d.get("citations", [])],
            confidence=d.get("confidence", 0.0),
            abstained=d.get("abstained", False),
            disclaimer=d.get("disclaimer", "This is informational, not legal advice."),
        )
