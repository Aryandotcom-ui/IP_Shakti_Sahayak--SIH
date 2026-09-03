# IP-SAKTI — document ingestion pipeline

Turns PDFs of Indian and international IP/regulatory law into validated,
version-tracked, embedded chunks.

```
PDFs → extract → section → chunk → metadata → validate
     → SQLite (version tracking) → embed only what changed → ChromaDB
```

## Install

```bash
pip install -r ai/requirements.txt
```

## Run

All commands below are run from the repository root, since `ai/` is an
importable package (`python -m ai.<module>`), not a standalone script
directory.

```bash
# generate test fixtures (two statutes, one scanned PDF, one corrupt file)
python -m ai.make_test_pdfs data/pdfs

# chunk and validate without writing anything
python -m ai.cli data/pdfs --manifest ai/corpus.yaml \
    --dry-run --json-out build/chunks.json

# full ingest
python -m ai.cli data/pdfs --manifest ai/corpus.yaml

# add a document that isn't in the manifest yet
python -m ai.cli data/pdfs/new-rules.pdf --interactive

# once the corpus is stable — refuse to guess any metadata
python -m ai.cli data/pdfs --manifest ai/corpus.yaml --strict

# 5 sample chunks for whoever is building retrieval
python -m ai.dump_samples --from-json build/chunks.json -n 5

python -m pytest ai/ -q
```

Exit codes: `0` all files ingested, `1` some files failed (the rest still
ingested), `2` bad arguments or manifest, `3` embedding model unavailable.

## Output contract

`Chunk.to_dict()` emits exactly these eight keys, in this order. Anything
else the pipeline learns (page number, chapter, which metadata was
inferred vs. read from the manifest) goes to SQLite, never into the JSON.

```json
{
  "chunk_id": "the-patents-act-1970--s3",
  "text": "The Patents Act, 1970 — Section 3: What are not inventions\n\n3. ...",
  "jurisdiction": "india",
  "instrument_type": "statute",
  "act_name": "The Patents Act, 1970",
  "section": "Section 3",
  "effective_date": "2005-04-01",
  "source_url": "https://www.indiacode.nic.in/handle/123456789/1979"
}
```

`chunk_id` is deterministic — `{act-slug}--{section-slug}[--pN]` — so
re-ingesting the same PDF updates the same rows instead of duplicating
them. Oversized sections get `--p1`, `--p2` suffixes.

Every chunk's `text` opens with `{act_name} — {section}: {heading}`. That
makes the chunk self-describing: the embedding carries the locator, and a
retrieved chunk read on its own still says what it is.

## Design notes

**A section is never split across chunks.** That is the load-bearing
guarantee. If s.3 and s.4 end up in one chunk, or s.3 is cut in half, the
citation shown to the user stops matching the text beside it and the
whole grounding claim collapses. `tests/test_ingest.py` pins this.

Three things break naive heading regexes on real gazette PDFs, and each
has a named guard in `sectioner.py`:

| Problem | Guard |
|---|---|
| Contents pages look like a run of headings | `_drop_toc_lines` + `_suppress_toc` — a contents entry is a heading with no operative text after it |
| Sentences starting with a number, and sub-clauses, match the heading pattern | `_longest_increasing` — real sections number monotonically, so keep the longest increasing run and drop the rest |
| A section longer than the embedding window still has to be split | `_split_oversized` — cuts only at sub-clause boundaries, repeats the heading on every part, never mid-sentence |

**Metadata precedence**: manifest → `--interactive` → inference →
failure under `--strict`. Inference exists to make the first pass fast,
not to be trusted. Every inferred value is recorded in the chunk's
provenance, so the corpus lead can filter for what was guessed and verify
it by hand. A wrong `effective_date` is the worst silent failure here —
the as-of filter would then serve repealed law as current.

**Amendments** go in `section_effective_dates` in the manifest. The
Patents Act commenced in 1972, but s.3(d) only exists in its current form
from 2005. Without the override, every section inherits the parent Act's
date and the as-of filter is wrong.

**Version tracking**: `chunks` holds the four agreed columns.
`chunk_versions` sits alongside and keeps the history — when a
provision's text changes, the old hash is closed out with a
`superseded_at` and the new one opened. That is what makes the corpus
version-tracked rather than merely timestamped, and it is what lets you
answer "when did this chunk change under us?".

Content hashes are computed on whitespace-normalised text, so a re-export
of the same PDF does not look like an amendment. Re-ingesting an
unchanged corpus embeds nothing:

```
registry          0 new, 0 changed, 12 unchanged
embedded          0 (skipped 12)
```

Chunk ids in the registry that a run no longer produces are reported as
orphans and **never auto-deleted** — usually it means a section was
renumbered, and deleting corpus without a human looking at it is how a
citation quietly disappears.

## Error handling

One bad file never sinks a run. Failures are collected and reported, and
the exit code is non-zero.

| Condition | Behaviour |
|---|---|
| Corrupt / not a PDF | `PDFOpenError`, file skipped |
| Encrypted | `PDFOpenError` asking for a password |
| Scanned, no text layer | `ScannedPDFError` telling you to run `ocrmypdf` |
| Partially scanned | warning naming the page count; text pages still ingest |
| Text layer empty after cleaning | `EmptyPDFError` |
| No sections detected | whole document becomes one `Preamble` chunk |
| Schema violation | `SchemaError` naming the chunk and field |

OCR is deliberately **not** built in. Silently OCR-ing a scan produces
plausible-looking text with wrong section numbers, which is worse than a
loud failure in a system whose entire value is citation accuracy. Run
`ocrmypdf input.pdf output.pdf` yourself, eyeball it, then ingest.

## Embeddings

Default `BAAI/bge-small-en-v1.5` (384-dim, CPU-friendly). Documents are
encoded with the `passage: ` prefix; **the retrieval service must use
`query: ` and the same model**, or the vectors are meaningless.

`--allow-fallback-embeddings` swaps in a deterministic hashing embedder
so the pipeline, its tests and CI run with no model weights and no
network. It produces correctly-shaped vectors that are semantically
worthless — fine for plumbing tests, never ship an index built with it.

## Handing off

`sample_output.json` holds five chunks chosen for spread, not the first
five: both jurisdictions, several instrument types, and a multi-part
chunk if one exists. Preambles are deprioritised because every document
has one and none of them exercise the section logic.

For retrieval, the fields to filter on are `jurisdiction` (the toggle)
and `effective_date` (the as-of cursor). Both are mirrored into Chroma
metadata alongside `content_hash`.
