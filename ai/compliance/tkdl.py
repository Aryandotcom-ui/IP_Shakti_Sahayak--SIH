"""
compliance/tkdl.py

Prior-art probing for the section 3(p) traditional-knowledge bar.

Why this is not a TKDL API client
---------------------------------
The TKDL is not publicly queryable. Access is granted to patent offices
under Access (Non-disclosure) Agreements, and those agreements restrict
examiners to using it for search and examination -- they cannot disclose
contents to third parties. Wider access has been approved as a phased paid
subscription, but there is no open endpoint to call.

So a `tkdl_search(query)` function that returns results would be a lie in
code, and worse than useless here: a hit means "your application will
probably be refused under section 3(p)", and a fabricated one sends someone
into a filing decision on invented evidence.

What this module does instead is define the seam:

    PriorArtProbe          the interface any backend implements
    LocalClassicalProbe    works today, offline, over a local index
    TKDLProbe              the credentialed adapter, fails loudly unqualified
    NullProbe              explicit "no probe configured"

`probe_status()` reports which backend is live, and every ProbeResult
carries the backend that produced it, so a UI can distinguish "checked
against TKDL" from "checked against our local index" from "not checked".
Collapsing those three into one green tick is exactly the failure this
layering exists to prevent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Protocol, Sequence

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class PriorArtHit:
    """A match suggesting the formulation is already documented."""
    term: str                     # what matched
    reference: str                # the classical text or database record
    match_type: str               # "formulation_name" | "ingredient" | "combination"
    confidence: float             # 0..1
    note: str = ""
    verified: bool = False        # has a human checked this entry against the source?


@dataclass
class ProbeResult:
    backend: str
    available: bool
    hits: list[PriorArtHit] = field(default_factory=list)
    searched_terms: list[str] = field(default_factory=list)
    message: str = ""

    @property
    def risk(self) -> str:
        """Coarse section 3(p) exposure.

        `unknown` is a distinct outcome from `low`, and the distinction is
        the whole point: an unavailable probe found nothing because it did
        not look. Reporting that as low risk is how a system quietly tells
        someone their application is clear when nobody checked.
        """
        if not self.available:
            return "unknown"
        if not self.hits:
            return "low"
        top = max(h.confidence for h in self.hits)
        if top >= 0.85:
            return "high"
        if top >= 0.5:
            return "medium"
        return "low"

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "available": self.available,
            "risk": self.risk,
            "message": self.message,
            "searched_terms": self.searched_terms,
            "hits": [
                {
                    "term": h.term,
                    "reference": h.reference,
                    "match_type": h.match_type,
                    "confidence": round(h.confidence, 3),
                    "note": h.note,
                    "verified": h.verified,
                }
                for h in self.hits
            ],
        }


class PriorArtProbe(Protocol):
    name: str

    def available(self) -> bool: ...
    def search(self, terms: Sequence[str]) -> ProbeResult: ...


# ---------------------------------------------------------------------------
# Local classical-text index
# ---------------------------------------------------------------------------
#
# SEED DATA -- NOT AUTHORITATIVE.
#
# These entries exist so the mechanism is exercisable and demonstrable before
# a real index exists. They name the classical source generically and are all
# `verified=False`. They must be replaced by records derived from the
# Ayurvedic Formulary of India and the Ayurvedic Pharmacopoeia of India
# before this is put in front of anyone making a filing decision.
#
# Deliberately no page or entry numbers: a precise-looking citation nobody
# checked is more dangerous than an obviously coarse one, because it invites
# reliance it has not earned.

_CLASSICAL_SEED: dict[str, tuple[str, str]] = {
    # formulation -> (classical source, note)
    "triphala": ("Classical Ayurvedic formulary", "Three-fruit combination; extensively documented."),
    "trikatu": ("Classical Ayurvedic formulary", "Three-pungent combination; extensively documented."),
    "chyawanprash": ("Classical Ayurvedic formulary", "Documented rasayana preparation."),
    "dashamoola": ("Classical Ayurvedic formulary", "Ten-root combination."),
    "sitopaladi": ("Classical Ayurvedic formulary", "Documented churna."),
    "talisadi": ("Classical Ayurvedic formulary", "Documented churna."),
    "avipattikar": ("Classical Ayurvedic formulary", "Documented churna."),
    "hingvashtaka": ("Classical Ayurvedic formulary", "Documented churna."),
    "panchakola": ("Classical Ayurvedic formulary", "Five-pungent combination."),
    "kutajarishta": ("Classical Ayurvedic formulary", "Documented arishta."),
    "arjunarishta": ("Classical Ayurvedic formulary", "Documented arishta."),
}

_INGREDIENT_SEED: dict[str, tuple[str, str]] = {
    # ingredient -> (source, note). Botanical and common names both indexed.
    "withania somnifera": ("Classical Ayurvedic materia medica", "Ashwagandha."),
    "ashwagandha": ("Classical Ayurvedic materia medica", "Withania somnifera."),
    "curcuma longa": ("Classical Ayurvedic materia medica", "Haridra; subject of the turmeric patent revocation."),
    "turmeric": ("Classical Ayurvedic materia medica", "Curcuma longa; subject of the turmeric patent revocation."),
    "haridra": ("Classical Ayurvedic materia medica", "Curcuma longa."),
    "azadirachta indica": ("Classical Ayurvedic materia medica", "Neem; subject of the neem patent revocation."),
    "neem": ("Classical Ayurvedic materia medica", "Azadirachta indica; subject of the neem patent revocation."),
    "tinospora cordifolia": ("Classical Ayurvedic materia medica", "Guduchi."),
    "guduchi": ("Classical Ayurvedic materia medica", "Tinospora cordifolia."),
    "bacopa monnieri": ("Classical Ayurvedic materia medica", "Brahmi."),
    "brahmi": ("Classical Ayurvedic materia medica", "Bacopa monnieri."),
    "terminalia arjuna": ("Classical Ayurvedic materia medica", "Arjuna."),
    "asparagus racemosus": ("Classical Ayurvedic materia medica", "Shatavari."),
    "shatavari": ("Classical Ayurvedic materia medica", "Asparagus racemosus."),
    "emblica officinalis": ("Classical Ayurvedic materia medica", "Amalaki; component of Triphala."),
    "amalaki": ("Classical Ayurvedic materia medica", "Emblica officinalis."),
    "piper longum": ("Classical Ayurvedic materia medica", "Pippali; component of Trikatu."),
    "pippali": ("Classical Ayurvedic materia medica", "Piper longum."),
}


def _normalise(term: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", term.lower()).strip()


class LocalClassicalProbe:
    """Offline probe over a local classical-formulation index.

    Not a TKDL substitute and does not claim to be. It answers a narrower
    question -- "is this name or ingredient set already documented in
    classical literature" -- which is enough to raise a section 3(p) flag
    worth investigating, which is all a pre-filing check should ever do.
    """

    name = "local_classical_index"

    def __init__(
        self,
        formulations: dict[str, tuple[str, str]] | None = None,
        ingredients: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        self.formulations = formulations if formulations is not None else _CLASSICAL_SEED
        self.ingredients = ingredients if ingredients is not None else _INGREDIENT_SEED

    def available(self) -> bool:
        return bool(self.formulations or self.ingredients)

    def search(self, terms: Sequence[str]) -> ProbeResult:
        searched = [t for t in (terms or []) if t and t.strip()]
        result = ProbeResult(
            backend=self.name,
            available=self.available(),
            searched_terms=list(searched),
            message=(
                "Checked against a local classical-formulation index. This is "
                "NOT a TKDL search; absence of a hit does not mean absence of "
                "prior art."
            ),
        )
        if not result.available:
            result.message = "Local classical index is empty."
            return result

        ingredient_hits = 0
        for raw in searched:
            term = _normalise(raw)
            if not term:
                continue

            if term in self.formulations:
                source, note = self.formulations[term]
                result.hits.append(PriorArtHit(
                    term=raw, reference=source, match_type="formulation_name",
                    confidence=0.9, note=note, verified=False,
                ))
                continue

            # Substring match on the formulation index, e.g. "Triphala churna".
            matched = next(
                (k for k in self.formulations if k in term or term in k),
                None,
            )
            if matched:
                source, note = self.formulations[matched]
                result.hits.append(PriorArtHit(
                    term=raw, reference=source, match_type="formulation_name",
                    confidence=0.7, note=note, verified=False,
                ))
                continue

            if term in self.ingredients:
                source, note = self.ingredients[term]
                ingredient_hits += 1
                result.hits.append(PriorArtHit(
                    term=raw, reference=source, match_type="ingredient",
                    confidence=0.45, note=note, verified=False,
                ))

        # A combination of individually documented ingredients is the classic
        # section 3(e) / 3(p) shape, and is stronger evidence than any single
        # ingredient on its own -- so it gets its own hit rather than being
        # left implicit in a list the reader has to assemble themselves.
        if ingredient_hits >= 2:
            result.hits.append(PriorArtHit(
                term=" + ".join(searched[:6]),
                reference="Combination of individually documented components",
                match_type="combination",
                confidence=0.65,
                note=(
                    f"{ingredient_hits} components are individually documented. "
                    "A combination of known components attracts both the section "
                    "3(e) mere-admixture objection and the section 3(p) bar unless "
                    "synergy beyond additive effect is shown."
                ),
                verified=False,
            ))

        return result


class TKDLProbe:
    """Adapter for the real TKDL, for when credentials exist.

    Left unimplemented on purpose. `available()` returns False without
    credentials and `search()` raises rather than degrading to a
    plausible-looking empty result, because a silent empty result from an
    unconfigured probe reads identically to a genuine clean search.
    """

    name = "tkdl"

    def __init__(self, endpoint: str | None = None, credentials: str | None = None) -> None:
        self.endpoint = endpoint
        self.credentials = credentials

    def available(self) -> bool:
        return bool(self.endpoint and self.credentials)

    def search(self, terms: Sequence[str]) -> ProbeResult:
        if not self.available():
            raise RuntimeError(
                "TKDL access is not configured. The TKDL is not publicly "
                "queryable: access is granted to patent offices under Access "
                "(Non-disclosure) Agreements, with wider access approved as a "
                "phased paid subscription. Supply endpoint and credentials, or "
                "use LocalClassicalProbe."
            )
        raise NotImplementedError(
            "Implement against the TKDL interface granted under your access "
            "agreement. Note the non-disclosure terms: hits must not be "
            "redistributed to third parties, which constrains what this "
            "system may cache or display."
        )


class NullProbe:
    """No prior-art checking configured. Reports `unknown`, never `low`."""

    name = "none"

    def available(self) -> bool:
        return False

    def search(self, terms: Sequence[str]) -> ProbeResult:
        return ProbeResult(
            backend=self.name,
            available=False,
            searched_terms=list(terms or []),
            message="No prior-art probe configured; section 3(p) exposure was not assessed.",
        )


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def get_probe(
    tkdl_endpoint: str | None = None,
    tkdl_credentials: str | None = None,
) -> PriorArtProbe:
    """Prefer the real TKDL when it is genuinely configured, else the local
    index, else nothing."""
    tkdl = TKDLProbe(tkdl_endpoint, tkdl_credentials)
    if tkdl.available():
        return tkdl
    local = LocalClassicalProbe()
    if local.available():
        return local
    return NullProbe()


def probe_terms(formulation_name: str | None, ingredients: Iterable[str] | None) -> list[str]:
    terms: list[str] = []
    if formulation_name:
        terms.append(formulation_name)
    for ing in ingredients or ():
        if ing and ing not in terms:
            terms.append(ing)
    return terms
