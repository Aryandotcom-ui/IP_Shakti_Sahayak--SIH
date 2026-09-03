from functools import lru_cache
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing import Annotated


REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "IP-SAKTI Sahayak API"
    api_v1_prefix: str = "/api/v1"
    # pydantic-settings normally expects JSON for list-valued environment
    # variables. We intentionally use a comma-separated value in .env for
    # developer friendliness, so disable automatic JSON decoding and parse it.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    # Resolve the default corpus relative to the repository, not the process cwd.
    chroma_path: str = str(REPO_ROOT / "data" / "chroma")
    chroma_collection: str = "ip_sakti_corpus"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_device: str | None = "cpu"
    top_k: int = 5
    abstain_threshold: float = 0.20

    corpus_manifest_path: str = str(REPO_ROOT / "ai" / "corpus.yaml")
    sqlite_registry_path: str = str(REPO_ROOT / "data" / "registry.sqlite3")
    audit_db_path: str = str(REPO_ROOT / "data" / "audit.sqlite3")
    # DPDP storage-limitation bound for the audit trail. purge_older_than()
    # is not scheduled by anything in this process — the auto-update
    # pipeline's job runner (below) is the intended caller.
    audit_retention_days: int = 180

    # Auto-update pipeline (ai/updates) — source watcher + review gate.
    updates_sources_path: str = str(REPO_ROOT / "ai" / "updates" / "sources.yaml")
    updates_watcher_db_path: str = str(REPO_ROOT / "data" / "updates_watcher.sqlite3")
    updates_queue_db_path: str = str(REPO_ROOT / "data" / "updates_queue.sqlite3")
    updates_stage_dir: str = str(REPO_ROOT / "data" / "updates_incoming")
    # Off by default: enabling this makes the process poll real external
    # URLs on a schedule, which a shared/CI/demo deployment should opt
    # into deliberately rather than inherit from a default.
    updates_scheduler_enabled: bool = False
    updates_interval_minutes: int = 60
    # Whether AUTO_PUBLISH / PUBLISH_THEN_AUDIT tiers are ingested
    # immediately by the scheduler and by "check now". False makes every
    # tier land in the queue for a human to trigger ingestion on
    # explicitly — a safer default for a first deployment.
    updates_auto_ingest: bool = False

    # Patent preparation and tracking (ai/patent_prep) — separate from the
    # RAG core's own SQLite stores above.
    patent_cases_db_path: str = str(REPO_ROOT / "data" / "patent_cases.sqlite3")

    llm_model: str = "claude-sonnet-4-5"
    anthropic_api_key: str | None = None

    # Multilingual request/response edge (ai/translation.py). Without both
    # set, queries and answers pass through untranslated — see
    # ai.translation.NullTranslator.
    bhashini_api_key: str | None = None
    bhashini_user_id: str | None = None

    model_config = SettingsConfigDict(
        # Support .env at the repo root and backend/.env; the latter wins.
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def normalized_cors_origins(self) -> list[str]:
        return [x.strip() for x in self.cors_origins if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
settings.cors_origins = settings.normalized_cors_origins
