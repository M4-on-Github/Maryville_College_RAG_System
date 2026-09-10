# Maryville College RAG

A retrieval-augmented question-answering system over the public web presence of
**Maryville College** (Maryville, Tennessee) — `maryvillecollege.edu` and its
SmartCatalogIQ course catalog.

The interesting question is not "can a language model answer questions about a
college website." It is whether a small, cheap, mostly-local pipeline can answer
**cross-silo** questions — ones whose answer is spread across the pages of two or
more offices that do not link to each other — and whether it knows when to say it
does not know.

> Not affiliated with Maryville University in St. Louis, a different institution.

## Crawl policy

Three lines, and they are enforced in code rather than promised in a document:

1. **Public pages only.** No authenticated content, no student records. There is
   no FERPA surface in this project and it stays that way.
2. **One request per second**, with a user agent naming the project and a contact
   address. A crawl without a reachable contact fails loudly rather than running.
3. **`robots.txt` is honored.** Every URL passes the robots check before a fetch
   is attempted, and a refusal is recorded in the crawl manifest with the exact
   rule that matched.

Every URL the crawler *considers* gets a manifest record, fetched or not. A
corpus that records only its successes cannot tell you what is missing from it.

## Documents

| File | What it is |
|---|---|
| `PLAN.md` | The design doc: what is being built and why |
| `tasks/plan.md` | The execution plan: ordered tasks, acceptance criteria, verification |
| `tasks/todo.md` | The backlog |
| `decisions/` | Decisions made once and not relitigated |
| `RESULTS.md` | Generated from `runs/`, never hand-edited |

## Development conventions

Every swappable pipeline stage is a class behind an interface, named by
`config.yaml` and instantiated by the runner. An ablation arm is a config value,
not an edited function body. Checkpoints A through H are the sprint boundaries;
each one demonstrates working software or it is not done. Both conventions are
spelled out in `tasks/plan.md`.

## Setup

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
pytest
```

Generation runs against Ollama Cloud's free tier. Copy `.env.example` to `.env`
and fill in the key; embedding and reranking run locally and need no key.

## Status

Phase 0 (foundations) is in progress. No corpus has been crawled yet.
