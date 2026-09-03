from functools import lru_cache
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing import Annotated


REPO_ROOT = Path(__file__).resolve().parents[3]


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
    audit_db_path: str = str(REPO_ROOT / "data" / "audit.sqlite3")
    # DPDP storage-limitation bound for the audit trail. purge_older_than()
    # is not scheduled by anything in this process — the gap-5 auto-update
    # pipeline's job runner is the intended caller.
    audit_retention_days: int = 180

    llm_model: str = "claude-sonnet-4-5"
    anthropic_api_key: str | None = None

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
