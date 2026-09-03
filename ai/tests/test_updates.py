"""
Tests for ai/updates — the auto-update pipeline's watch/classify/queue
layer.

    python -m pytest ai/tests/test_updates.py -v

Deliberately does not exercise `orchestrator.publish()` or
`scheduler.run_once()`'s auto-ingest path: those call the real
`ai.pipeline.ingest()`, which needs pymupdf/chromadb/an embedding model.
`ai/test_ingest.py` already covers that pipeline directly. What's tested
here is the part unique to this package — detecting a change, sorting it
into the right tier, and the queue's state machine — using StaticFetcher
so nothing touches a network or a model.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.updates.classify import Tier, classify  # noqa: E402
from ai.updates.fetch import FetchError, StaticFetcher  # noqa: E402
from ai.updates.orchestrator import run_check_cycle  # noqa: E402
from ai.updates.queue import ReviewQueue, ReviewQueueError  # noqa: E402
from ai.updates.watcher import SourceConfig, SourceWatcher, load_sources  # noqa: E402

OFFICIAL_CRITICAL = SourceConfig(
    name="bio-div-amendment", url="https://example.test/bio-div.pdf",
    act_name="The Biological Diversity (Amendment) Act, 2023",
    jurisdiction="india", priority="critical", source_trust="official",
)
OFFICIAL_MEDIUM = SourceConfig(
    name="wipo-gratk", url="https://example.test/wipo.pdf",
    act_name="WIPO Treaty ...", jurisdiction="international",
    priority="medium", source_trust="official",
)
UNVERIFIED = SourceConfig(
    name="mystery-blog", url="https://example.test/blog.html",
    act_name="Some Act", jurisdiction="india",
    priority="low", source_trust="unverified",
)


@pytest.fixture
def watcher(tmp_path: Path) -> SourceWatcher:
    w = SourceWatcher(tmp_path / "watcher.sqlite3")
    yield w
    w.close()


@pytest.fixture
def queue(tmp_path: Path) -> ReviewQueue:
    q = ReviewQueue(tmp_path / "queue.sqlite3")
    yield q
    q.close()


# ---------------------------------------------------------------------------
# watcher: hash-diff detection
# ---------------------------------------------------------------------------


def test_first_check_of_a_source_is_a_candidate(watcher: SourceWatcher):
    fetcher = StaticFetcher({OFFICIAL_MEDIUM.url: b"version one"})
    candidate = watcher.check_one(OFFICIAL_MEDIUM, fetcher)
    assert candidate is not None
    assert candidate.is_first_seen
    assert candidate.previous_hash is None


def test_unchanged_content_is_not_a_candidate(watcher: SourceWatcher):
    fetcher = StaticFetcher({OFFICIAL_MEDIUM.url: b"stable content"})
    watcher.check_one(OFFICIAL_MEDIUM, fetcher)  # first check, records baseline
    second = watcher.check_one(OFFICIAL_MEDIUM, fetcher)  # same bytes again
    assert second is None


def test_changed_content_is_a_candidate_with_previous_hash(watcher: SourceWatcher):
    fetcher = StaticFetcher({OFFICIAL_MEDIUM.url: b"version one"})
    first = watcher.check_one(OFFICIAL_MEDIUM, fetcher)
    fetcher.set(OFFICIAL_MEDIUM.url, b"version two, a bit longer than before")
    second = watcher.check_one(OFFICIAL_MEDIUM, fetcher)
    assert second is not None
    assert not second.is_first_seen
    assert second.previous_hash == first.content_hash


def test_unreachable_source_is_skipped_not_raised(watcher: SourceWatcher):
    fetcher = StaticFetcher({})  # nothing registered -> FetchError inside
    candidate = watcher.check_one(OFFICIAL_MEDIUM, fetcher)
    assert candidate is None


def test_check_all_skips_unreachable_and_returns_the_rest(watcher: SourceWatcher):
    fetcher = StaticFetcher({OFFICIAL_MEDIUM.url: b"content"})
    # OFFICIAL_CRITICAL's url is not registered -> FetchError, skipped
    candidates = watcher.check_all([OFFICIAL_CRITICAL, OFFICIAL_MEDIUM], fetcher)
    assert len(candidates) == 1
    assert candidates[0].source.name == "wipo-gratk"


# ---------------------------------------------------------------------------
# classify: tiering
# ---------------------------------------------------------------------------


def _candidate(source: SourceConfig, *, first_seen: bool, delta: float):
    from ai.updates.watcher import ChangeCandidate

    previous_size = None if first_seen else 1000
    new_size = previous_size if first_seen else int(previous_size * (1 + delta))
    return ChangeCandidate(
        source=source,
        content=b"x" * (new_size or 10),
        content_hash="new",
        previous_hash=None if first_seen else "old",
        previous_size=previous_size,
        checked_at="2026-01-01T00:00:00+00:00",
    )


def test_first_seen_is_always_mandatory_review():
    candidate = _candidate(OFFICIAL_MEDIUM, first_seen=True, delta=0.0)
    result = classify(candidate)
    assert result.tier == Tier.MANDATORY_REVIEW


def test_critical_priority_is_always_mandatory_review_even_with_tiny_diff():
    candidate = _candidate(OFFICIAL_CRITICAL, first_seen=False, delta=0.001)
    result = classify(candidate)
    assert result.tier == Tier.MANDATORY_REVIEW
    assert "critical" in result.reason


def test_unverified_source_is_always_mandatory_review():
    candidate = _candidate(UNVERIFIED, first_seen=False, delta=0.001)
    result = classify(candidate)
    assert result.tier == Tier.MANDATORY_REVIEW


def test_official_small_diff_is_auto_publish():
    candidate = _candidate(OFFICIAL_MEDIUM, first_seen=False, delta=0.005)
    result = classify(candidate)
    assert result.tier == Tier.AUTO_PUBLISH


def test_official_large_diff_is_publish_then_audit():
    candidate = _candidate(OFFICIAL_MEDIUM, first_seen=False, delta=0.5)
    result = classify(candidate)
    assert result.tier == Tier.PUBLISH_THEN_AUDIT


# ---------------------------------------------------------------------------
# queue: state machine
# ---------------------------------------------------------------------------


def test_enqueue_mandatory_review_starts_pending(queue: ReviewQueue):
    candidate = _candidate(OFFICIAL_CRITICAL, first_seen=True, delta=0.0)
    result = classify(candidate)
    entry_id = queue.enqueue(candidate, result, staged_path="/tmp/x.pdf")
    entry = queue.get(entry_id)
    assert entry["status"] == "pending"
    assert entry_id in [e["id"] for e in queue.list_pending()]


def test_enqueue_auto_publish_starts_queued_for_ingest(queue: ReviewQueue):
    candidate = _candidate(OFFICIAL_MEDIUM, first_seen=False, delta=0.005)
    result = classify(candidate)
    entry_id = queue.enqueue(candidate, result, staged_path="/tmp/x.pdf")
    entry = queue.get(entry_id)
    assert entry["status"] == "queued_for_ingest"
    assert entry["needs_audit"] == 0
    assert entry_id not in [e["id"] for e in queue.list_pending()]
    assert entry_id in [e["id"] for e in queue.list_queued_for_ingest()]


def test_enqueue_publish_then_audit_starts_queued_for_ingest_and_needs_audit(queue: ReviewQueue):
    candidate = _candidate(OFFICIAL_MEDIUM, first_seen=False, delta=0.5)
    result = classify(candidate)
    entry_id = queue.enqueue(candidate, result, staged_path="/tmp/x.pdf")
    entry = queue.get(entry_id)
    assert entry["status"] == "queued_for_ingest"
    assert entry["needs_audit"] == 1
    # not yet published, so it should not show up as needing audit until
    # mark_published() runs
    assert entry_id not in [e["id"] for e in queue.list_needs_audit()]


def test_publish_then_audit_needs_audit_after_publishing(queue: ReviewQueue):
    candidate = _candidate(OFFICIAL_MEDIUM, first_seen=False, delta=0.5)
    entry_id = queue.enqueue(candidate, classify(candidate), staged_path="/tmp/x.pdf")
    queue.mark_published(entry_id, {"chunks": 3})
    assert entry_id in [e["id"] for e in queue.list_needs_audit()]
    queue.clear_audit(entry_id, decided_by="reviewer@example.test", notes="checked, fine")
    entry = queue.get(entry_id)
    assert entry["status"] == "published"  # unchanged
    assert entry["needs_audit"] == 0
    assert entry_id not in [e["id"] for e in queue.list_needs_audit()]


def test_approve_pending_entry(queue: ReviewQueue):
    candidate = _candidate(OFFICIAL_CRITICAL, first_seen=True, delta=0.0)
    entry_id = queue.enqueue(candidate, classify(candidate), staged_path="/tmp/x.pdf")
    queue.approve(entry_id, decided_by="reviewer@example.test", notes="looks right")
    entry = queue.get(entry_id)
    assert entry["status"] == "approved"
    assert entry["decided_by"] == "reviewer@example.test"
    assert entry["decided_at"] is not None


def test_reject_pending_entry(queue: ReviewQueue):
    candidate = _candidate(OFFICIAL_CRITICAL, first_seen=True, delta=0.0)
    entry_id = queue.enqueue(candidate, classify(candidate), staged_path="/tmp/x.pdf")
    queue.reject(entry_id, decided_by="reviewer@example.test", notes="stale mirror")
    entry = queue.get(entry_id)
    assert entry["status"] == "rejected"


def test_cannot_approve_twice(queue: ReviewQueue):
    candidate = _candidate(OFFICIAL_CRITICAL, first_seen=True, delta=0.0)
    entry_id = queue.enqueue(candidate, classify(candidate), staged_path="/tmp/x.pdf")
    queue.approve(entry_id, decided_by="a")
    with pytest.raises(ReviewQueueError):
        queue.approve(entry_id, decided_by="b")


def test_cannot_approve_a_queued_for_ingest_entry(queue: ReviewQueue):
    # AUTO_PUBLISH/PUBLISH_THEN_AUDIT tiers were already cleared by the
    # classifier — approve() is only for MANDATORY_REVIEW's pending items.
    candidate = _candidate(OFFICIAL_MEDIUM, first_seen=False, delta=0.005)
    entry_id = queue.enqueue(candidate, classify(candidate), staged_path="/tmp/x.pdf")
    with pytest.raises(ReviewQueueError):
        queue.approve(entry_id, decided_by="a")


def test_mark_ingest_failed_is_visible_not_silently_dropped(queue: ReviewQueue):
    candidate = _candidate(OFFICIAL_MEDIUM, first_seen=False, delta=0.005)
    entry_id = queue.enqueue(candidate, classify(candidate), staged_path="/tmp/x.pdf")
    queue.mark_ingest_failed(entry_id, "PDFOpenError: corrupt file")
    entry = queue.get(entry_id)
    assert entry["status"] == "ingest_failed"
    assert "corrupt file" in entry["ingest_result"]


def test_list_history_excludes_pending_and_queued_for_ingest(queue: ReviewQueue):
    pending = _candidate(OFFICIAL_CRITICAL, first_seen=True, delta=0.0)
    queued = _candidate(OFFICIAL_MEDIUM, first_seen=False, delta=0.005)
    rejected_id = queue.enqueue(pending, classify(pending), staged_path="/tmp/a.pdf")
    queue.enqueue(queued, classify(queued), staged_path="/tmp/b.pdf")
    queue.reject(rejected_id, decided_by="reviewer")
    history = queue.list_history()
    assert len(history) == 1
    assert history[0]["status"] == "rejected"


# ---------------------------------------------------------------------------
# orchestrator: run_check_cycle end to end (no ingestion)
# ---------------------------------------------------------------------------


def test_run_check_cycle_stages_and_enqueues(tmp_path: Path, watcher, queue):
    fetcher = StaticFetcher({
        OFFICIAL_MEDIUM.url: b"%PDF-1.4 fake content for the stage test",
    })
    results = run_check_cycle(
        [OFFICIAL_MEDIUM],
        watcher=watcher, fetcher=fetcher, queue=queue,
        stage_dir=tmp_path / "staged",
    )
    assert len(results) == 1
    entry_id, tier = results[0]
    assert tier == Tier.MANDATORY_REVIEW  # first-seen source
    entry = queue.get(entry_id)
    staged = Path(entry["staged_path"])
    assert staged.is_file()
    assert staged.read_bytes().startswith(b"%PDF")


def test_run_check_cycle_is_a_noop_when_nothing_changed(tmp_path: Path, watcher, queue):
    fetcher = StaticFetcher({OFFICIAL_MEDIUM.url: b"stable"})
    run_check_cycle(
        [OFFICIAL_MEDIUM], watcher=watcher, fetcher=fetcher, queue=queue,
        stage_dir=tmp_path / "staged",
    )
    second = run_check_cycle(
        [OFFICIAL_MEDIUM], watcher=watcher, fetcher=fetcher, queue=queue,
        stage_dir=tmp_path / "staged",
    )
    assert second == []


# ---------------------------------------------------------------------------
# sources.yaml loads and matches corpus.yaml's exact-match contract
# ---------------------------------------------------------------------------


def test_load_sources_yaml_parses():
    sources = load_sources(REPO_ROOT / "ai" / "updates" / "sources.yaml")
    assert len(sources) >= 1
    assert all(s.act_name for s in sources)


def test_sources_act_names_match_corpus_yaml_exactly():
    import yaml

    sources = load_sources(REPO_ROOT / "ai" / "updates" / "sources.yaml")
    corpus = yaml.safe_load((REPO_ROOT / "ai" / "corpus.yaml").read_text())
    corpus_act_names = {d["act_name"] for d in corpus["documents"]}
    for source in sources:
        assert source.act_name in corpus_act_names, (
            f"{source.name}: act_name {source.act_name!r} not in corpus.yaml — "
            "the exact-match contract is broken"
        )
