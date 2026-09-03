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


ApplicantCategory = Literal[
    "indian_individual", "indian_entity", "foreign_controlled_entity",
    "non_resident_indian", "foreign_national",
]
ResourceOrigin = Literal["india", "outside_india", "mixed"]
ResourceCultivation = Literal["cultivated", "wild_collected", "mixed"]


class ComplianceFacts(BaseModel):
    """Facts the classifier cannot infer but the Biological Diversity Act
    turns on.

    All optional, all defaulting to None. None means "unknown" and produces
    a follow-up question in the response; it must never be read as False.
    Whether the applicant is a section 3(2) person is not something a
    question about a formulation can reveal, so the API has to be able to
    carry it separately and to admit when it has not been told.
    """
    applicant_category: ApplicantCategory | None = None
    resource_origin: ResourceOrigin | None = None
    resource_cultivation: ResourceCultivation | None = None
    practitioner_is_registered_ayush: bool | None = None
    uses_biological_material: bool | None = None
    uses_codified_tk: bool | None = None
    seeking_ipr: bool | None = None
    ipr_already_granted: bool | None = None
    intends_commercialisation: bool | None = None
    formulation_name: str | None = Field(default=None, max_length=200)
    ingredients: list[str] | None = Field(default=None, max_length=50)


class QueryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=3, max_length=4000)
    classification: ClassificationRequest | None = None
    top_k: int = Field(default=5, ge=1, le=10)
    compliance_facts: ComplianceFacts | None = None
    # act_name strings (exact match, see ai/corpus.yaml's `access` field)
    # the requester consents to being answered from if retrieval matches a
    # licensed source. DPDP consent has to be for a specified purpose, so
    # this is a named list, not one blanket "yes to licensed content" flag.
    # No document in the corpus is currently licensed, so this is normally
    # empty — the gate exists for when one is added.
    consent_licensed_acts: list[str] = Field(default_factory=list, max_length=50)


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
    # Left loosely typed on purpose: the shape is owned by
    # ai/compliance and adding an obligation field should not require a
    # coordinated edit here. The AI-layer dataclasses are the contract.
    compliance: dict | None = None
    # act_names whose citation was withheld because retrieval matched a
    # licensed source the request had not consented to (see
    # consent_licensed_acts on QueryRequest and ai/audit.py). Empty in the
    # common case where nothing licensed matched.
    licensed_sources_withheld: list[str] = Field(default_factory=list)
    # The audit_log row id for this query (see ai/audit.py) — carried back
    # so a support/compliance flow can look the request up without a
    # separate correlation id scheme.
    audit_id: str | None = None


class CorpusResponse(BaseModel):
    collection: str
    chunks: int


# ---------------------------------------------------------------------------
# Auto-update pipeline / review gate (ai/updates)
# ---------------------------------------------------------------------------

class ReviewQueueEntry(BaseModel):
    id: str
    source_name: str
    url: str
    act_name: str
    jurisdiction: str | None = None
    tier: str
    reason: str
    status: str
    needs_audit: bool
    created_at: str
    decided_at: str | None = None
    decided_by: str | None = None
    notes: str | None = None
    ingest_result: str | None = None


class ReviewDecisionRequest(BaseModel):
    decided_by: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class CheckNowRequest(BaseModel):
    # Overrides settings.updates_auto_ingest for this one call only.
    # None (default) means "use the configured default".
    auto_ingest: bool | None = None


class CheckNowResponse(BaseModel):
    checked: int
    entries: list[dict]


class PublishResponse(BaseModel):
    ok: bool
    chunks: int | None = None
    embedder: str | None = None
    error: str | None = None
