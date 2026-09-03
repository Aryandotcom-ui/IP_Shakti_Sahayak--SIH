# ai/updates — auto-update pipeline with a review gate

Watches configured sources for changes and routes each one into a tier
that decides whether it ingests unattended or waits for a human.

```
check sources -> diff against last-seen hash -> classify into a tier
    -> auto_publish:        ingest immediately
    -> publish_then_audit:  ingest immediately, flagged for later review
    -> mandatory_review:    held until a human approves or rejects it
```

## Files

```
ai/updates/
├── sources.yaml     # what's watched: url, act_name, jurisdiction, priority, trust
├── fetch.py          # Fetcher protocol: HttpFetcher (real), StaticFetcher (tests)
├── watcher.py         # SourceWatcher — SQLite last-seen-hash tracker, ChangeCandidate
├── classify.py        # classify() — sorts a candidate into a Tier
├── queue.py            # ReviewQueue — SQLite state machine for the gate
├── orchestrator.py      # run_check_cycle() (light) + publish() (real ingest)
└── scheduler.py          # APScheduler wrapper: run_once() / start_scheduler()
```

## Why two "run" functions

`run_check_cycle()` — fetch, hash-diff, classify, stage the bytes to
disk, enqueue. No PDF parsing, no embedding model, no Chroma. Safe and
fast enough to unit test with nothing beyond the stdlib and PyYAML (see
`ai/tests/test_updates.py`).

`publish()` — the heavy step. Runs a staged file through the real
`ai.pipeline.ingest()`, the same code path `python -m ai.cli` uses
manually. Called immediately after a MANDATORY_REVIEW item is approved,
and — when `updates_auto_ingest` is on — immediately after an
AUTO_PUBLISH/PUBLISH_THEN_AUDIT item is classified.

Keeping them apart means the classifier and the review queue can be
exercised in CI without pymupdf/sentence-transformers/chromadb ever
loading, and means a slow or failing embedding model can't make the
lightweight "did anything change" check unreliable.

## The three tiers

| Tier | When | What happens |
|---|---|---|
| `auto_publish` | Official source, seen before, byte diff ≤ 2% | Ingested immediately, no human step |
| `publish_then_audit` | Official source, seen before, bigger diff | Ingested immediately, flagged `needs_audit` until a human signs off |
| `mandatory_review` | First time seeing this source, OR `priority: critical`, OR `source_trust: unverified` | Held as `pending`; nothing ingested until approved |

A byte-hash diff cannot tell "a comma changed" from "section 6 was
rewritten" — only that something changed — so `priority: critical`
(reusing `ai/corpus.yaml`'s own acquisition-priority scale) always wins
over how small the diff looks. See `classify.py`'s module docstring for
the reasoning in full.

## The queue's status model

`status` tracks ingestion lifecycle: `pending` → `approved`/`rejected`
(human path) or `pending` doesn't apply → `queued_for_ingest` →
`published`/`ingest_failed` (auto path, or after an approval is
published). `needs_audit` is a separate flag, not a status:
PUBLISH_THEN_AUDIT items are `published` immediately **and**
`needs_audit=1` until `clear_audit()` runs. Folding that into `status`
would force "this is published" and "this needs review" to be mutually
exclusive, when the whole point of that tier is that both are true at
once.

## Running it

```bash
# one-off check, from the repo root — safe, does not ingest anything by
# default unless the entries land in AUTO_PUBLISH/PUBLISH_THEN_AUDIT and
# auto_ingest=True is passed
python -c "
from ai.updates.scheduler import run_once
run_once(
    sources_path='ai/updates/sources.yaml',
    watcher_db_path='data/updates_watcher.sqlite3',
    queue_db_path='data/updates_queue.sqlite3',
    stage_dir='data/updates_incoming',
    manifest_path='ai/corpus.yaml',
    chroma_path='data/chroma', chroma_collection='ip_sakti_corpus',
    embedding_model='BAAI/bge-small-en-v1.5', embedding_device='cpu',
    sqlite_registry_path='data/registry.sqlite3',
    auto_ingest=False,
)
"

python -m pytest ai/tests/test_updates.py -v
```

Or via the backend API — see `backend/README.md`'s "Auto-update
pipeline" section for the `/api/v1/updates/*` endpoints, which wrap the
same functions.

## What's a skeleton, not production-hardened

- **One watcher per URL.** `sources.yaml` watches direct document URLs.
  A real deployment is usually better served watching an index/listing
  page per source (more stable against a document being re-exported with
  different bytes but the same legal text) — swap the URL, nothing else
  changes.
- **Byte-hash diffing only.** No structural PDF diff, no "which section
  changed" — that judgment is exactly what MANDATORY_REVIEW and the
  `needs_audit` flag hand to a human.
- **No retry/backoff policy** beyond `HttpFetcher`'s single timeout — a
  transient failure is just skipped and picked up next tick.
- **No authentication on the review-gate endpoints.** `decided_by` is a
  free-text field the caller supplies, not verified against a login
  session — wire it to whatever auth the rest of the backend adopts
  before this is exposed beyond a trusted operator.
