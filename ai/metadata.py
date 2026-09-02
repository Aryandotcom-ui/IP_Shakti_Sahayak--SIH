"""Resolve the six metadata fields for a document.

Precedence, highest first:

  1. the manifest (`manifests/*.yaml`) — hand-written, verified, checked in
  2. `--interactive`, which prompts and offers to append to the manifest
  3. inference from the document text
  4. failure, if `--strict`

Inference exists to make the first pass fast, not to be trusted. Every
inferred value is recorded in the chunk's provenance so the corpus lead
can filter for `source=inferred` and verify those by hand. Getting
`effective_date` wrong silently is the worst failure this pipeline can
have: the as-of filter would then serve repealed law as current.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .extract import Document
from .schema import INSTRUMENT_TYPES, JURISDICTIONS

log = logging.getLogger(__name__)

INFERRED = "inferred"
MANIFEST = "manifest"
PROMPTED = "prompted"


class MetadataError(ValueError):
    pass


@dataclass
class DocMeta:
    jurisdiction: str
    instrument_type: str
    act_name: str
    effective_date: str
    source_url: str
    # per-section overrides, e.g. {"3(d)": "2005-04-01"} for amendments
    section_effective_dates: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    def effective_date_for(self, section_label: str, section_number: str) -> tuple[str, str]:
        for key in (section_label, section_number, section_label.replace("Section ", "")):
            if key in self.section_effective_dates:
                return self.section_effective_dates[key], MANIFEST
        return self.effective_date, self.sources.get("effective_date", INFERRED)


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------

def load_manifest(path: Path | str | None) -> dict[str, dict[str, Any]]:
    """Load a manifest keyed by filename. Accepts YAML or JSON."""
    if path is None:
        return {}
    path = Path(path)
    if not path.is_file():
        raise MetadataError(f"manifest not found: {path}")
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw) if path.suffix == ".json" else yaml.safe_load(raw)
    if isinstance(data, dict) and "documents" in data:
        data = data["documents"]
    if not isinstance(data, list):
        raise MetadataError(f"{path}: expected a list of document entries")

    out: dict[str, dict[str, Any]] = {}
    for entry in data:
        if "file" not in entry:
            raise MetadataError(f"{path}: every entry needs a 'file' key, got {entry!r}")
        out[Path(entry["file"]).name] = entry
    return out


# --------------------------------------------------------------------------
# inference
# --------------------------------------------------------------------------

_INTL_MARKERS = (
    "world intellectual property organization", "wipo", "trips agreement",
    "world trade organization", "convention on biological diversity",
    "nagoya protocol", "patent cooperation treaty", "madrid protocol",
    "hague agreement", "budapest treaty", "contracting party",
    "contracting parties", "member states", "diplomatic conference",
)
_INDIA_MARKERS = (
    "government of india", "gazette of india", "ministry of", "parliament",
    "an act to", "be it enacted", "controller general of patents",
    "central government", "state government", "india code",
)
_TYPE_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("treaty", ("treaty", "convention", "protocol", "agreement between",
                "contracting parties", "diplomatic conference")),
    ("rule", ("rules, 20", "rules, 19", "in exercise of the powers conferred",
              "amendment rules", "regulations, 20")),
    ("case_law", ("in the high court", "in the supreme court", "judgment",
                  "petitioner", "respondent", "coram", "civil appeal no")),
    ("statute", ("an act to", "be it enacted", "act, 19", "act, 20")),
]

_DATE_PATTERNS = [
    re.compile(r"(?i)\b(?:came?\s+into\s+force|shall\s+come\s+into\s+force|commenced?|"
               r"with\s+effect\s+from|w\.e\.f\.?|dated)\D{0,25}?"
               r"(\d{1,2})(?:st|nd|rd|th)?\s+(\w+),?\s+(\d{4})"),
    re.compile(r"(?i)\b(?:came?\s+into\s+force|with\s+effect\s+from|w\.e\.f\.?|dated)"
               r"\D{0,25}?(\d{4})-(\d{2})-(\d{2})"),
]
_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}
_YEAR_IN_TITLE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def infer_jurisdiction(text: str) -> str:
    head = text[:20000].lower()
    intl = sum(head.count(m) for m in _INTL_MARKERS)
    india = sum(head.count(m) for m in _INDIA_MARKERS)
    return "international" if intl > india else "india"


def infer_instrument_type(text: str, filename: str) -> str:
    head = (filename + "\n" + text[:20000]).lower()
    scores = {t: sum(head.count(m) for m in markers) for t, markers in _TYPE_MARKERS}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] else "statute"


def infer_act_name(doc: Document) -> str:
    if doc.pdf_title and len(doc.pdf_title.strip()) > 6:
        return doc.pdf_title.strip()
    for line in doc.pages[0].text.splitlines()[:40] if doc.pages else []:
        s = line.strip(" .*_-")
        if 10 < len(s) < 120 and _YEAR_IN_TITLE.search(s):
            if re.search(r"(?i)\b(act|rules|treaty|convention|protocol|agreement|regulations)\b", s):
                return re.sub(r"\s+", " ", s)
    stem = doc.path.stem.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", stem).strip().title()


def infer_effective_date(text: str, act_name: str) -> tuple[str, bool]:
    """Return (date, confident). Falls back to 1 January of the year in
    the title, which is a guess and is flagged as one."""
    head = text[:40000]
    for pat in _DATE_PATTERNS:
        m = pat.search(head)
        if not m:
            continue
        try:
            if len(m.group(2)) == 2 and m.group(2).isdigit():
                y, mo, d = m.group(1), m.group(2), m.group(3)
                return f"{y}-{mo}-{d}", True
            day, month_name, year = m.group(1), m.group(2).lower(), m.group(3)
            month = _MONTHS.get(month_name[:3].lower()) or _MONTHS.get(month_name)
            if month:
                return f"{int(year):04d}-{month:02d}-{int(day):02d}", True
        except (ValueError, IndexError):
            continue
    year = _YEAR_IN_TITLE.search(act_name) or _YEAR_IN_TITLE.search(head[:2000])
    if year:
        return f"{year.group(1)}-01-01", False
    return _dt.date.today().isoformat(), False


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------

def _ask(prompt: str, default: str | None, choices: tuple[str, ...] | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"  {prompt}{suffix}: ").strip()
        if not val and default:
            return default
        if choices and val not in choices:
            print(f"    must be one of {', '.join(choices)}")
            continue
        if val:
            return val


def resolve(
    doc: Document,
    manifest: dict[str, dict[str, Any]],
    *,
    interactive: bool = False,
    strict: bool = False,
) -> DocMeta:
    entry = manifest.get(doc.path.name, {})
    text = doc.text
    sources: dict[str, str] = {}

    def pick(field_name: str, inferred: Any, confident: bool = True) -> Any:
        if field_name in entry and entry[field_name] not in (None, ""):
            sources[field_name] = MANIFEST
            return entry[field_name]
        if strict:
            raise MetadataError(
                f"{doc.path.name}: '{field_name}' missing from the manifest and "
                f"--strict is set. Add it to the manifest."
            )
        if interactive:
            choices = None
            if field_name == "jurisdiction":
                choices = JURISDICTIONS
            elif field_name == "instrument_type":
                choices = INSTRUMENT_TYPES
            val = _ask(field_name, str(inferred), choices)
            sources[field_name] = MANIFEST if val == str(inferred) and confident else PROMPTED
            return val
        sources[field_name] = INFERRED
        if not confident:
            log.warning(
                "%s: %s inferred with low confidence (%r) — verify before this "
                "reaches the corpus", doc.path.name, field_name, inferred,
            )
        return inferred

    jurisdiction = pick("jurisdiction", infer_jurisdiction(text))
    instrument_type = pick("instrument_type", infer_instrument_type(text, doc.path.name))
    act_name = pick("act_name", infer_act_name(doc))
    guessed_date, confident = infer_effective_date(text, str(act_name))
    effective_date = pick("effective_date", guessed_date, confident)
    source_url = pick("source_url", "")

    if jurisdiction not in JURISDICTIONS:
        raise MetadataError(f"{doc.path.name}: bad jurisdiction {jurisdiction!r}")
    if instrument_type not in INSTRUMENT_TYPES:
        raise MetadataError(f"{doc.path.name}: bad instrument_type {instrument_type!r}")
    if not source_url:
        log.warning("%s: no source_url — the assistant cannot link out to this document",
                    doc.path.name)

    return DocMeta(
        jurisdiction=str(jurisdiction),
        instrument_type=str(instrument_type),
        act_name=str(act_name),
        effective_date=str(effective_date),
        source_url=str(source_url),
        section_effective_dates=dict(entry.get("section_effective_dates") or {}),
        sources=sources,
    )
