from typing import Literal

from pydantic import BaseModel, Field, ConfigDict

Jurisdiction = Literal["india", "international"]
FormulationType = Literal[
    "classical", "proprietary", "new_drug",
    "phytopharmaceutical", "aahar", "cosmetic",
]
SourceOrganism = Literal["plant", "microbial", "animal", "mixed"]


class ClassificationRequest(BaseModel):
    formulation_type: FormulationType | None = None
    source_organism: SourceOrganism | None = None
    jurisdiction: Jurisdiction | None = None


class QueryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=3, max_length=4000)
    classification: ClassificationRequest | None = None
    top_k: int = Field(default=5, ge=1, le=10)


class CitationResponse(BaseModel):
    act_name: str
    section: str
    source_url: str | None = None


class SourceResponse(BaseModel):
    chunk_id: str
    act_name: str
    section: str
    jurisdiction: str
    similarity_score: float
    source_url: str | None = None


class QueryResponse(BaseModel):
    answer_text: str
    citations: list[CitationResponse]
    confidence: float = Field(ge=0, le=1)
    abstained: bool
    disclaimer: str
    sources: list[SourceResponse] = Field(default_factory=list)


class CorpusResponse(BaseModel):
    collection: str
    chunks: int
