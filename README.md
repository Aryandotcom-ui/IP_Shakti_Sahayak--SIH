# IP-SAKTI Sahayak

Multilingual, citation-grounded AI assistant for Ayurvedic intellectual
property and regulatory guidance.

Ask a question in plain language and get an answer that names the sections
it rests on, shows you their verbatim text, and screens your facts against
the access-and-benefit-sharing duties that Ayurvedic IP filings trigger —
the ones applicants usually do not know to ask about.

## Run it

You need Python 3.11+, Node 18+, and this repository. One command:

```bash
./scripts/run.sh
```

Then open **<http://localhost:5173>**.

That installs dependencies, builds the search index from `data/pdfs` (about
a minute, first run only), and starts the API and the web UI together.

> **Open the URL, not the file.** Double-clicking `frontend/index.html` in a
> file manager cannot work. The page is compiled by the dev server when it is
> requested, and a `file://` page has no origin from which to reach the API,
> so it shows the sample-data banner no matter what else is running. If the
> banner says the API is unreachable, the backend is not running — start it
> with the command above.

Other options:

```bash
./scripts/run.sh --backend    # API only; docs at localhost:8000/docs
./scripts/run.sh --rebuild    # discard and rebuild the search index
```

### Generated answer wording is off by default

Set `ANTHROPIC_API_KEY` to have a model write the prose:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
./scripts/run.sh
```

Without it the wording comes from a deterministic stand-in and every answer
is labelled **"Canned prose — no API key"** in the UI. Retrieval, citations,
confidence, deadlines and compliance screening are real either way; only the
sentence phrasing is affected. Passing canned text off as a generated answer
is the failure this project exists to prevent, so the label is not optional.

## What is in the box

| Path | What it does |
|---|---|
| `ai/` | PDF extraction, sectioning, chunking, embedding, retrieval, abstention |
| `ai/compliance/` | Defeasible ABS / IP obligation graph; obligations suppressed by exemptions |
| `ai/patent_prep/` | Intake, prior-art precheck, Form 1/3/27 drafts, deadline tracking |
| `ai/updates/` | Source watcher and tiered review gate for amended law |
| `ai/audit.py` | DPDP-aligned audit trail and licensed-source citation gate |
| `ai/translation.py` | Bhashini translation; retrieval always runs on English |
| `backend/` | FastAPI service over the above |
| `frontend/` | React web UI (Vite), proxied to the API in development |
| `data/pdfs/` | The 17-document legal corpus (statutes, rules, treaties, guidelines) |

The search index (`data/chroma/`) is **not** in version control. It is
derived from `data/pdfs` and rebuilds in about a minute, so it is generated
rather than versioned.

## Tests

```bash
python3 -m pytest -q
```

## Known limits

These are real and worth knowing before you rely on anything here.

- **13 of the 17 corpus documents have no `source_url`**, so their citations
  cannot link out to the official text. The UI marks these "no public link".
  They are fully ingested and quoted verbatim; there is just no verified URL
  on file. Filling these in needs a machine that can reach the official
  sites.
- **The offline embedder is lexical.** `--model tfidf` is character-ngram
  TF-IDF, so it matches wording rather than meaning: a question phrased far
  from the statute's language can retrieve the wrong Act. It exists so the
  system runs with no model download. For better retrieval, install
  `sentence-transformers`, uncomment it in `ai/requirements.txt`, and rebuild
  with `./scripts/run.sh --rebuild` — queries must be encoded in the same
  space as the chunks, so switching embedders *requires* a rebuild.
- **Deadlines marked "unverified"** come from rules whose current figures
  were not confirmed against amended text; the request-for-examination
  window in particular changed in 2024. Confirm before relying on any date.
- **Nothing here is legal advice.** Every obligation must be checked against
  the bare text of the cited provision and with a registered patent agent.

## Licence and disclaimer

Informational only. Not legal advice. The corpus consists of public legal
instruments; each document's provenance is recorded in `ai/corpus.yaml`.
