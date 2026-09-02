"""
Shared data shapes for the retrieval module.

These match exactly the JSON contract agreed with Person A (chunk producer)
and Person C (answer generator). Do not change field names without updating
the contract doc and telling the other two people.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Literal

Jurisdiction = Literal["india", "international"]
InstrumentType = Literal["statute", "rule", "treaty", "case_law"]
FormulationType = Literal[
    "classical", "proprietary", "new_drug", "phytopharmaceutical", "aahar", "cosmetic"
]
SourceOrganism = Literal["plant", "microbial", "animal", "mixed"]


@dataclass
class Chunk:
    """Shape 1 — what Person A's ingestion pipeline produces."""

    chunk_id: str
    text: str
    jurisdiction: Jurisdiction
    instrument_type: InstrumentType
    act_name: str
    section: str
    effective_date: str
    source_url: str

    @staticmethod
    def from_dict(d: dict) -> "Chunk":
        return Chunk(
            chunk_id=d["chunk_id"],
            text=d["text"],
            jurisdiction=d["jurisdiction"],
            instrument_type=d["instrument_type"],
            act_name=d["act_name"],
            section=d["section"],
            effective_date=d["effective_date"],
            source_url=d["source_url"],
        )


@dataclass
class Classification:
    """Shape 2 — the formulation-classification result. May be partially filled."""

    formulation_type: Optional[FormulationType] = None
    source_organism: Optional[SourceOrganism] = None
    jurisdiction: Optional[Jurisdiction] = None


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


@dataclass
class RetrievalResult:
    """Shape 3 — what this module hands to Person C."""

    query: str
    matched_chunks: List[MatchedChunk] = field(default_factory=list)
    confidence: float = 0.0
    should_abstain: bool = True

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "matched_chunks": [c.to_dict() for c in self.matched_chunks],
            "confidence": round(self.confidence, 4),
            "should_abstain": self.should_abstain,
        }
