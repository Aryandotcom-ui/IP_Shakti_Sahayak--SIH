"""
ai/updates — the auto-update pipeline with a review gate.

    check sources -> diff against last-seen hash -> classify into a tier
        -> auto_publish:        ingest immediately
        -> publish_then_audit:  ingest immediately, flagged for later review
        -> mandatory_review:    held in the queue until a human decides

Nothing in this package is scheduled by importing it. `scheduler.py` is
the only piece that starts a background job, and only when
`start_scheduler()` is called explicitly (see backend/app/main.py).
"""

from .classify import ClassificationResult, Tier, classify
from .fetch import Fetcher, FetchError, HttpFetcher, StaticFetcher
from .orchestrator import publish, run_check_cycle
from .queue import ReviewQueue, ReviewQueueError
from .watcher import ChangeCandidate, SourceConfig, SourceWatcher, load_sources

__all__ = [
    "Tier",
    "ClassificationResult",
    "classify",
    "Fetcher",
    "FetchError",
    "HttpFetcher",
    "StaticFetcher",
    "ReviewQueue",
    "ReviewQueueError",
    "ChangeCandidate",
    "run_check_cycle",
    "publish",
    "SourceConfig",
    "SourceWatcher",
    "load_sources",
]
