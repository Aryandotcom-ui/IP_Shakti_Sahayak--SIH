"""
ai/updates/classify.py

Sorts a ChangeCandidate into one of three tiers. This is the "review
gate" the auto-update pipeline is named for: the classifier's whole job
is to decide which changes are safe enough to publish unattended and
which need a person to look first.

Tier meanings
-------------
AUTO_PUBLISH        — ingest immediately, no human step. Reserved for a
                       small change to a source already trusted and
                       already seen at least once before.
PUBLISH_THEN_AUDIT   — ingest immediately (the corpus should not lag a
                       real change), but the item stays visible in the
                       review queue as "published — needs audit" so a
                       human can retract it after the fact if it turns
                       out wrong.
MANDATORY_REVIEW     — held in the queue, nothing ingested, until a
                       human approves or rejects it.

The defaults below are deliberately conservative: a first-seen source, an
unverified source, or a `priority: critical` act (the same field
ai/corpus.yaml already uses for the Biological Diversity Act amendment,
where ingesting the wrong text makes the system tell an applicant they
are in breach when they are not) always lands in MANDATORY_REVIEW,
whatever the diff size says. A byte-hash diff cannot tell "a comma
changed" from "section 6 was rewritten" — it can only tell "something
changed" — so severity is decided by the source's own declared risk, not
by how big the diff looks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from .watcher import ChangeCandidate

log = logging.getLogger(__name__)

# Below this fraction of byte-size change, on an official source that has
# been seen before, is "small enough to auto-publish". Tuned generously
# conservative on purpose — false negatives here (something small gets
# sent to review anyway) cost a human five minutes; false positives
# (something substantive slips through unreviewed) cost a wrong citation.
AUTO_PUBLISH_MAX_DELTA = 0.02

CRITICAL_PRIORITIES = {"critical"}


class Tier(str, Enum):
    AUTO_PUBLISH = "auto_publish"
    PUBLISH_THEN_AUDIT = "publish_then_audit"
    MANDATORY_REVIEW = "mandatory_review"


@dataclass
class ClassificationResult:
    tier: Tier
    reason: str


def classify(
    candidate: ChangeCandidate,
    *,
    auto_publish_max_delta: float = AUTO_PUBLISH_MAX_DELTA,
) -> ClassificationResult:
    source = candidate.source

    if candidate.is_first_seen:
        return ClassificationResult(
            Tier.MANDATORY_REVIEW,
            "first time this source has been seen — nothing to diff against",
        )

    if source.priority in CRITICAL_PRIORITIES:
        return ClassificationResult(
            Tier.MANDATORY_REVIEW,
            f"source is priority=critical ({source.act_name}) — always reviewed",
        )

    if source.source_trust != "official":
        return ClassificationResult(
            Tier.MANDATORY_REVIEW,
            f"source_trust={source.source_trust!r}, not an official portal",
        )

    delta = candidate.byte_delta_ratio
    if delta <= auto_publish_max_delta:
        return ClassificationResult(
            Tier.AUTO_PUBLISH,
            f"official source, {delta:.2%} byte change ≤ {auto_publish_max_delta:.0%} threshold",
        )

    return ClassificationResult(
        Tier.PUBLISH_THEN_AUDIT,
        f"official source, {delta:.2%} byte change exceeds auto-publish threshold",
    )
