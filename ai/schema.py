"""Chunk schema and validation.

The output contract is fixed: `Chunk.to_dict()` emits exactly the eight
keys the team agreed on, in a stable order. Anything we learn during
ingestion that is *not* in that contract (how a field was obtained, which
page it came from) lives in `Chunk.provenance` and is written to SQLite,
never to the JSON payload.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

Jurisdiction = Literal["india", "international"]
InstrumentType = Literal["statute", "rule", "treaty", "case_law"]

JURISDICTIONS: tuple[str, ...] = get_args(Jurisdiction)
INSTRUMENT_TYPES: tuple[str, ...] = get_args(InstrumentType)

SCHEMA_KEYS: tuple[str, ...] = (
    "chunk_id",
    "text",
    "jurisdiction",
    "instrument_type",
    "act_name",
    "section",
    "effective_date",
    "source_url",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SchemaError(ValueError):
    """A chunk does not satisfy the agreed contract."""


def slugify(value: str, max_len: int = 60) -> str:
    """ASCII slug used to build deterministic chunk ids."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:max_len].strip("-") or "unknown"


def content_hash(text: str) -> str:
    """Hash of the normalised text. Whitespace-only changes must not
    produce a new version, or every re-ingest looks like an amendment."""
    normalised = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


@dataclass
class Chunk:
    chunk_id: str
    text: str
    jurisdiction: str
    instrument_type: str
    act_name: str
    section: str
    effective_date: str
    source_url: str

    # Not part of the output contract.
    provenance: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, str]:
        """Exactly the eight contract keys, in contract order."""
        return {k: getattr(self, k) for k in SCHEMA_KEYS}

    @property
    def content_hash(self) -> str:
        return content_hash(self.text)

    def validate(self) -> None:
        if not self.chunk_id or not re.fullmatch(r"[a-z0-9\-]+", self.chunk_id):
            raise SchemaError(f"chunk_id must be a lowercase slug, got {self.chunk_id!r}")
        if not self.text.strip():
            raise SchemaError(f"{self.chunk_id}: empty text")
        if self.jurisdiction not in JURISDICTIONS:
            raise SchemaError(
                f"{self.chunk_id}: jurisdiction {self.jurisdiction!r} not in {JURISDICTIONS}"
            )
        if self.instrument_type not in INSTRUMENT_TYPES:
            raise SchemaError(
                f"{self.chunk_id}: instrument_type {self.instrument_type!r} "
                f"not in {INSTRUMENT_TYPES}"
            )
        if not self.act_name.strip():
            raise SchemaError(f"{self.chunk_id}: act_name is required")
        if not self.section.strip():
            raise SchemaError(f"{self.chunk_id}: section is required")
        if not _DATE_RE.match(self.effective_date):
            raise SchemaError(
                f"{self.chunk_id}: effective_date must be YYYY-MM-DD, "
                f"got {self.effective_date!r}"
            )
        try:
            _dt.date.fromisoformat(self.effective_date)
        except ValueError as exc:
            raise SchemaError(f"{self.chunk_id}: {exc}") from exc
        if not isinstance(self.source_url, str):
            raise SchemaError(f"{self.chunk_id}: source_url must be a string")


def validate_all(chunks: list[Chunk]) -> None:
    """Validate every chunk and reject duplicate ids in one pass."""
    seen: dict[str, int] = {}
    errors: list[str] = []
    for i, c in enumerate(chunks):
        try:
            c.validate()
        except SchemaError as exc:
            errors.append(str(exc))
        if c.chunk_id in seen:
            errors.append(
                f"duplicate chunk_id {c.chunk_id!r} (positions {seen[c.chunk_id]} and {i})"
            )
        else:
            seen[c.chunk_id] = i
    if errors:
        raise SchemaError("; ".join(errors))
