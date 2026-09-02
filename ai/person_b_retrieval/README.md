# Person B — Retrieval & Confidence Module

## What's here

```
person_b_retrieval/
├── fixtures/fake_chunks.json   # 10 hand-written fake chunks, matching Shape 1 exactly
├── schema.py                    # Chunk, Classification, MatchedChunk, RetrievalResult
├── embeddings.py                # TF-IDF stand-in for a real embedding model
├── retrieval.py                 # filter_chunks() + retrieve() — the main entry point
├── confidence.py                # compute_confidence() + decide_abstain()
├── test_retrieval.py            # 8 tests, all passing
└── sample_output.json           # a real Shape-3 output, for Person C to build against
```

## How to run it

```
pip install scikit-learn numpy pytest --break-system-packages
python -m pytest test_retrieval.py -v
```

## What it actually does

`retrieve(query, all_chunks, embedder, jurisdiction, classification, top_k)` runs two stages:

1. **Metadata pre-filter** (`filter_chunks`) — narrows the candidate chunks by
   jurisdiction first, then by formulation type using a lookup table
   (`FORMULATION_RELEVANT_ACTS` in retrieval.py) that maps a formulation type
   to the acts most relevant to it. This is the "use the classification
   answers to narrow the search before searching" mechanism from the project
   plan — implemented here as a simple dict, upgradeable to a real knowledge
   graph later without changing the function's interface.
2. **Semantic search over the narrowed set** — embeds the query and the
   filtered candidates, ranks by cosine similarity, and returns the top
   matches above a minimum floor.

Confidence is computed from the top similarity score (plus a small bonus if
multiple chunks agree), and `should_abstain` is set true when confidence is
below a threshold or nothing passed the filter — matching Shape 3 exactly.

## Important: the embedding model is a placeholder

This sandbox has no internet access to huggingface.co, so `embeddings.py`
uses TF-IDF over character n-grams instead of a real sentence-embedding
model — it's a stand-in that behaves *directionally* like semantic search
(catches "patented"/"patentability" as related) but is much cruder than a
real model. Two things to know:

1. **The interface won't change.** `Embedder.fit(texts)` and
   `Embedder.embed(texts)` are the only two methods `retrieval.py` calls.
   Swapping in a real model later means rewriting the inside of those two
   methods only — see the docstring at the top of `embeddings.py` for the
   exact swap.
2. **The thresholds will need re-tuning.** `MIN_SIMILARITY_FLOOR` in
   retrieval.py and `ABSTAIN_THRESHOLD` in confidence.py were tuned against
   this crude embedder's score range (roughly 0.1–0.4). A real embedding
   model separates relevant from irrelevant text far more cleanly, so once
   you swap it in, re-run the test suite and adjust these two constants
   until the abstention tests behave correctly again.

## For integration with Person A

Once Person A's real ChromaDB store exists, replace the fixture-loading line
(`json.load(open('fixtures/fake_chunks.json'))`) with a query against their
store, converting results into `Chunk` objects the same way `Chunk.from_dict`
does now. Nothing else in `retrieval.py` or `confidence.py` needs to change.

## For integration with Person C

Person C should use `sample_output.json` (a real Shape-3 result produced by
this module) as their fixture, and eventually call `retrieve()` directly
instead of reading a static file.
