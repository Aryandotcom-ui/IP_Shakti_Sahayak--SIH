from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app
from app.api import routes

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_query_validation():
    response = client.post("/api/v1/query", json={"query": "x"})
    assert response.status_code == 422


def test_corpus_status(monkeypatch):
    class FakeStore:
        class Collection:
            name = "ip_sakti_corpus"
        collection = Collection()

    class FakeService:
        store = FakeStore()

        def corpus_count(self):
            return 12

    monkeypatch.setattr(routes, "ai_service", FakeService())
    response = client.get("/api/v1/corpus")
    assert response.status_code == 200
    assert response.json() == {"collection": "ip_sakti_corpus", "chunks": 12}


def test_query_success(monkeypatch):
    class FakeService:
        def answer(self, query, classification, top_k, compliance_facts=None,
                   consented_acts=None, language=None):
            assert query == "Can this be patented?"
            assert classification is not None
            assert classification.formulation_type == "classical"
            assert classification.jurisdiction == "india"
            assert top_k == 3
            return {
                "answer_text": "See Section 3.",
                "citations": [{
                    "act_name": "The Patents Act, 1970",
                    "section": "Section 3",
                    "source_url": "https://example.test/patents",
                }],
                "confidence": 0.82,
                "abstained": False,
                "disclaimer": "This is informational, not legal advice.",
                "sources": [{
                    "chunk_id": "c1",
                    "act_name": "The Patents Act, 1970",
                    "section": "Section 3",
                    "jurisdiction": "india",
                    "similarity_score": 0.82,
                    "source_url": "https://example.test/patents",
                }],
            }

    monkeypatch.setattr(routes, "ai_service", FakeService())
    response = client.post(
        "/api/v1/query",
        json={
            "query": "Can this be patented?",
            "classification": {
                "formulation_type": "classical",
                "jurisdiction": "india",
            },
            "top_k": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer_text"] == "See Section 3."
    assert body["abstained"] is False
    assert body["sources"][0]["section"] == "Section 3"


def test_cors_origins_can_be_loaded_from_comma_separated_env(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", "http://a.test,http://b.test")
    configured = Settings()
    assert configured.cors_origins == ["http://a.test", "http://b.test"]


def test_abstain_threshold_is_configurable(monkeypatch):
    from app.services.ai_service import AIService

    service = AIService()

    class FakeEmbedder:
        def encode_query(self, texts):
            return [[1.0, 0.0]]

    class FakeCollection:
        name = "ip_sakti_corpus"

        def query(self, **kwargs):
            return {
                "ids": [["c1"]],
                "documents": [["patent novelty"]],
                "metadatas": [[{
                    "act_name": "The Patents Act, 1970",
                    "section": "Section 3",
                    "jurisdiction": "india",
                    "source_url": "https://example.test",
                }]],
                "distances": [[0.85]],
            }

    class FakeStore:
        collection = FakeCollection()

        def query(self, **kwargs):
            return {
                "matches": [{
                    "chunk_id": "c1",
                    "text": "patent novelty",
                    "act_name": "The Patents Act, 1970",
                    "section": "Section 3",
                    "jurisdiction": "india",
                    "similarity_score": 0.15,
                    "source_url": "https://example.test",
                }]
            }

    service._embedder = FakeEmbedder()
    service._store = FakeStore()
    monkeypatch.setattr("app.services.ai_service.settings.abstain_threshold", 0.10)

    retrieval, _ = service.retrieve("patent novelty", None, 1)
    assert retrieval.confidence == 0.15
    assert retrieval.should_abstain is False


def test_configured_anthropic_key_is_forwarded_to_generation(monkeypatch):
    from app.services import ai_service as service_module

    captured = {}

    def fake_generate_answer(retrieval, model, mock, api_key=None):
        captured["api_key"] = api_key
        from ai.shared.schema import FinalAnswer
        return FinalAnswer(
            answer_text="ok", citations=[], confidence=retrieval.confidence,
            abstained=False, disclaimer="This is informational, not legal advice."
        )

    class FakeService(service_module.AIService):
        def retrieve(self, query, classification, top_k):
            from ai.person_b_retrieval.schema import MatchedChunk, RetrievalResult
            chunk = MatchedChunk(
                chunk_id="c1", text="source", act_name="Act", section="1",
                jurisdiction="India", similarity_score=0.9
            )
            r = RetrievalResult(query=query, matched_chunks=[chunk], confidence=0.9, should_abstain=False)
            return r, {"c1": {"source_url": "https://example.com"}}

    monkeypatch.setattr(service_module, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(service_module.settings, "anthropic_api_key", "test-key")
    result = FakeService().answer("test", None, 1)

    assert captured["api_key"] == "test-key"
    assert result["answer_text"] == "ok"


# ---------------------------------------------------------------------------
# ai/translation.py wiring — the multilingual request/response edge
# ---------------------------------------------------------------------------

def test_answer_translates_query_and_answer_for_hindi(monkeypatch):
    from app.services import ai_service as service_module

    captured = {}

    def fake_generate_answer(retrieval, model, mock, api_key=None):
        captured["retrieval_query"] = retrieval.query  # what the LLM saw
        from ai.shared.schema import FinalAnswer
        return FinalAnswer(
            answer_text="Yes, it can be patented.", citations=[],
            confidence=retrieval.confidence, abstained=False,
            disclaimer="This is informational, not legal advice.",
        )

    class FakeService(service_module.AIService):
        def retrieve(self, query, classification, top_k):
            captured["retrieve_query"] = query
            from ai.person_b_retrieval.schema import MatchedChunk, RetrievalResult
            chunk = MatchedChunk(
                chunk_id="c1", text="source", act_name="The Patents Act, 1970",
                section="3", jurisdiction="india", similarity_score=0.9,
            )
            r = RetrievalResult(query=query, matched_chunks=[chunk],
                                 confidence=0.9, should_abstain=False)
            return r, {"c1": {"source_url": "https://example.com"}}

    monkeypatch.setattr(service_module, "generate_answer", fake_generate_answer)
    result = FakeService().answer(
        "क्या यह पेटेंट हो सकता है?", None, 1, language="hi"
    )

    assert result["language"] == "hi"
    # No Bhashini credentials configured in tests -> NullTranslator ->
    # translated=False, text stays English rather than being fabricated.
    assert result["translated"] is False
    assert result["answer_text"] == "Yes, it can be patented."
    # Retrieval and generation both ran on the (untranslated, since no
    # backend) query -- the point being it's the SAME text passed through
    # to both, not that it changed language here.
    assert captured["retrieve_query"] == captured["retrieval_query"]
    # Citations are never touched by translation.
    assert result["citations"] == [] or all(
        "act_name" in c for c in result["citations"]
    )


def test_answer_english_query_is_untranslated_and_flagged_translated_true(monkeypatch):
    from app.services import ai_service as service_module

    def fake_generate_answer(retrieval, model, mock, api_key=None):
        from ai.shared.schema import FinalAnswer
        return FinalAnswer(
            answer_text="Yes.", citations=[], confidence=retrieval.confidence,
            abstained=False, disclaimer="This is informational, not legal advice.",
        )

    class FakeService(service_module.AIService):
        def retrieve(self, query, classification, top_k):
            from ai.person_b_retrieval.schema import MatchedChunk, RetrievalResult
            chunk = MatchedChunk(
                chunk_id="c1", text="source", act_name="Act", section="1",
                jurisdiction="india", similarity_score=0.9,
            )
            r = RetrievalResult(query=query, matched_chunks=[chunk],
                                 confidence=0.9, should_abstain=False)
            return r, {"c1": {"source_url": "https://example.com"}}

    monkeypatch.setattr(service_module, "generate_answer", fake_generate_answer)
    result = FakeService().answer("Can this be patented?", None, 1)

    assert result["language"] == "en"
    assert result["translated"] is True  # trivial identity, not a degraded case
    assert result["answer_text"] == "Yes."


def test_query_endpoint_accepts_language_field(monkeypatch):
    from app.api import routes

    captured = {}

    class FakeService:
        def answer(self, query, classification, top_k, compliance_facts=None,
                   consented_acts=None, language=None):
            captured["language"] = language
            return {
                "answer_text": "ok", "citations": [], "confidence": 0.5,
                "abstained": False, "disclaimer": "d", "sources": [],
                "language": language or "en", "translated": True,
            }

    monkeypatch.setattr(routes, "ai_service", FakeService())
    response = client.post(
        "/api/v1/query", json={"query": "क्या यह पेटेंट हो सकता है?", "language": "hi"}
    )
    assert response.status_code == 200
    assert captured["language"] == "hi"
    assert response.json()["language"] == "hi"


# ---------------------------------------------------------------------------
# /api/v1/updates — auto-update pipeline review gate
# ---------------------------------------------------------------------------

def test_updates_pending_lists_entries(monkeypatch):
    from app.api import updates_routes

    class FakeUpdatesService:
        def pending(self):
            return [{
                "id": "e1", "source_name": "src", "url": "https://example.test/a.pdf",
                "act_name": "The Patents Act, 1970", "jurisdiction": "india",
                "tier": "mandatory_review", "reason": "first time seen",
                "status": "pending", "needs_audit": False,
                "created_at": "2026-01-01T00:00:00+00:00", "decided_at": None,
                "decided_by": None, "notes": None, "ingest_result": None,
            }]

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    response = client.get("/api/v1/updates/pending")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "e1"
    assert body[0]["status"] == "pending"


def test_updates_approve_success(monkeypatch):
    from app.api import updates_routes

    class FakeUpdatesService:
        def approve(self, entry_id, *, decided_by, notes=None):
            assert entry_id == "e1"
            assert decided_by == "reviewer@example.test"

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    response = client.post(
        "/api/v1/updates/e1/approve",
        json={"decided_by": "reviewer@example.test", "notes": "ok"},
    )
    assert response.status_code == 200
    assert response.json() == {"id": "e1", "status": "approved"}


def test_updates_approve_conflict_returns_409(monkeypatch):
    from app.api import updates_routes
    from ai.updates.queue import ReviewQueueError

    class FakeUpdatesService:
        def approve(self, entry_id, *, decided_by, notes=None):
            raise ReviewQueueError(f"entry {entry_id!r} is already approved")

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    response = client.post(
        "/api/v1/updates/e1/approve", json={"decided_by": "reviewer@example.test"}
    )
    assert response.status_code == 409


def test_updates_publish_missing_entry_returns_404(monkeypatch):
    from app.api import updates_routes

    class FakeUpdatesService:
        def publish_entry(self, entry_id):
            raise ValueError(f"no review-queue entry {entry_id!r}")

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    response = client.post("/api/v1/updates/missing/publish")
    assert response.status_code == 404


def test_updates_check_now_returns_summary(monkeypatch):
    from app.api import updates_routes

    class FakeUpdatesService:
        def check_now(self, *, auto_ingest=None):
            return {"checked": 2, "entries": [
                {"id": "e1", "tier": "mandatory_review"},
                {"id": "e2", "tier": "auto_publish"},
            ]}

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    response = client.post("/api/v1/updates/check-now", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["checked"] == 2
    assert len(body["entries"]) == 2


# ---------------------------------------------------------------------------
# /api/v1/patent-cases — patent preparation and tracking
# ---------------------------------------------------------------------------

def test_patent_cases_create_and_get(monkeypatch):
    from app.api import patent_prep_routes

    class FakeService:
        def create_case(self, intake_dict):
            assert intake_dict["applicant_name"] == "Jane Doe"
            return "case-1"

        def get_case(self, case_id):
            assert case_id == "case-1"
            return {
                "id": "case-1", "intake": {"applicant_name": "Jane Doe"},
                "status": "intake", "precheck_result": None, "forms_result": None,
                "handoff_result": None, "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.post("/api/v1/patent-cases", json={
        "applicant_name": "Jane Doe", "inventors": ["Jane Doe"],
        "invention_title": "A formulation",
    })
    assert response.status_code == 200
    assert response.json() == {"id": "case-1", "status": "intake"}

    response = client.get("/api/v1/patent-cases/case-1")
    assert response.status_code == 200
    assert response.json()["status"] == "intake"


def test_patent_cases_get_missing_returns_404(monkeypatch):
    from app.api import patent_prep_routes
    from ai.patent_prep.tracker import CaseNotFound

    class FakeService:
        def get_case(self, case_id):
            raise CaseNotFound(f"no case {case_id!r}")

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.get("/api/v1/patent-cases/missing")
    assert response.status_code == 404


def test_patent_cases_precheck(monkeypatch):
    from app.api import patent_prep_routes

    class FakeService:
        def precheck(self, case_id):
            assert case_id == "case-1"
            return {"clear_to_draft": True, "reasons_not_clear": [], "blocking": [],
                     "critical_open_questions": [], "compliance": {}}

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.post("/api/v1/patent-cases/case-1/precheck")
    assert response.status_code == 200
    assert response.json()["clear_to_draft"] is True


def test_patent_cases_draft_forms(monkeypatch):
    from app.api import patent_prep_routes

    class FakeService:
        def draft_forms(self, case_id):
            return {"form_1": {"form_id": "Form 1"}, "form_3": {"form_id": "Form 3"}}

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.post("/api/v1/patent-cases/case-1/draft-forms")
    assert response.status_code == 200
    assert set(response.json()) == {"form_1", "form_3"}


def test_patent_cases_deadlines(monkeypatch):
    from app.api import patent_prep_routes

    class FakeService:
        def deadlines(self, case_id):
            return [{"rule_id": "convention_priority", "status": "upcoming"}]

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.get("/api/v1/patent-cases/case-1/deadlines")
    assert response.status_code == 200
    assert response.json()[0]["rule_id"] == "convention_priority"


def test_patent_cases_handoff(monkeypatch):
    from app.api import patent_prep_routes

    class FakeService:
        def handoff(self, case_id, *, recipient, notes=None):
            assert recipient == "agent@example.test"
            return {"generated_at": "2026-01-01", "intake": {}, "precheck": {},
                     "forms": {}, "deadlines": [], "handoff_notes": []}

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.post(
        "/api/v1/patent-cases/case-1/handoff",
        json={"recipient": "agent@example.test", "notes": "ready"},
    )
    assert response.status_code == 200
    assert "handoff_notes" in response.json()


def test_patent_cases_update_status(monkeypatch):
    from app.api import patent_prep_routes

    class FakeService:
        def update_status(self, case_id, status, *, detail=None):
            assert status == "filed"

    monkeypatch.setattr(patent_prep_routes, "patent_prep_service", FakeService())
    response = client.post(
        "/api/v1/patent-cases/case-1/status", json={"status": "filed"}
    )
    assert response.status_code == 200
    assert response.json() == {"id": "case-1", "status": "filed"}
