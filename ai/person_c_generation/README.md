# Person C — Answer Generation & Evaluation

Consumes a Shape-3 `retrieval_result` (from Person B) and produces a Shape-4
`final_answer`. Built and tested entirely against a hand-written fixture —
no dependency on Person B's real code yet.

## Files

```
person_c_generation/
├── fixtures/
│   ├── fake_retrieval_result.json           # answerable case
│   └── fake_retrieval_result_abstain.json   # unanswerable / low-confidence case
├── prompts/
│   └── system_prompt.txt      # the exact runtime prompt sent to the LLM
├── generate.py                # build_prompt / call_llm / parse_llm_response / generate_answer
├── eval/
│   ├── test_questions.json    # 15 questions, mix of answerable + deliberately unanswerable
│   └── eval_runner.py         # checks citation correctness + abstention behavior
├── requirements.txt
└── README.md
```

It also imports `../shared/schema.py` for the dataclasses (`Chunk`,
`Classification`, `RetrievalResult`, `MatchedChunk`, `FinalAnswer`,
`Citation`) shared across all three people's modules.

## Setup

```bash
pip install -r requirements.txt --break-system-packages
export ANTHROPIC_API_KEY=sk-ant-...   # only needed for real (non-mock) calls
```

## Running it

```bash
# Mocked LLM call — no API key needed, deterministic, good for quick sanity checks
python generate.py --mock

# Mocked, abstain-case fixture
python generate.py --mock --abstain

# Real call to the Anthropic API
python generate.py

# Real call with a custom query against the same fixture chunks
python generate.py --query "Does the phytopharmaceutical proviso apply here?"
```

Output is always the Shape-4 JSON:

```json
{
  "answer_text": "...",
  "citations": [{"act_name": "...", "section": "...", "source_url": null}],
  "confidence": 0.84,
  "abstained": false,
  "disclaimer": "This is informational, not legal advice."
}
```

## Running the eval suite

```bash
cd eval
python eval_runner.py          # mocked, offline — fast iteration
python eval_runner.py --live   # real API calls against all 15 questions
```

The runner checks two things per question:
1. **Citation correctness** — for answerable questions, the expected
   `{act_name, section}` must appear in the model's returned citations.
2. **Abstention correctness** — for the deliberately unanswerable
   questions, the model must return `abstained: true`.

It prints a `[PASS]`/`[FAIL]` line per question and a final `N/M passed`
summary, and exits non-zero if anything failed (so it's CI-friendly).

## Swapping in the real retrieval module later

`generate_answer(retrieval_result, ...)` takes a `RetrievalResult` object —
it doesn't care whether that object came from
`fixtures/fake_retrieval_result.json` or from Person B's live
ChromaDB/SQLite-backed retrieval function. To wire it up for real:

```python
# before (fixture)
retrieval_result = load_retrieval_result_from_fixture()

# after (real)
from person_b_retrieval.retrieval import retrieve
retrieval_result = retrieve(query, jurisdiction="india", ...)
```

No changes needed inside `generate_answer()` itself.

## Notes on the LLM call

- `MockLLM` in `generate.py` is a deterministic stand-in used by `--mock`
  and by the eval runner by default, so nobody needs a live API key just to
  confirm the plumbing (prompt formatting, JSON parsing, citation checks)
  works.
- The real path (`call_llm`) uses the standard `anthropic` Python SDK and
  reads `ANTHROPIC_API_KEY` from the environment. Set `LLM_MODEL` to
  override the default model string.
- `parse_llm_response` strips ```` ```json ```` fences and falls back to
  regex-extracting the first `{...}` block, in case the model adds stray
  preamble text despite the instruction not to.
