"""
shared/taxonomy.py

Formulation-type -> relevant-act taxonomy.

This is the "pre-filter before you search" mechanism: given a formulation
classification, narrow the corpus to the acts that actually matter for it
BEFORE running semantic search, instead of searching the whole corpus.

IMPORTANT: the act_name strings below must match EXACTLY (character for
character, including "The " prefixes) the `act_name` value used in
ai/corpus.yaml for that document. Chroma's metadata `where` filter is an
exact-match filter, not a substring/contains match — there is no fuzzy
matching here. If an act is renamed in the manifest, update it here too,
or the formulation pre-filter will silently stop matching that document
and fall back to jurisdiction-only filtering.

This file is the ONLY place this taxonomy should be defined. Both the
offline fixture-based retrieval module (person_b_retrieval/retrieval.py)
and the production Chroma-backed store (store.py) import from here, so
there is one taxonomy, not two copies that can drift apart.
"""

from __future__ import annotations

# Only "The Patents Act, 1970" and the WIPO GRATK Treaty are actually
# ingested into the real corpus so far (see ai/corpus.yaml) — the acts
# below are the intended taxonomy once the rest of the corpus is
# ingested, and their exact strings are provisional. They are harmless
# in production today (an `act_name` filter for an act that hasn't been
# ingested yet just matches zero chunks — it doesn't error), and they
# are what let the fixture-based tests in person_b_retrieval exercise
# the pre-filter mechanism meaningfully before the full corpus exists.
# VERIFY each string against the real act_name in ai/corpus.yaml the
# moment that document is actually ingested — do not assume this guess
# is correct.
FORMULATION_RELEVANT_ACTS: dict[str, list[str]] = {
    "classical": [
        "The Patents Act, 1970",
        "Biological Diversity Act, 2002",       # provisional — verify on ingest
        "Drugs and Cosmetics Act, 1940",         # provisional — verify on ingest
    ],
    "proprietary": [
        "The Patents Act, 1970",
        "Drugs and Cosmetics Act, 1940",         # provisional — verify on ingest
    ],
    "new_drug": [
        "The Patents Act, 1970",
        "Drugs and Cosmetics Act, 1940",         # provisional — verify on ingest
    ],
    "phytopharmaceutical": [
        "The Patents Act, 1970",
        "Drugs and Cosmetics Act, 1940",         # provisional — verify on ingest
    ],
    "aahar": [
        "FSSAI Ayurveda Aahar Regulations",      # provisional — verify on ingest
    ],
    "cosmetic": [
        "Drugs and Cosmetics Act, 1940",         # provisional — verify on ingest
    ],
}


def acts_for_formulation(formulation_type: str | None) -> list[str] | None:
    """Return the act_names relevant to a formulation type, or None if
    there's nothing to narrow by — callers should fall back to
    jurisdiction-only filtering rather than returning zero candidates
    when the mapping list happens to be empty (e.g. before the relevant
    act has been ingested yet)."""
    if not formulation_type:
        return None
    return FORMULATION_RELEVANT_ACTS.get(formulation_type) or None
