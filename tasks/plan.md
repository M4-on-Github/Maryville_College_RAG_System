# Implementation Plan — Maryville College RAG

Companion to `PLAN.md` (the design doc). This file is the **execution** plan:
ordered, verifiable tasks. `PLAN.md` says *what and why*; this says *in what
order, and how you know it worked*.

## Overview

Build a cross-silo RAG chatbot over `maryvillecollege.edu` + the SmartCatalogIQ
catalog, with a reproducible ablation harness. Generation runs on Ollama Cloud
free tier (`gpt-oss:20b-cloud`); embedding and reranking run locally.

## Architecture decisions carried in

| Decision | Rationale | Ref |
|---|---|---|
| News sitemap excluded | ~850 dated posts; stale-date hallucination risk; doubles corpus | PLAN §1 |
| SmartCatalogIQ needs a nav-tree adapter | robots permits it, but declares **no sitemap** | PLAN §1 |
| Chunk cap 400 tok; sweep `(chunk_size, k)` coupled | embedder truncates at 512; the two trade off under a fixed context budget | PLAN §2c |
| Retrieval ablations run before any generation | retrieval metrics cost zero quota | PLAN §2b, §4a |
| Generation scored by a validated ladder | no frontier judge; self-judging is circular | PLAN §4d |
| τ calibration method undecided — 3 candidates to test | cross-encoder scores aren't cross-query calibrated | PLAN §4e |
| 40/20/40 stratified split, test touched once | τ and hyperparameters are fitted | PLAN Phase 2 |

## Development conventions — OOP and Agile

Two standing constraints, decided 2026-09-10. They bind every task below.

### Object-oriented design

Every pipeline stage is a **class behind an interface**, not a module of loose
functions. The reason is not style: this project's whole experimental program is
swapping one implementation for another and measuring the difference. An ablation
should be a constructor argument, never an edited function body.

| Seam | Abstract base | Implementations swapped in ablations |
|---|---|---|
| Retrieval leg | `Retriever.search(query, k) -> list[Hit]` | dense, BM25, literal/regex |
| Fusion | `Fuser.fuse(list[list[Hit]]) -> list[Hit]` | RRF, weighted, MoR |
| Reranking | `Reranker.rerank(query, hits) -> list[Hit]` | cross-encoder, identity (off) |
| Chunking | `Chunker.chunk(Document) -> list[Chunk]` | heading-aware, fixed-window |
| Extraction | `Extractor.extract(RawPage) -> Document` | trafilatura, fallback |
| Generation | `Generator.generate(Prompt) -> Iterator[Event]` | cloud model, stub, cached replay |
| Query rewriting | `Reformulator.reform(query, history) -> list[str]` | each rung of the ladder |
| Scoring | `Scorer.score(Answer, Gold) -> Score` | Tier 0–3 of the ladder |

Rules that follow from this:

- **`config.yaml` names classes.** The runner instantiates from the config; adding
  an ablation arm means adding a class and a config value, not a branch.
- **Value objects are frozen dataclasses** — `Hit`, `Chunk`, `Document`, `Score`,
  `Event`. Nothing downstream mutates what it was handed.
- **Composition over inheritance below the interface.** The base classes exist to
  define a contract; a two-level hierarchy is a smell, not a design.
- **No I/O in constructors.** Index loading, HTTP clients and model handles are
  injected, so every stage is testable with a fake.
- **The service layer depends on interfaces only** (T24) — the existing rule that
  no web framework may be imported there is the same rule stated narrowly.

An abstract base with exactly one implementation and no ablation planned against
it is over-engineering; write the concrete class and extract the interface when
the second implementation actually arrives.

### Agile process

Solo project, so the ceremony that assumes a team is dropped and the mechanics
that do real work are kept.

| Agile concept | What it is here |
|---|---|
| Product backlog | `tasks/todo.md` — ordered, re-ordered freely, nothing starts without criteria |
| Sprint | The span between two checkpoints; **Checkpoints A–H are the sprint boundaries** |
| Increment | Each checkpoint ships something demonstrable and reviewed, not a half-integrated branch |
| Definition of done | The task's acceptance criteria **plus** its verification step passing |
| Sprint review | The checkpoint's own review gate; Checkpoint D is a real GO/NO-GO |
| Retrospective | The dated `## Resolved` block at the foot of this file |
| Velocity | Not tracked. A solo velocity number measures nothing |
| Standup, planning poker, story points | Dropped |

Rules that follow:

- **Vertical slices, not horizontal layers.** Prefer a thin end-to-end path that
  answers one question badly over a perfect crawler with nothing behind it. This
  is why T16 is an end-to-end sanity check placed before the tuning work.
- **Working software at every checkpoint.** If a checkpoint cannot be
  demonstrated, it is not done, regardless of how much code exists.
- **The backlog is re-orderable; the frozen artifacts are not.** Pre-registered
  analysis plans (T16b), `corpus.lock`, `split.lock` and the Checkpoint E config
  are deliberately outside the agile surface. Responding to change does not
  extend to changing the metric after seeing the result.
- **Refactor continuously, inside a checkpoint.** Interfaces get extracted when
  the second implementation arrives, not speculatively before it.

## Dependency graph

```
T1 config+run-log ──┬── T2 robots+ratelimit ── T4 manifest ── T5 fetcher ── T6 extract
                    │                                          │
                    │                        T7 catalog adapter ┘
                    │                                          │
                    │                          T8 silo mapper ──┤
                    │                                          v
                    │                                   T9 chunker ── T10 incremental
                    │                                          │
                    └── T3 quota calibration                   v
                                                        T11 indexes
                                                               │
              T12 gold schema+splits ── T13 gold authoring      │
                                    └──────────┬───────────────┘
                                               v
                                    T14 retrieval eval harness
                                               │
                                    T15 Phase 3a baseline
                                               │
                                    T16 Phase 3b sanity  <-- RISK GATE
                                               │
                                    T16b analysis plan (pre-registered)
                                               │
                                    T17 ablation runner
                                               │
                                    T18 free retrieval ablations
                                               │
                          T19 scoring ladder ──┤
                                               v
                                    T20 Phase 3c gen baseline
                                               │
                                    T21 τ study ── T22 metered ablations
                                               │
                                               v   [Checkpoint E — config frozen]
                                    T23 event contract
                                               │
                                    T24 service callable (no web framework)
                                               │
                                    T25 FastAPI+SSE shell
                                               │
                          ┌────────────────────┼────────────────────┐
                          v                    v                    v
                   T26 early sources    T29 ref client       T27 refusal routing
                          │                                         │
                          └─────────────────┬───────────────────────┘
                                            v
                                   T28 conversation memory
                                            │
                                            v   [Checkpoint F — backend done]
                          T30 results table ── T31 README ── T32 limitations
                                    │                     └── T33 demo
                                    v   [Checkpoint G — shipped]
                          T34 re-crawl + alerts ── T35 gold staleness
                                    └── T36 re-run trigger
```

**T8 also depends on T4**, not only T6: silo discovery step 1 is a path-prefix
histogram over the manifest.

---

# Phase 0 — Foundations

## Task 1: Config schema + run-logging harness

**Description:** The spine everything else writes to. One `config.yaml` fully
describes a pipeline; one run directory captures a result with its provenance
locks.

**Acceptance criteria:**
- [ ] `config.yaml` round-trips to a typed object; unknown keys are an error
- [ ] Config **names implementation classes** per seam; the runner instantiates from the config with no `if` on arm names
- [ ] `runs/<ts>_<confighash>/` created with `config.yaml`, `metrics.json`, `per_query.jsonl`, `corpus.lock`, `model.lock`, `split.lock`, `notes.md`
- [ ] Run id = timestamp + config hash; identical configs produce identical hashes
- [ ] `per_query.jsonl` is appended incrementally and a killed run leaves a valid resumable file

- [ ] Frozen dataclasses defined for `Hit`, `Chunk`, `Document`, `Score`, `Event`; mutation raises

**Verification:** `pytest tests/test_runlog.py`; kill a run mid-write and confirm the partial file parses line-by-line. Assert a config naming a fake class instantiates it without touching runner code.

**Dependencies:** None · **Scope:** M

## Task 2: Robots enforcement + rate limiter

**Description:** The two load-bearing crawl rules, as code. The separate policy
document is dropped — it becomes three lines in the README (§1). The robots
parser is needed anyway to discover sitemaps, so enforcement is nearly free.

**Acceptance criteria:**
- [ ] Robots parser refuses any URL matching a `Disallow`, and **returns the matched rule string** for the manifest `reason` field
- [ ] Rate limiter measurably holds ≤1 req/sec across concurrent callers
- [ ] UA string with a contact address is set from config, and a request without one fails loudly
- [ ] Unit test asserts each of the five known WordPress disallow paths is rejected
- [ ] README carries the three-line policy statement

**Verification:** `pytest tests/test_robots.py`; timing test over 10 queued URLs takes ≥10s.

**Dependencies:** None · **Scope:** S

## Task 3: Ollama Cloud smoke test + quota calibration

**Description:** Empirical, not a decision. Establishes the budget every later
phase is designed around. **Do this early — it is the project's largest unknown.**

**Acceptance criteria:**
- [x] Authenticated call to `gpt-oss:20b-cloud` returns text
- [x] `num_ctx` set explicitly; a prompt exceeding it raises rather than truncating silently
- [x] Reasoning channel parsed and separated from visible answer
- [x] 20 sample questions run; per-query cost recorded (`eval_duration` /
      `prompt_eval_duration` do not exist for this model -- see below; client
      wall-clock, token counts and `timing_source` are recorded instead)
- [x] `docs/quota-calibration.md` states seconds/query and derived **full gold-set passes affordable per weekly reset**

**Verification:** `docs/quota-calibration.md`, generated from
`runs/20260910T224550Z_f4f0da4d39e0/`. 20 of 20 calls succeeded. Median
**2.32 s/query** (95% CI 1.76-2.97, n=20) on realistic k=5 RAG prompts of
~1,077 prompt tokens. Regenerating the report from the run directory costs
nothing: the calls are on disk and the truncation probe is cached.

### Four things this task settled that PLAN left open

**The endpoint returns no durations.** `usage` carries token counts once
`stream_options: {include_usage: true}` is sent, but there is no `eval_duration`
and no `prompt_eval_duration` on the OpenAI-compatible surface. **Client
wall-clock is the cost measure**, and every `Usage` record says so in
`timing_source` rather than leaving a reader to assume. Wall-clock includes
queueing behind the single free-tier concurrency slot, so it is an upper bound
on GPU time -- the safe direction for a budget.

**The native endpoint does not rescue it, and PLAN said it would.** PLAN 2a
asserts that Ollama returns `total_duration`, `prompt_eval_duration` and
`eval_duration` on the final chunk "for cloud models too", and recommends the
native surface for eval runs on that basis. Probed with three cheap calls
(`probe_native_durations`, cached to `native_probe.json`): `/api/chat` returns
`total_duration`, `prompt_eval_count` and `eval_count`, and **neither**
`prompt_eval_duration` **nor** `eval_duration`. `total_duration` is genuinely
server-side and ran about 0.2s under wall-clock on 1.3-2.1s calls, so it is a
tighter number if a later run wants one -- but it is a total. Prompt processing
cannot be separated from generation, so an arm that inflates the prompt and an
arm that inflates the answer are indistinguishable on cost. PLAN 2a is corrected
in place and the open question is closed.

**`num_ctx` really does truncate silently.** Probed deliberately: ~15,000
estimated tokens sent against `num_ctx` 8192 with the client guard stood down.
The server counted 8,243 prompt tokens, returned no error and no warning, and
answered without the fact planted at the front of the prompt. This is why
`OllamaCloudGenerator.check_prompt` raises instead of trimming, and why
`enforce_context=False` exists in exactly one place: the probe that proves it.

**The budget is not the constraint PLAN assumed it was.** PLAN 2a sized the
project around 5-15 s/query and a 12-40 minute pass. The whole metered ablation
program -- 10 arms over the 120-question test split -- is **1,200 queries and
about 0.8 hours** of sequential wall-clock. That does not license spending the
test split more freely; it moves the OFAT restriction on the metered half from a
budget decision to a **statistical** one, to be re-argued at Checkpoint D
against the pre-registered analysis plan and not against cost.

A fourth, smaller finding worth carrying forward: **83% of generated tokens are
reasoning**, not answer. Any latency comparison between arms is mostly a
comparison of how much the model thought.

**Dependencies:** None · **Scope:** S

### ✅ Checkpoint A
- [x] Run harness writes complete, resumable run dirs — the calibration run has all three locks, resumed cleanly, and regenerates its report without re-spending
- [x] Robots enforcement passes tests
- [x] Quota budget is a written number, not an assumption — `docs/quota-calibration.md`
- [ ] **Human review before building the crawler** — *outstanding.* The crawler is built and tested; two rehearsals totalling 55 pages have run. The full 2,454-URL pass is held pending sign-off

---

# Phase 1 — Corpus

## Task 4: Sitemap parser → crawl manifest

**Description:** Build `corpus/manifest.jsonl` as **one record per URL
considered, not per URL fetched** (§1). A corpus that records only its successes
cannot tell you what is missing from it.

**Acceptance criteria:**
- [ ] Parses the two in-scope WordPress sitemaps; **news sitemap excluded by config, not by omission**
- [ ] Every URL considered gets a record with `status` ∈ `fetched` / `excluded` / `failed` / `skipped`
- [ ] **Every non-`fetched` record carries a class-prefixed `reason`**: `robots_disallow:<rule>` · `policy:<name>` · `http_error` · `extraction_empty` · `unchanged_hash`. A bare "excluded" fails review
- [ ] Excluded URLs stay *in* the manifest — exclusion is recorded, not silent
- [ ] `lastmod` recorded but flagged untrusted (documented: 2017 post carries a 2026 lastmod)
- [ ] Every URL passes the Task 2 robots check before fetch is attempted
- [ ] `scripts/coverage.py` reports counts by status and by reason class

**Verification:** Manifest count is 800–900 for pages; zero `/news/` URLs with
status `fetched`; ~850 present with `policy:news_excluded`. Coverage report
totals reconcile against sitemap URL count exactly.

**Dependencies:** T2 · **Scope:** M

## Task 5: Polite fetcher + raw snapshot store

**Acceptance criteria:**
- [x] Fetches manifest URLs at ≤1 req/s with the policy UA — `--rps` above 1.0 is refused outright
- [x] Stores raw HTML content-hashed and dated; re-fetch of unchanged page creates no duplicate
- [x] Resumable — interrupting and restarting does not refetch completed URLs
- [x] Failures logged with status codes; run does not abort on a single 404

**Verification:** `pytest tests/test_fetcher.py` — 19 tests against a loopback HTTP server,
including two consecutive full runs with 0 new snapshots on the second, an interrupted pass
resuming without refetching, and a robots-forbidden URL that is never requested. A 25-page
rehearsal against the live site succeeded. **The full 2,454-URL pass is held for Checkpoint A
sign-off** — it is ~41 minutes of sustained traffic to someone else's server.

**Dependencies:** T4 · **Scope:** M

## Task 6: Extraction + regression snapshot test

**Acceptance criteria:**
- [x] `trafilatura` extraction produces main content with nav/footer chrome removed
- [x] 17 hand-picked pages (one per silo) have committed expected-text snapshots, HTML input included
- [x] Extraction regression test fails loudly on drift
- [x] Empty or suspiciously short extractions are flagged, not silently kept

**Verification:** `pytest tests/test_extraction_snapshots.py` (58 tests) and
`tests/test_extraction_pipeline.py`. On the 54-page rehearsal corpus, 46 documents
extracted and 8 flagged — 1 empty and 7 boilerplate-only. `scripts/extract_corpus.py`
exits non-zero above a 20% empty share.

**Two things this task turned up that PLAN.md did not anticipate:**

1. Per-page extraction is not enough. On pages with little prose of their own the
   extractor returns the site footer and calls it the article — about one page in
   seven. A single page cannot tell its own boilerplate from its content, so
   `BoilerplateFilter` learns the template from line frequency across the corpus and
   runs as a second pass. Pages left with nothing become `extraction_empty`.
2. The site publishes no visible breadcrumb markup, but its SEO plugin emits a JSON-LD
   `BreadcrumbList` on nearly every page. That is the site's own stated hierarchy,
   better than one inferred from URL paths, and Task 8 should check silo mapping
   against it. The accounting program's crumb is *Programs of Study > Accounting
   Minor*, which the URL alone would never have given.

**Dependencies:** T5 · **Scope:** M

## Task 7: Catalog coverage assessment (was: SmartCatalogIQ nav-tree crawler adapter)

**What decision 0001 settled that PLAN left open.** The acceptance criteria
below assumed a separate SmartCatalogIQ host with no sitemap, needing
nav-tree discovery. Measured false on 2026-09-10: the catalog is three
WordPress custom post types on `www.maryvillecollege.edu` itself
(`smart_catalog_course`, `_block`, `_prog`), already enumerated by
`wp-sitemap.xml` and already covered by the ordinary sitemap-driven crawl
(T4/T5). There is no separate host, no missing sitemap, and no nav tree to
walk — so there is nothing for a nav-tree adapter to do. All three
`smart_catalog_*` types also match a robots `Disallow` rule, so we hold no
text from them regardless (1,146 URLs, the single largest exclusion in the
corpus). Task 7 becomes what decision 0001 calls it: confirm what that
exclusion costs, confirm the course-level substitute, and write the gap up.
No terms-of-use check applies — we are not crawling that vendor surface at
all, by any adapter.

**Findings, verified against the completed full crawl (2026-09-10):**
- [x] ~~Catalog footer checked for terms of use~~ — moot; see above, superseded by decision 0001
- [x] ~~Nav-tree walk discovers all 13 sections~~ / ~~`/sitecore/` never requested~~ — no nav-tree crawl exists to do this
- [x] ~~Discovered URLs enter `manifest.jsonl` with `source: "catalog-nav"`~~ — the sitemap-driven crawl already accounts for all `smart_catalog_*` URLs (1,146) under their own `wp-sitemap-posts-smart_catalog_*` sources, all marked `robots_disallow` — one corpus accounting, achieved for free
- [x] **Course-level substitute confirmed:** `/academics/course/*` (772 URLs, robots-allowed) carries the same course code/title/credits/description/prerequisites data as the disallowed `smart_catalog_course` pages. 763/772 (98.8%) survived extraction with real content; the other 9 are individually thin/retired listings, not a systemic gap. Course-level questions ("what is BIO416") are answerable from the corpus.
- [x] **Program-requirements gap confirmed, not just assumed:** sampled `academic_programs` pages (78 extracted) carry narrative program overviews ("Why minor in Accounting at MC?") but no itemized, course-by-course requirement list — that structure lives only in the disallowed `smart_catalog_prog` (138 URLs). Degree/major-requirements questions are therefore a genuine corpus gap, not a retrieval-tuning problem, and decision 0002's referral mechanism (name the Registrar's Office + the public catalog URL) is the intended handling, not a bug to fix later.
- [ ] ~~`catalog_year` stamped on every extracted page~~ / ~~extraction snapshot test extended with 5 catalog pages~~ — deferred to T8 (silo/contact discovery), which is where `catalog_year` stamping is actually driven from; no separate catalog extraction path exists to test

**Verification:** Manifest reconciliation (T4/T6, already passing) accounts for
all 1,146 `smart_catalog_*` URLs as `robots_disallow`. Course-substitute and
program-gap claims verified by direct sampling of `corpus/extracted/documents.jsonl`
against the completed 1,847-document corpus, 2026-09-10.

**Dependencies:** T2, T6 · **Scope:** M

## Task 8: Silo discovery, mapper, and contact-routing table

**Description:** Runs the four-step discovery procedure in §2c. **Absorbs the
former T8b** — the contact table is a byproduct of step 3, not follow-on work,
and treating it as separate is what let it go missing.

The governing test: *a silo is a topic that has an office with a published
contact page.* If you cannot name an owner with an email, it is a topic, not a
silo.

**Acceptance criteria:**
- [x] Step 1 — path-prefix histogram over the manifest, with page counts, committed as data (`scripts/discover_silos.py` -> `data/silo_histogram.csv`, 129 two-level prefixes / 1857 fetched pages)
- [x] Step 2 — top nav and breadcrumb trails harvested; **nav/URL disagreements recorded**, not silently resolved (`scripts/harvest_nav.py` -> `data/nav_top_level.csv`, `data/breadcrumb_vs_path.csv`). The main navbar has 5 dropdown sections (Academics, Admissions, About, Campus Life, Athletics) plus a 4-item utility bar (Alumni, Books & Merchandise, Event Operations, Families). **Disagreement recorded:** the nav's "Athletics" section is a full top-level dropdown with 12 children, but 11 of the 12 point off-domain to `mcscots.com` and vendor sites (conference sites, merchandise) — only `/athletics/` and `/campus-life/intramural-recreation/` are on the crawled domain. Athletics cannot become a real silo from this corpus: the nav promises a section our crawl scope structurally cannot fill (decision 0001's scope is `maryvillecollege.edu` only). 983/1847 documents carry a JSON-LD breadcrumb (864 do not — mostly the `academics/course` custom post type, which has no breadcrumb markup); breadcrumb-vs-path-prefix agreement is left for step 3's per-candidate matching rather than eyeballed in bulk.
- [x] Step 3 (mechanical narrowing done; **matches are candidates, not approved rows** — see below) — `scripts/match_offices.py` parses two sources. (a) `/directories/department/`'s own division-office block: six fixed-pattern rows ("Division of X - Office" / name+title / building / phone+email) that precede the flat personnel directory on the same page — high confidence, the site's own structured listing, written to `data/division_offices.csv`. (b) For the other 25 histogram prefixes, the shortest-URL page under each prefix is scanned for an email+nearby-phone; 15/25 found one, written to `data/office_candidates.csv` with `confidence: low (heuristic)`. Several of the 15 are real generic office addresses (`registrar@`, `alumni@`, `careercenter@`, `international@`, `residence.life@`) but a few are **false positives** — a named faculty member's personal page picked up as the "office" for `academics/faculty` (`jeff.bay@...`), same risk on `about/inside` and `about/faith`. This is exactly the human hand-check decision 0002 requires before anything here becomes `offices.yaml`.
- [x] Step 4 — `data/silos.yaml` + `data/offices.yaml` finalized from the step-3 candidates, after a human reviewed `data/office_candidates.csv` (dropped the `jeff.bay` personal-page email, confirmed four other named-individual rows were acceptable office contacts rather than more of the same mistake — see `decisions/0003-silo-taxonomy.md`)
- [x] `data/silos.yaml` (taxonomy) and `data/offices.yaml` (name → contact URL + email +
      **referral destination URL**, per decision 0002) both exist and are data, not code
- [x] Every offices row carries a destination URL a person should land on. A referral may
      point at a page we never crawled, including a robots-disallowed one; it may never be
      quoted from (decision 0002) — asserted by `tests/test_offices.py`
- [x] Every non-`other` silo has an offices row. 26 silos, each resolving to exactly one office row (`tests/test_offices.py`)
- [ ] ~~Mapper assigns multi-label silos from path + breadcrumb~~ — single-label path-prefix matching only; PLAN §2c resolves single-vs-multi-label at the gold-question level (a page can appear in >1 silo's gold refs), not by tagging one chunk with two silo strings. No breadcrumb signal was usable in practice (checked: faculty-page breadcrumbs don't carry division info)
- [x] `other` rate measured and reported: 10.3% (175/1699), just over the 10% flag line — explained, not hand-waved: 79 of the 175 (45%) are `/news/*` articles, ownerless by the same §2c logic as About/history pages; residual rate excluding those is 5.6%. See `decisions/0003-silo-taxonomy.md`
- [x] Granularity follows the site: 6 academic-division silos, each with its own contact page; a broad `academics` catch-all (61% of the corpus — mostly the 763-page course catalog) owned by the Registrar's Office, the site's own office of record for the catalog
- [x] Final taxonomy + the rationale committed to `decisions/0003-silo-taxonomy.md`, including 7 real office contacts (`admissions`, `finaid`, `title_ix`, `giving`, `families`, `event_operations`, `orientation`) found by full-corpus search after the original heuristic's top-5-shortest-page search missed them

**Verification:** `tests/test_silo_mapper.py` (6 tests) + `tests/test_offices.py`
(4 tests) — every silo resolves to exactly one office row, no path prefix is
claimed twice, every office has an email and an on-domain destination URL.
`scripts/map_silos.py` run for real over the full corpus: 1699 documents
stamped, other rate 10.3%. **Not yet done:** PLAN's own sample-10-URLs-per-silo
hand-check and a live-URL spot-check on three destinations — flagged in
decision 0003 as worth doing before Checkpoint B, not blocking Task 13.

**Dependencies:** T4, T6 · **Scope:** M

## Task 9: Heading-aware chunker + metadata stamping

**What this task settled that PLAN left open.** The acceptance criteria below
assumed `Document.text` carries H2/H3 markers. Measured false:
`TrafilaturaExtractor` uses trafilatura's default plain-text output, which
discards heading tags. A markdown re-extraction of the rehearsal corpus found
at most one or two real headings per page — the site's templates lean on bold
text and paragraph breaks, not semantic headings, for structure. Changing the
extractor to keep them would touch every committed fixture and the
boilerplate filter's learned template for a signal present on a minority of
pages, and would inject `**`/`##` characters into the retrieval text on all of
them. `ParagraphChunker` (`mcrag/chunk/paragraph_chunker.py`) instead packs on
the finest boundary the corpus actually offers — the paragraph break the
extractor already preserves — and treats a real heading, when the extractor
is later changed to keep one, as something only the boundary-detection method
needs to learn about.

**Acceptance criteria:**
- [x] ~~Chunks respect H2/H3 boundaries~~ Chunks respect paragraph boundaries (see above); cap 400 tokens, ~15% overlap
- [x] **No chunk exceeds the embedder's 512-token limit** (asserted per chunk in `chunk()`, not assumed — verified against real `bge-base-en-v1.5` tokenizer over the full 1,847-document corpus: 3,495 chunks, max 509 tokens, 0 violations)
- [x] Every chunk carries: `source_url`, `title`, `breadcrumb`, `silo`, `heading_path`, `crawled_at`, `content_hash`, `catalog_year` (`heading_path` is `(doc.title,)` until the extractor preserves real headings)
- [x] `chunk_size` (`max_tokens`) and overlap are config-driven constructor args, not constants

**Verification:** `tests/test_chunker.py` (15 tests, `FakeTokenCounter`) plus `tests/test_token_counter.py` (4 tests, real tokenizer). Ran over the 46-page rehearsal corpus first (99 chunks, max 454 tokens), then re-validated over the full corpus post-crawl. (Initial full-corpus run showed 1,847 documents/3,495 chunks; that count included 143 duplicate rows from an extraction-pipeline redirect-fan-in bug fixed under T10/T11 below — the corrected corpus is 1,699 documents / 3,237 chunks, max 509 tokens, 0 hard-limit violations.)

**Dependencies:** ~~T8~~ built and tested against the rehearsal corpus without it; `silo` stamps as `()` until T8 fills it · **Scope:** M

## Task 10: Incremental reindex

**Acceptance criteria:**
- [x] Content-hash diff identifies changed pages; `lastmod` used only as a cheap pre-filter — `mcrag.index_pipeline.incremental_reindex`; `lastmod` is not read here at all, it's already spent as a pre-filter at T5 fetch time
- [x] Changed page → delete-by-`source_url` → re-insert; no orphaned chunks — delete-then-upsert, driven purely through the `Indexer` interface so it's index-agnostic
- [x] Unchanged corpus produces a no-op reindex — no indexer is touched at all when every url's hash matches the lock, not just an update that happens to write the same rows
- [x] `corpus.lock` written with the snapshot hash — `write_lock`/`load_lock`, sha256 over sorted-key JSON

**Verification:** `tests/test_index_pipeline.py` (5 tests, `_FakeIndexer`) covers first-run-is-all-changed, true no-op, changed-page delete+reinsert, removed-page delete-only, and lock contents. Also exercised for real by `scripts/build_indexes.py`'s first run against the full corpus (see T11).

**Dependencies:** T9 · **Scope:** M

## Task 11: Build the three indexes

**Acceptance criteria:**
- [x] LanceDB dense index over `bge-base-en-v1.5` embeddings — `mcrag.retrieval.dense.DenseIndex` + `mcrag.retrieval.bge_embedder.BgeEmbedder`
- [x] BM25 index over the same chunk set — `mcrag.retrieval.bm25.BM25Index` (`rank_bm25.BM25Okapi`)
- [x] Literal index supporting substring/regex with the §4c entity patterns — `mcrag.retrieval.literal.LiteralIndex`, entity patterns verbatim from §4c (course_code/form/money); only fires when the query itself matches one
- [x] Embeddings cached on `(model_name, chunk_text_hash)`; rebuild with unchanged chunks re-embeds nothing — `mcrag.retrieval.embedding_cache.EmbeddingCache`, flat append-only JSONL
- [x] All three return chunk ids joinable to metadata — each `Retriever.search` returns `Hit(chunk_id=...)`, joinable back to `corpus/chunks.jsonl`

**Verification:** `tests/test_retrieval_literal.py` (5), `tests/test_retrieval_bm25.py` (4), `tests/test_embedding_cache.py` (3), `tests/test_retrieval_dense.py` (5, fake embedder, no model download in tests) — all pass. Built for real over the full corpus via `scripts/build_indexes.py`: 1,699 documents / 3,237 chunks, `1699 changed, 0 removed, 3237 chunks written` on a from-scratch run; dense index verified to have exactly 3,237 rows with 3,237 unique `chunk_id`s (no duplicates). Full suite: 266 passed.

**Note:** the first run of `scripts/build_indexes.py` reported 1699 changed / 4061 chunks written against an 1847-document corpus — a red flag caught before committing. Root cause: `mcrag/extract/pipeline.py`'s `extract_all` produced one `Document` per manifest record with no dedup on canonical URL, so 143 cases of two different requested URLs redirecting to the same final page each wrote a duplicate row to `corpus/extracted/documents.jsonl`. Fixed by deduping in `extract_all` (prefer the non-redirected request, else the most recently fetched); `scripts/extract_corpus.py`, `scripts/chunk_corpus.py`, and `scripts/build_indexes.py` were then re-run clean.

**Dependencies:** T9 · **Scope:** M

### ✅ Checkpoint B
- [x] Full corpus crawled, extracted, chunked, indexed — 1699 documents, 3237 chunks, dense/BM25/literal indexes built
- [x] Extraction snapshots pass; silo `other` rate acceptable — 10.3%, explained in decision 0003 (residual 5.6% excluding ownerless `/news/*`)
- [x] No chunk exceeds 512 tokens — verified, max 509
- [x] **Human review of 20 random chunks for quality before building the gold set** — cleared, plus the silo-assignment sample and referral-link spot-check from decision 0003

---

# Phase 2 — Gold set

## Task 12: Gold-set schema + split tooling

**Description:** Build the container before writing 300 questions into it.
Retrofitting granularity or conjunctive flags later is miserable. Does not
depend on T8's final `offices.yaml` — `expected_referral` is a free-text field
on the schema; it gets populated with real office data when T13 authors
questions against a finalized `offices.yaml`, not before.

**Acceptance criteria:**
- [x] Schema: `qid`, `slice`, `question`, `gold` (list of **heading/chunk-level** refs, not bare page URLs), `conjunctive: bool`, `notes` — `mcrag.types.GoldQuestion`. Plus decision 0002's field, `expected_referral: str | None`, so refusal correctness can split into refused-correctly and routed-correctly.
- [x] Stratified 40/20/40 split, deterministic from a seed, proportional within every slice — `mcrag.eval.gold.stratified_split`, one `random.Random(f"{seed}:{slice}")` per slice so slices don't perturb each other's draws
- [x] `split.lock` records split hash and which split a run scored — `write_split_lock`/`load_split_lock`, hash is order-independent (sorted-key JSON, sha256)
- [x] Test-access counter that must be incremented explicitly — `TestAccessCounter`; only moves on `.increment(reason)`, logs reason + UTC timestamp, never as a side effect of an unrelated read
- [x] `SLICE_TARGETS` encodes PLAN's seven-slice targets (single_silo 80, cross_silo 70, out_of_scope 60, temporal/exact_match/adversarial 25 each, multi_turn 15 — sums to 300) as the single source of truth `validate()` checks slice names against
- [x] `validate()` also enforces two structural rules from PLAN/decision 0002 that aren't in the literal T12 bullet list but are load-bearing: `out_of_scope` questions carry no gold refs (there is nothing to cite for an unanswerable question), and `conjunctive: true` requires ≥2 gold refs (a conjunctive claim needs something to conjoin)

**Verification:** `tests/test_gold.py` (12 tests) — re-running the splitter with
the same seed produces an identical split hash; a different seed can differ;
split proportions land exactly 4/2/4 on a 10-question slice; split-lock and
gold-question JSONL round-trip losslessly; the access counter only advances on
an explicit call.

**Dependencies:** T1 · **Scope:** M

## Task 13: Author the gold set (~300 questions)

**Description:** The largest manual effort in the project. Slice quotas
proportional to PLAN Phase 2, scaled to 300. Per decision 0004, this v1 set is
`provenance: "synthetic"` throughout — drafted from the corpus, not from real
student queries (none are available). A 28-question pilot batch (single_silo,
cross_silo, out_of_scope) was drafted first and human-approved on style/rigor
before the remaining 272 were authored to match it.

**Authoring method:** drafted by LLM subagents (one per slice or slice-group),
each required to (a) match the approved pilot's tone — natural student
phrasing, not textbook-stiff — and (b) ground every `gold` ref in a real
`chunk_id` from `corpus/chunks.jsonl`, quote-checked against the actual chunk
text, never asserted from memory. Schema-validated programmatically, at scale,
rather than by hand-reading all 300 (see Checkpoint C for what a human should
still spot-check).

**Acceptance criteria:**
- [x] ~300 questions across all **seven** slices at target proportions — exactly 300, matching `SLICE_TARGETS` per slice precisely (single_silo 80, cross_silo 70, out_of_scope 60, temporal 25, exact_match 25, adversarial 25, multi_turn 15)
- [x] Every answerable question has heading/chunk-level gold refs — every `gold` chunk_id verified to exist in `corpus/chunks.jsonl` (`tests/test_gold_v1.py`)
- [x] Cross-silo questions marked `conjunctive: true` and reference ≥2 silos — verified programmatically for all 70 (`tests/test_gold_v1.py`)
- [x] Out-of-scope slice has no gold refs and is explicitly unanswerable from the corpus — all 60 have `gold: []`; each was checked against the corpus by grep before being included (a candidate was dropped, not included, if it turned out answerable — several such rejections are on record from the drafting agents)
- [x] Authored against **train+dev only** — moot for authoring itself (no split existed yet to leak from); the split was assigned by `stratified_split` *after* every question was finalized, so authoring could not have been steered by which split a question landed in. The discipline that matters **going forward** is not reading `data/gold/gold_v1.jsonl`'s test-split rows while tuning anything — `TestAccessCounter` (Task 12) is how that gets enforced and logged
- [x] `multi_turn` questions carry ≥1 prior turn in `history` (schema gap found and fixed before authoring — see the `history` field commit) — a gap the original Task 12 schema didn't anticipate

**Verification:** Schema validation passes on all 300 (`tests/test_gold_v1.py`,
7 tests, run against the committed file itself, not just the tooling). Every
gold chunk_id exists in the corpus; single_silo/cross_silo silo-spanning
verified programmatically; every `expected_referral` is a real `offices.yaml`
email. **Not yet done: a human sampling ~20 questions and independently
confirming the gold refs actually contain the answer** — the drafting agents
self-verified this by quote-checking, but per Checkpoint C below this dataset
is the measuring instrument for everything after, and self-verification by
the same process that wrote the questions is not independent verification.

**Dependencies:** T12, T11 · **Scope:** L — drafted via 5 parallel subagent
batches instead of split across human sessions, but the a-few-slices-at-a-time
structure PLAN anticipated is exactly what happened

### ✅ Checkpoint C
- [x] 300 questions validated, split, locked — `data/gold/gold_v1.jsonl`, `data/gold/split.lock` (seed 42, stratified 40/20/40 within every slice)
- [x] Gold refs verified on a 20-question sample — human reviewed `data/gold/review_sample.md`, no corrections needed
- [x] **Human review — this dataset is the measuring instrument for everything after** — cleared

---

# Phase 3 — Baselines

## Task 14: Retrieval eval harness (zero quota)

**Acceptance criteria:**
- [x] Computes recall@k, MRR, nDCG against gold refs — `mcrag/eval/retrieval_metrics.py`, pure functions over `(gold, retrieved, k)`, no I/O
- [x] Computes **all-golds-retrieved@k** for `conjunctive` questions — partial recall scores zero — `all_golds_retrieved_at_k`; `summarize()` gives it its own `conjunctive_all_golds_retrieved@k` breakout rather than burying it in the overall average
- [x] Runs the full gold set in seconds, no LLM calls — `mcrag/eval/retrieval_harness.py`'s `run()`; a question with no gold (`out_of_scope`) is skipped, not scored as a failure — abstention is a generation-level question, not a retrieval-metric one
- [x] Writes a standard run dir (T1) — `RunDir.create`/`.append`/`.write_metrics`, resumable (re-running a complete run dir rescans `completed_ids()` and touches the retriever again for nothing)

**Verification:** `tests/test_retrieval_metrics.py` (13 tests) — every case hand-worked in a comment above it, including the 3-question end-to-end case T14 itself calls for. `tests/test_retrieval_harness.py` (5 tests) — a fake deterministic retriever, conjunctive breakout math verified by hand (2 conjunctive questions, one full match one partial -> mean 0.5), and a resume test that would silently corrupt if re-scoring happened (second retriever returns nothing for every query, would zero everything if it re-ran). Full suite: 307 passed.

**Dependencies:** T11, T12 · **Scope:** M

## Task 15: Phase 3a retrieval baseline

**What running this for real found.** The first run scored an exact 0.000 on
every metric — not a bad baseline, a bug. `FixedSizeChunker`'s 512-token
windows produce different `chunk_id`s than the production `ParagraphChunker`
chunks the 300 gold refs are ids into, so exact-id matching could never hit,
regardless of retrieval quality. This is a structural problem, not a one-off:
every future chunk-size ablation (§2c) would hit it too. Fixed by adding
content-overlap matching (`mcrag/eval/chunk_alignment.py`) — a retrieved chunk
is relabeled to the gold id it demonstrably covers (same `source_url`, and
either containment or ≥50% word-set overlap) before the existing exact-match
metric functions ever see it, so a retriever run against its *own* native
chunking is scored identically to before (pure extension, not a behavior
change) while a differently-chunked candidate is now scored on retrieval
quality instead of chunk-boundary luck.

**Acceptance criteria:**
- [x] Deliberately naive config: fixed 512-tok chunks, dense-only, k=5, no literal leg, no rerank, no rewriting — `mcrag/chunk/fixed_size_chunker.py` (`FixedSizeChunker`, no paragraph awareness, no overlap) + `scripts/build_baseline_index.py`
- [x] Scored on **dev**; run dir committed as the control condition — `runs/20260914T203423Z_318f7310fe60/` (36K, small enough to commit outright; `.gitignore` carries an explicit exception for this one control run, future Phase 4 ablation run dirs stay untracked)
- [x] `RESULTS.md` generated from `runs/` as a leaderboard — `mcrag/eval/results_table.py` (`scripts/generate_results.py`), extensible for Task 30's later cost column / Pareto plot rather than a throwaway

**Verification:** Ran twice; `metrics.json` byte-identical both times (no
randomness anywhere in a dense-only k=5 search plus a fixed-seed bootstrap).
Real numbers on 48 scored dev questions (12 out_of_scope skipped, no gold to
score): recall@5 0.667 [0.542, 0.781], MRR 0.614, nDCG@5 0.598,
all-golds-retrieved@5 0.562 — and the conjunctive breakout lands at **0.071**
(n=14): naive dense-only retrieval at k=5 almost never finds *both* chunks a
cross-silo question needs. That is the project's central thesis showing up in
the very first real number, not asserted — exactly what Phase 4's ablations
exist to move. `tests/test_fixed_size_chunker.py` (6), `tests/test_chunk_alignment.py` (7), `tests/test_results_table.py` (5) — full suite 327 passed.

**Dependencies:** T14 · **Scope:** S

## Task 16: Phase 3b end-to-end sanity check ⚠️ RISK GATE

**Description:** Validates that retrieval metrics predict answer quality
*before* twenty ablations are tuned against them.

**What running this for real found.** Two bugs, caught because this was a
real end-to-end run and not just a retrieval-only score. (1) The generator's
streaming reader let `requests` guess the response encoding, which defaults to
Latin-1 for `text/event-stream` with no charset header — every curly quote,
em-dash and non-breaking space in a real answer came out as mojibake. Fixed in
`mcrag/generate/ollama_cloud.py` (pin `response.encoding = "utf-8"`); the fix
is invisible to any test that JSON-escapes its fixture bytes, so the
regression test builds raw UTF-8 wire bytes directly. (2) One question
(`ss-39`) scored `ndcg@k = 1.13` — nDCG is normalized and cannot exceed 1.0.
Cause: `chunk_alignment.canonicalize_retrieved` (T15's content-overlap fix)
could relabel two *different* retrieved chunks to the *same* gold id when two
overlapping fixed-size windows both covered one gold paragraph, double-
counting that hit at two ranks. Fixed so a gold id is claimed only once, at
its best rank; corrected T15's committed run dir and `RESULTS.md`
(nDCG 0.598 → 0.587; recall/MRR/all-golds were unaffected).

Also found, orthogonal to both: the naive prompt never delimited retrieved
passages from the user's question, and the corpus is unreviewed scraped web
text — an instruction-shaped sentence on some future page is indistinguishable
from a real instruction in a flat concatenated prompt. Fixed in the new
`mcrag/generate/prompting.py` (shared by every script that builds a
generation prompt, so the fix can't silently apply to only one caller):
`<passages>`/`<question>` tags plus an explicit system-prompt clause. This
run predates the fix and was not rerun on it (would have invalidated the
hand-scores already recorded); the fix applies starting with Task 20.

**Acceptance criteria:**
- [x] 25 dev questions run end-to-end on the 3a config — stratified across all 6 answerable slices (`scripts/run_phase3b_sanity.py`), `runs/20260915T004143Z_2a62552d2271/`
- [x] Answers **hand-scored 0/1/2** — no LLM judge at this n — `docs/phase3b-sanity-review.md`, human-scored
- [x] Disagreement quadrants analysed per PLAN Phase 3b — see `decisions/0005-primary-retrieval-metric.md`: 76% diagonal agreement; the 2 high-retrieval/bad-answer cases are generation-stage (output-token exhaustion, inference confidence), not retrieval; the 6 low-retrieval/good-answer cases are grounded-but-mislabeled or defensible grounded refusals — never the dangerous parametric-knowledge case PLAN warns about
- [x] `num_ctx` truncation explicitly ruled out — zero `truncation_risk` flags across all 25 (guard raises rather than truncates); the one empty-answer case (`ss-39`) is `max_tokens`/reasoning exhaustion, a distinct failure mode, documented as such rather than conflated with the guard
- [x] **Primary retrieval metric chosen empirically** and recorded in `decisions/` — `all_golds_retrieved@k`, per `decisions/0005-primary-retrieval-metric.md`

**Verification:** Written finding stating which metric tracks hand-scored quality, with the quadrant table — `decisions/0005-primary-retrieval-metric.md`. Checkpoint D call: **GO**.

**Dependencies:** T15, T3 · **Scope:** M

## Task 16b: Pre-registered analysis plan + statistics tooling

**Description:** Implements PLAN §4f. Must be **complete and committed before the
first Phase 4 run**, because its entire purpose is to make Phase 4 confirmatory
rather than a search for a story. Written after seeing results, it is worthless.

**Acceptance criteria:**
- [x] `decisions/analysis-plan.md` names the primary retrieval, generation and abstention metrics — the retrieval one carried over from the T16 finding and **frozen here** — `decisions/0006-analysis-plan.md`: retrieval `all_golds_retrieved@k` (carried over), generation Tier-1 NLI faithfulness (primary) + Tier-0 binary checks (secondary), abstention coverage @ ≥95% precision floor
- [x] It lists the specific comparisons the test split will be spent on; anything else is labelled exploratory when reported — 10-arm table in `decisions/0006`, matching `docs/quota-calibration.md`'s own sizing
- [x] Paired comparison utilities: **exact McNemar** for binary outcomes, **seeded paired bootstrap** (10k) for graded ones and for median cost — `mcrag/eval/significance.py`
- [x] Every metric function returns `(point_estimate, ci_low, ci_high, n)` — **a bare float is not an acceptable return type anywhere in the harness** — every `significance.py` function returns `ComparisonResult` wrapping `stats.Interval`
- [x] `scripts/mde.py` reproduces the §4f detectable-effect table — hardened: no more undeclared `numpy`/`scipy` dependency, now calls `mcrag.eval.significance.mcnemar_p_value` directly so the power tool can't drift from the real test; added the previously-missing out-of-scope (n=24) split to its own table
- [x] Reporting layer refuses to emit a p-value for any dev-split comparison — `assert_reportable` raises `DevSplitSignificanceError`

**Verification:** Round-trip a known-effect synthetic pair through both tests and
confirm the CI covers the truth at the nominal rate. Assert the reporting layer
raises on a dev p-value request. — `tests/test_significance.py` (19 tests): a constant known effect is recovered exactly by the bootstrap; a coverage calibration test confirms the 95% CI covers a true 0.2 effect at ~85-100% over 100 replications; a companion test confirms the exact McNemar p-value rejects a true null at roughly the nominal alpha rate; `assert_reportable` is asserted to raise on dev and pass through on test.

**Dependencies:** T16 · **Scope:** M

### 🚨 Checkpoint D — GO / NO-GO
- [x] Retrieval proxy demonstrably tracks answer quality — `decisions/0005-primary-retrieval-metric.md`, 76% quadrant agreement, no dangerous disagreement cases
- [x] If it does not: ~~stop and fix the metric or the gold labels before Phase 4~~ — not triggered, GO
- [x] **Human review — this gate protects all downstream work** — signed off 2026-09-16

---

# Phase 4 — Ablations

## Task 17: Ablation runner (resumable, cached)

**Acceptance criteria:**
- [x] Takes a config matrix, runs one variable at a time, one run dir each
- [x] Generation cache keyed `(model, digest, prompt_hash)`; identical reruns cost zero quota
- [x] Resume from last completed `qid` after interruption
- [x] Quota wall → clean pause with resumable state, never a corrupt run

**Verification:** Kill mid-sweep, resume, confirm no duplicate generations and identical final metrics.

**Dependencies:** T1, T14 · **Scope:** M

**What building this found:** `mcrag/eval/ablation_runner.py` is deliberately
generic — it knows nothing about retrieval or generation, only how to turn a
`Config` into a resumable `RunDir` and drive a caller-supplied
`evaluate_fn`/`summarize_fn` over a gold-question list. That's the same
seam shape T14's `retrieval_harness.evaluate_question` already established;
T18 onward supply the pipeline-specific logic, T17 supplies only the
orchestration.

Two things needed building that weren't implied by T1/T14 alone:
- `find_or_create_run_dir(config, root)` — `RunDir.create` names directories
  `<timestamp>_<config_hash>`, so calling it twice for the same config (e.g.
  re-invoking a sweep after a kill) makes a *second*, empty directory next to
  the half-finished one instead of resuming it. Resume needed to look a run
  dir up by its config-hash suffix, not by timestamp.
- `GenerationCache`, keyed `(model, digest, prompt_hash)` and shared across
  every arm in a sweep (not scoped to one run dir) — two arms that send the
  identical prompt (same retrieved passages, same question, same decoding
  config) now pay for the generation once. Backed by an append-only JSONL
  file with the same fsync-per-record discipline as `RunDir.append`.

`SweepPaused` is the quota-wall contract: `run_arm`/`run_matrix` take a
`quota_errors` tuple of exception types that mean "the metered backend
stopped serving us" (as opposed to a bug in `evaluate_fn`, which propagates
immediately, uncaught) and turn one into a clean stop with the run dir intact
— every record that reached `evaluate_fn` was already appended and fsynced
before the exception could unwind. `run_matrix` stops at the first paused
arm; arms before it are complete, arms after it never started; a second call
with the same config list resumes exactly there. `tests/test_ablation_runner.py`
(13 tests) includes the literal verification step: two independent sweeps of
the same matrix, one clean and one deliberately paused-then-resumed, produce
identical final `metrics.json` — not merely "no crash," but no divergence.

## Task 18: Free retrieval ablations — **factorial, not OFAT** (#1–#5, #7)

**Description:** These runs cost nothing, so the only thing OFAT would buy is a
blind spot on interactions. Run the full crossing (PLAN §Phase 4).

**Acceptance criteria:**
- [x] **Index-time factors crossed:** boilerplate on/off × chunking scheme → 4 index builds
- [x] **Query-time factors crossed:** reranker × fusion mode × silo boost → 8 configs per index
- [x] All 32 cells evaluated; **`k` swept nested within a cell**, not as an orthogonal factor (the `(chunk_size, k)` coupling makes it non-orthogonal — §2c)
- [x] **Two-way interactions estimated and reported**, not just main effects
- [x] Every run logged with `corpus.lock` + `split.lock`, scored on dev
- [x] Zero generation calls across the entire set
- [x] Retrieval config frozen and recorded in `decisions/` at the end

**Verification:** `RESULTS.md` carries a main-effects table **and** an
interaction table; cell count is exactly 32; quota consumption is exactly zero.

**Dependencies:** T17, Checkpoint D · **Scope:** L

**What running this for real found:** the two index-time cells T9/T15 didn't
already build (boilerplate OFF × each chunker) came from
`scripts/extract_corpus.py --no-boilerplate-filter` (a flag that already
existed) + a new `scripts/build_ablation_corpora.py`. Three new retrieval
seams had to be built to have a query-time factorial at all —
`mcrag/retrieval/fusion.py` (`RRFFuser`), `mcrag/retrieval/reranker.py`
(`IdentityReranker` + a local `CrossEncoderReranker`, zero quota, zero
network once the model is cached — see the caught bug below), and
`mcrag/retrieval/silo_boost.py` (`SiloBoostReranker`, a soft, additive boost
toward the candidate list's own modal silo, since no query-side silo
classifier exists in the project) — plus `mcrag/eval/factorial.py`, the
standard 2-level coded-contrast main-effects/interaction analysis, and
`scripts/run_phase4_free_ablations.py`, the 32-cell driver built on T17's
`run_arm`. All new modules are unit-tested (fusion, reranker, silo_boost,
factorial: 31 tests) independent of the real sweep.

Two real bugs surfaced running this for real, both fixed: `extract_corpus.py
--no-boilerplate-filter` silently overwrites `corpus/manifest.jsonl` (the
*production* manifest) with the boilerplate-off run's per-page outcomes as a
side effect — reverted with `git checkout`, documented in the driver
script's docstring so it isn't repeated; and the first full sweep crashed on
a transient DNS hiccup because `CrossEncoderReranker` re-checked Hugging
Face Hub for a newer model version on every one of its 16 constructions even
though the weights were already cached — fixed by forcing
`HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`, which is also the more honest
posture for a task whose entire acceptance criterion is "zero quota": it
should mean zero network dependency too, not just zero LLM spend. T17's
resume-by-config-hash picked the sweep back up exactly where it crashed with
no duplicate work.

Real dev-split numbers, full 32-cell table, main effects, interactions, and
the frozen config with an explicit per-factor "why this lost" for every
rejected option: `decisions/0007-retrieval-config-freeze.md`. Headline:
reranker (+0.057) and fusion (+0.047) are the two real levers; the naive
`FixedSizeChunker(512)` edges out the production `ParagraphChunker`
(+0.010) and boilerplate-OFF edges out boilerplate-ON (net effect of
stripping is −0.016) — both flagged as possible `all_golds_retrieved@k`
chunk-size artifacts rather than settled claims, to be checked against
T20's real generation-quality numbers, not just asserted. Frozen config:
boilerplate OFF, `FixedSizeChunker(512)`, RRF fusion ON, reranker OFF, silo
boost OFF — the cheapest of four cells tied at the top score, chosen by an
explicit tie-break rule (dev is selection, not inference; no p-value
anywhere in this comparison, per `decisions/0006`).

## Task 19: Generation scoring ladder

**Acceptance criteria:**
- [x] Tier 0 deterministic metrics implemented (citation accuracy/validity, refusal correctness, exact-match regex)
- [x] Tier 1 NLI faithfulness via local DeBERTa-class entailment model — ⚠️ **correction, found in Task 20:** the version shipped here joined all retrieved chunks into one premise that the 512-token tokenizer silently truncated, and scored every validation answer exactly 0.000. Rewritten (windowed premises, normalized text, attribution stripping), but the rewrite **fails** its pre-set validation against the Task 16 hand scores. See `decisions/0008`.
- [x] If a Tier 3 judge is used: different model, **temperature 0**, calibrated against the Task 16 hand-scores, **κ reported**
- [x] Uncalibrated judge output is never reported as a metric

**Verification:** Tier 0 metrics hand-verified on 5 answers; judge κ recorded if used.

**Dependencies:** T16 · **Scope:** M

**What building this found:** `mcrag/eval/tier0_scoring.py` (citation
accuracy/validity, refusal correctness, exact-match presence) works against
Task 16's real answers *as they already are* — the naive prompt never forced
a citation syntax (that's ablation #8, Task 22), so citation extraction is a
bare-URL regex rather than a structured format, and it still discriminates:
hand-verified against 5 real T16 answers (`adversarial-10`, `-12`, `-01`,
`cs-14`, `cs-25` in `docs/phase3b-sanity-review.md`), all five score exactly
as a human reading them would expect. `mcrag/eval/nli_faithfulness.py`
(Tier 1) is the same tool class as T18's `CrossEncoderReranker` — a local
`sentence_transformers.CrossEncoder`, lazy-loaded, zero quota and offline
once cached — pointed at an NLI label space instead of relevance.

Tier 3 is built but **not run against real answers by this task**: PLAN's
own reservation (`decisions/0006`) is that Tier 2/3 scoring is spent at
Task 20's control run and the final test-split confirmation, not per
ablation, so the actual calibration against Task 16's 25 hand-scores is
T20's job. What's built now is the mechanism that makes an uncalibrated
judge impossible to accidentally report: `mcrag/eval/judge_calibration.py`
(`cohens_kappa`, `assert_calibrated` — the same enforcement pattern as
T16b's `assert_reportable` dev-split guard, checked at report time rather
than trusted at every call site) and `mcrag/eval/tier3_judge.py`
(`Tier3JudgeScorer`, which refuses to construct if the judge model equals
the judged model or temperature isn't exactly 0, and refuses to `judge()`
without a calibration clearing the κ≥0.6 floor). 49 new tests across the
four modules, all against fakes — no quota spent building this task.

## Task 20: Phase 3c generation baseline

**Acceptance criteria:**
- [x] Naive prompt (no forced citations, no abstention) on frozen retrieval, dev split
- [x] Scored with the Task 19 ladder — after fixing Task 19's Tier 1 scorer, which running this exposed as broken
- [x] Committed as the control for #6, #8, #9, #10 — `runs/20260917T044122Z_c1d4b7284f0f` (with its null-arm rerun)

**Verification (amended 2026-09-17, human decision, `decisions/0008`):** ~~Reproducible across two runs at
temperature 0.~~ Text-level reproducibility is not achievable on this endpoint (first attempt: 3/60 answers
identical, 5/60 refuse/answer decisions flipped). **Now:** two runs of the control agree at the metric level,
meaning every run2−run1 interval covers zero, and that null-arm interval is recorded as the noise floor T22
must report beside every effect. — ✅ **passes, at the boundary** on the re-run: refusal_correct
run2−run1 −0.067 [−0.150, 0.000], faithfulness +0.037 [−0.054, +0.127]. Refusal_correct's
upper end is exactly zero (6 flips, 5 against the rerun, 4 of them cross-silo).

**Dependencies:** T18, T19 · **Scope:** S

**What running this for real found** (full detail, every number, and what was
rejected: `decisions/0008-generation-baseline-and-tier1-validity.md`):

1. *Task 19's Tier 1 scorer carried zero information.* It joined all retrieved
   chunks into one premise (1,500–2,500 tokens) that the 512-token NLI tokenizer
   silently truncated; against Task 16's hand scores it gave every answer 0.000.
   The first baseline number, 0.013, measured the truncation. Rewritten in three
   steps, each re-scored offline from stored answers (zero quota, every prior
   value kept per record): windowed premises (0.243), refusals excluded from the
   average, since PLAN scores them separately (0.291), then Unicode normalization
   plus attribution-wrapper stripping (0.400). The wrapper fix wasn't cosmetic:
   ablation #8 (citation-forced) attributes by design, so it would have looked
   less grounded for doing so.
2. *The rewrite fails its own validation.* The criterion was fixed before the
   numbers were computed: monotone across hand scores 0→1→2, and Spearman CI
   excluding zero. Result: Spearman 0.166 [−0.158, 0.457], no scorable hand-0
   answers. The set (20 twos / 3 ones / 2 zeros) is underpowered, but a fail is
   reported as a fail. Absolute values are biased low (human-judged fully
   grounded answers average 0.390).
3. *Temperature 0 is not deterministic on this endpoint.* The second run is a
   free null arm, giving the project's first measured noise floor: a pure rerun
   moves faithfulness by up to ~±9 points and refusal-correctness by ~±7 on dev.
   Task 17's cache masks this, so reproducibility must never be checked through it.
4. *Multi-turn questions never got their history* — slice numbers invalid (n=3).
5. *`refusal_correct` is coarse on the adversarial slice* — reported per slice.

Real control-condition findings that do stand: retrieval reproduces T18's frozen
cell exactly (0.708); the no-abstention baseline answers 5 of 12 out-of-scope
questions it should refuse (refusal_correct 0.583 on that slice) — the gap #9
targets; citation accuracy 0.600 when the model cites at all.

6. *The prompt hid a third of what retrieval found.* `build_user_prompt` cut
   passages to 1,400 chars. At the frozen chunk size that hid 37% of retrieved
   text and 9% of retrieved gold passages from the model. The control now
   sends passages whole.

**Decisions, resolved 2026-09-17 by the human reviewer** (`decisions/0008`
Resolution; `decisions/0006` addendum): (1) verification amended to
metric-level reproducibility, with the noise floor mandatory in T22;
(2) Tier 1 faithfulness stays primary, reported only as paired arm
differences and labelled unvalidated (the extra hand-scoring round was
declined, so Tier 3 still has no κ calibration set); (3) multi-turn history
goes to the prompt, not retrieval. Decision 3 and finding 6 changed the
control's behavior, so it was re-run under a new config hash. The first pair
of runs is kept, marked superseded.

**The control of record** (dev, `runs/20260917T044122Z_c1d4b7284f0f`):
refusal_correct 0.850 (out_of_scope only: 0.500, answering 6/12 it should
refuse — the #9 gap), citation accuracy 0.729 when citing, faithfulness 0.435
(unvalidated, paired differences only), retrieval 0.708. The null arm
puts refusal_correct's rerun interval at 15 points wide and faithfulness's at
18. Most single-arm T22 effects on dev are expected to fall inside that,
recorded now, before any arm result exists.

## Task 21: τ calibration study

**Acceptance criteria:**
- [x] All three candidates tested: per-query normalisation, top1−top2 margin, percentile
- [x] Correct/false-refusal curve computed **offline from stored retrieval scores** (near-zero quota) — zero quota; scores were never stored before, so recomputed and now stored per question
- [x] Model-initiated refusals measured separately from threshold-gated ones
- [x] Chosen method and rationale recorded in `decisions/` — **post hoc** (`decisions/0009` Decision): raw cross-encoder, τ = 4.96, at a floor lowered from 95% to 80% by the human reviewer after the pre-registered analysis found no usable gate

**Verification:** Tradeoff curves plotted for all three; selection justified against the curve. — Curves plotted (`tau_curves.png` pre-registered, `tau_curves_floor80_raw_eligible.png` post hoc). The pre-registered selection (margin, τ 12.44) was **not** justified by the curve, since raw dominates the usable range. The post-hoc selection is raw, the curve's best, though it misses 80% out of fold (0.786 [0.655, 0.905]).

**Dependencies:** T20 · **Scope:** M

**What running this found** (pre-registered design and full results: `decisions/0009`):
three design facts first. PLAN gates on a rerank score, but `decisions/0007` froze the reranker
off. No retrieval score had ever been stored. The train split had never been used. With the
reviewer: label = in scope with all evidence retrieved; signal = cross-encoder logits (MaxP
windows, 0 truncated pairs), dense cosine as a non-selectable reference; fit on train + dev,
5-fold CV. Everything was written down before any score was computed.

- **No method meets 95% precision out of fold.** The rule's fallback picks margin (τ 12.44),
  which answers 2% of questions and refuses 97% of answerable ones. The percentile method
  saturated and never answered, as predicted in advance.
- **The calibration methods destroy out-of-scope detection** (exploratory): cross-encoder AUC
  in-scope vs out-of-scope falls from 0.717 raw to 0.467 normalized and 0.501 margin. For an
  out-of-scope question every candidate scores low, so the best one still stands out from its
  pool. Normalizing removes the absolute "nothing is relevant" level abstention needs. PLAN
  Sec 4e's premise is backwards for this use.
- **Triage doesn't rescue retrieval scores.** At a 95% floor on both sides, even the best
  signal leaves 95% of questions in the uncertain band (63% at 80%), so the judge would run
  on nearly every query.
- **The model's own refusals were precise:** 9 of 9 on dev were should-refuse, catching 9 of 26.
- Consequence: on this corpus a retrieval-score threshold cannot reach 95%; answer-level
  signals (self-refusal, NLI or LLM answerability) are the route to higher precision.

**Decision (human, post hoc, 2026-09-17):** lower the floor to 80%. Re-selected from the stored
scores (procedure written before it was computed; raw made eligible): **raw cross-encoder,
τ = 4.96.** Out of fold it answers 23.3% of questions at 0.786 precision, missing 80% by 1.4
points, and refuses 62% of answerable ones. It is not one of PLAN's three methods, which all
lost to it. `decisions/0006` has a second dated addendum: 80% operating point; test-split rows
3–4 kept, with this gate. Clean estimate only from test, since τ was fitted on train + dev.

## Task 22: Metered ablations (#6, #8, #9, #10) — **dev only, selection not inference**

**⚠️ Resolves a contradiction found scoping this task.** `docs/quota-calibration.md`
and `decisions/0006`'s original comparison table sized this task's ten arms
against the 120-question **test** split — directly contradicting this task's
own "dev, never test" criterion and Checkpoint E's "test evaluated exactly
once, after this checkpoint." Human decision (`decisions/0006` addendum 3):
**this task runs entirely on dev, for selection.** The one-time test-split
spend PLAN Sec 4a itself calls for ("reserve test for one final pass") moves
to a new task, **T22b**, after Checkpoint E. `docs/quota-calibration.md`'s
"10 arms on the 120-question test split" framing is superseded by that addendum.

**Acceptance criteria:**
- [x] Citation-forced vs free-form prompting, chosen-τ-gate vs always-answer, model comparison — **done, `decisions/0010`**. **Query reformulation ladder (#6) — done, `decisions/0011`**: rungs 1-2 (free) both fail to clear the pre-registered bar; rungs 3-7 (metered) not built, per the pre-registered stopping rule
- [x] All run on **dev**, never test (now unambiguous — see above)
- [x] **Runs interleaved by question, never by config** — `mcrag.eval.ablation_runner.run_interleaved`, confirmed live during the real sweep (record counts grew roughly together across all 6 arms)
- [x] `model.lock` digest re-checked mid-sweep; a change quarantines affected questions rather than the whole run — built as a per-arm `expected_model` dict (a single global value would have wrongly flagged every #10 arm, which deliberately mixes models); zero quarantines in the real run
- [x] OFAT here is a **quota decision, recorded as such** in `decisions/` — `decisions/0010`
- [x] Quality **and** cost logged per run (`wall_s`, `completion_tokens`, `reasoning_char_share` per question) — Pareto-frontier presentation still pending, now unblocked (#6 landed with no config change to plot against the control)
- [x] Quota consumption tracked against the Task 3 budget — 360 calls, 22.6 min, well under budget; #6 spent **zero** quota (rungs 1-2 are free, and the ladder stopped before reaching any metered rung)
- [x] **Every comparison reports the measured noise floor beside its effect** — a fresh, same-session null arm (`free_form_20b_b` vs `_a`), not Task 20's older one; #6's rungs 1-2 needed no separate noise floor (deterministic, no rerun variance — `decisions/0011`)
- [x] **Tier 1 faithfulness reported only as a paired arm difference, labelled unvalidated**, answered questions only
- [x] Noise and reproducibility checks **never go through Task 17's generation cache** — this driver never constructs one
- [x] Reformulation step 5 (de-contextualization) is compared against the Task 20 control — **moot**: the ladder never reaches step 5; rungs 1-2 already failed to clear the bar (`decisions/0011`)
- [x] #9 evaluates the gate Task 21 adopted against always-answer, in-sample — **found a real tension, not a simple verdict**: Tier 0's coarse `refusal_correct` drops sharply (−0.400) under the gate, while the gate's own stricter precision improves as designed (0.567→0.938); both are correct, they measure different things (`decisions/0010`)
- [x] Every comparison is selection, not inference (effect size + CI only) — the single-winning-config write-up for Checkpoint E: `decisions/0007`'s frozen retrieval config, unchanged, no reformulation kept (`decisions/0011`), generation model switched to **`gemma4:31b`** (human decision, `decisions/0010`'s "Adopted" section)

**Verification:** `RESULTS.md` shows quality/cost frontier; no test-split access
recorded; work-queue order test confirms no two consecutive items share a config.
— Work-queue ordering has a dedicated test (`test_build_work_queue_never_repeats_a_config_consecutively`) plus 24 more covering resumability and drift quarantine. `RESULTS.md`/Pareto frontier generation still pending — no longer blocked on #6 (which changed nothing to plot), just not yet run.

**Dependencies:** T20, T21 · **Scope:** L

**What running #8/#9/#10 found** (full numbers, every arm, what was rejected:
`decisions/0010`): 360 generation calls, 22.6 min, one real bug caught and
fixed along the way (a sign error in #9's own diff — `paired_bootstrap_comparison(a,b)`
returns `b-a`; the arguments were passed backwards, silently computing
`always_answer − gate` while labelled the opposite; caught because the
printed sign didn't match the two point estimates, fixed and recomputed at
zero quota from the already-stored records). Also fixed live: a `ReadTimeout`
on `gemma4:31b` (180s default, never calibrated against a model other than
`gpt-oss:20b`) crashed the first attempt instead of pausing cleanly — widened
`quota_errors` to catch `requests.exceptions.RequestException`, raised
`timeout_s` to 300s, resumed with zero duplicate calls.

- **#8:** citation-forcing only partially works — 52.7% [42.9%, 62.4%] of
  sentences carry a valid marker even under an explicit forced instruction,
  with zero invalid/fabricated markers. No faithfulness or refusal-correctness
  effect beyond noise; citation-forced answers are shorter and faster.
- **#9:** the gate's Tier-0 `refusal_correct` and its own T21-native precision
  move in opposite directions for the same reason — Tier 0's `expects_answer`
  (any gold ref) is coarser than T21's `should_answer` (all gold retrieved),
  and the gate is optimized for the latter. Not a contradiction; a measurement
  mismatch already flagged as a risk in `decisions/0009`.
- **#10, the headline finding: `gemma4:31b` matches `gpt-oss:20b`'s
  faithfulness (within noise) while its reasoning-channel share collapses
  73 points and it is both the fastest and cheapest arm.** Real, statistically
  supported, and directly relevant to Checkpoint E. `gpt-oss:120b` and
  `nemotron-3-nano:30b` both score measurably *lower* faithfulness than the
  20b baseline — reported as a real per-session difference on an unvalidated
  metric, not a verdict on model quality. By-slice breakdown (PLAN's own
  prediction that abstention/cross-silo slices would separate models) is
  **underpowered at n=3–16 per cell** and reported as exploratory only —
  neither confirms nor refutes the prediction.
- **#6, the reformulation ladder (`decisions/0011`):** rung 1 (acronym
  dictionary) does not clear its pre-registered bar — 0.708 → 0.688
  `all_golds_retrieved@5`, −0.021 [−0.063, +0.000], CI does not exclude zero
  and the point estimate is negative. Per the pre-registered stopping rule,
  the ladder stops there: rung 2 (dictionary + spelling) was never run, and
  rungs 3-7 (decomposition, multi-query, de-contextualization, step-back,
  HyDE — all metered) were never built. Zero quota spent. The finding itself
  is the answer this ablation was scoped to produce: reformulation does not
  help this corpus at the frozen retrieval config, so the config stays
  exactly as `decisions/0007` froze it.

### ✅ Checkpoint E — before touching test
- [x] Full config frozen — `decisions/0007`'s retrieval config, unchanged; `decisions/0011`'s no-reformulation; `decisions/0010`'s generation model switched to **`gemma4:31b`** (human decision, 2026-09-18: faithfulness tied within noise, ~301 fewer completion tokens and ~4.4s faster per question — driven by a 73pp-lower reasoning-channel share, not parameter count; by-slice behavior not validated, n=3–16/cell)
- [x] Every ablation logged and reproducible — spot-checked every decisions doc's cited numbers against the run dirs/summary JSONs they reference (`decisions/0007`'s tie-break cell, `decisions/0009`'s τ=4.96 row, `decisions/0010`'s #10 headline deltas, `decisions/0011`'s rung comparison): all match on disk. Found and fixed one real gap — `runs/phase4_free_factorial_summary.json`, the file `decisions/0007` cites as its "machine-readable source," was never committed when T18 landed; force-added now
- [x] **Test split evaluated exactly once, after this checkpoint** — that evaluation is Task 22b, immediately below (done 2026-09-22, `decisions/0013`)

## Task 22b: Test-split confirmatory pass

**Description:** The "one final pass" PLAN Sec 4a itself calls for, and the
task `tasks/todo.md` never scheduled until this contradiction was found
scoping T22. Spends the 120-question test split **exactly once**, on the
*single* frozen Checkpoint-E configuration — never on each of Task 22's
dev-side comparisons separately, which would spend test multiple times and
break the project's central invariant.

**Acceptance criteria:**
- [x] Runs the one frozen Checkpoint-E config (and only that config) against the Task 20 baseline's methodology, on test — `scripts/run_t22b_test_confirmatory.py`, 3 arms (baseline x2 + frozen), 120 test questions, 360 calls, 0 quarantined
- [x] This is the **first and only** point real paired significance tests apply (exact McNemar, paired bootstrap) — every dev-split number in Task 18/20/21/22 stays effect-size-and-CI only, permanently — `decisions/0013`'s "primary" comparison is the only `mcnemar_exact` call against test or dev anywhere in the project; `assert_reportable` guards it
- [x] Test-split access logged in `notes.md`, per the standing rule ("log every access") — `notes.md` (new, repo root), one dated entry
- [x] Reports the measured noise floor beside the result, same as Task 22 (temperature 0 isn't deterministic, `decisions/0008`) — `decisions/0013` Results, noise floor table (`exact_text_match` 0.158, confirming non-determinism persists)
- [x] Tier 2 (human) or Tier 3 (calibrated judge, κ reported) scoring may be spent here — PLAN Sec 4d reserves both for exactly this pass — but only if a Tier 3 judge has since been calibrated (`decisions/0008` addendum: declined for Task 20; still unbuilt) — Tier 3 calibration attempted and failed (`decisions/0012`, κ=0.146); full Tier 2 explicitly declined by human decision (`decisions/0013` Resolution) — neither spent, by design, not oversight

**Verification:** `notes.md` shows a single test-split access, dated, naming the frozen config. `decisions/0013` carries the confirmatory result with the project's one real p-value (McNemar, `refusal_correct`, p=0.81; `citation_accuracy`/`citation_validity`, p=1.00 — no accuracy difference distinguishable from chance) alongside a large, noise-floor-exceeding cost/latency win for `gemma4:31b` (−5.5s, −298 completion tokens, −0.755 reasoning-channel share).

**Dependencies:** Checkpoint E · **Scope:** S

---

## Task 22c: Answer-level out-of-scope signal

**Description:** T22b (`decisions/0013`) found 100% of false-answer errors
on test are `out_of_scope`. `decisions/0009` already tested and rejected a
retrieval-score gate for this; its own conclusion named answer-level
signals (self-refusal, NLI, LLM answerability) as the unexplored route.
This task builds that, dev only, same ladder discipline as `0011`.

**Acceptance criteria:**
- [x] Zero-quota check: does an answer-level signal already on disk
  (Tier 1 faithfulness) separate false-answer `out_of_scope` cases from
  everything else, using every dev generation run already stored —
  `decisions/0014` rung 0: 68% (34/50) of false-answer `out_of_scope`
  cases score exactly 0.0 faithfulness vs 26.1% (94/360) of legitimate
  in-scope answers. Real signal, not clean, diagnostic only.
- [x] Rung 1: a strengthened refusal instruction (prompt-only, no new
  component), 3 dev arms interleaved incl. this-session noise floor —
  `decisions/0014` rung 1: **kept**. `out_of_scope` false-answer rate
  0.417→0.250 (n=12, +0.167 [+0.000,+0.417]), zero collateral drop on
  pooled dev. Does not close the gap alone (25% still false-answered).
- [x] Rung 2 (conditional): calibrated post-hoc faithfulness override,
  fit train/dev like `0009`'s τ — `decisions/0014` rung 2: **not kept**.
  5-fold CV finds no middle ground between a no-op (80% floor) and fully
  closing the gap at an unacceptable −0.167 [−0.283,−0.050] pooled
  refusal_correct collateral cost (95% floor) — same failure shape as the
  rejected CE gate, smaller scale. `scope_strict_gemma4_31b` (rung 1)
  alone remains best-so-far.
- [x] Rung 3: dedicated LLM answerability self-check (two-step pipeline,
  self-check call before generation, fails closed on an unparseable
  response) — `decisions/0014` rung 3: **not kept**. Fully closes the
  `out_of_scope` gap (12/12 refused, false-answer rate 0.000, refusal_correct
  +0.250 [+0.000,+0.500] n=12) but at the worst pooled collateral cost of
  any rung tried: refusal_correct −0.217 [−0.350,−0.083] (n=60), well
  outside the −0.017 noise floor and larger than rung 2's own rejected
  −0.167. `scope_strict_gemma4_31b` (rung 1) alone remains adopted.
- [x] Every rung's result — kept or not — recorded in `decisions/0014`
  before the next rung runs, same "log every arm, not just the winner"
  rule as `0007`/`0011`. **Ladder closed** — no rung 4 planned.

**Verification:** `decisions/0014` carries the pre-registered design for
every rung before it runs, and the result immediately after, with the
noise floor reported beside each effect. Target metric is `out_of_scope`
false-answer rate; a rung that "fixes" it by refusing everything is not a
win (`refusal_correct`/faithfulness/citation metrics checked for
collateral damage every time).

**Dependencies:** Checkpoint E, T22b · **Scope:** M · **Resolution:**
adopted config for production is `scope_strict_gemma4_31b` (rung 1's
prompt), un-stacked. The residual `out_of_scope` false-answer rate (25%,
3/12 dev) is an accepted, documented limitation — every stacked
answer-level mechanism tried (rungs 2 and 3) traded it for unacceptable
in-scope false-refusal collateral instead.

---

---

# Phase 5 — Product backend (UI deliberately deferred)

**Governing constraint: no client is privileged.** The front end is undecided —
embeddable widget on another site, standalone site, or something else. That stays
deferrable only if nothing in the service knows what renders it. Cheap to honor
now, expensive to retrofit. See PLAN.md §Phase 5 for the contract.

## Task 23: Event schema + stream contract

**Description:** Define the contract *before* the code, because a second client
turns it into a public interface the moment it exists.

**Acceptance criteria:**
- [x] `docs/stream_contract.md` defines events `sources` · `token` · `citation` · `refusal` · `done` with full field lists
- [x] Schema is versioned (`v1`) and the version travels in the `done` event (`DoneEvent.schema_version`)
- [x] `citation` carries character spans into the answer text, so clients never re-parse prose (`CitationEvent.claim_span`)
- [x] `refusal` carries office, contact URL and email as **structured fields** — no client parses an apology to find an email (`RefusalEvent`; `reason` reuses `per_query.jsonl`'s existing `threshold`/`gate`/`model` vocabulary rather than inventing a new one)
- [x] Pydantic models generated from / matching the doc, one source of truth — `mcrag/service/events.py`, `extra="forbid"` on every model

**Verification:** `tests/test_stream_contract.py` (12 tests: 5 parametrized round-trips + 7 others) parses every
`docs/stream_contract.md` JSON example and round-trips it through the
matching model; `extra="forbid"` means a field added to one side and not
documented on the other fails validation immediately rather than
drifting apart silently — the practical form "doc and models diff clean
in CI" takes without a codegen step (scope S). Full suite: 557 passed.

**Dependencies:** T22 (config frozen) · **Scope:** S · **Resolution:**
done 2026-09-24. `mcrag/service/` created (Task 24's future home). `pydantic>=2.0`
added to `pyproject.toml` core dependencies (also needed by Task 25's
FastAPI shell). The pre-existing `mcrag.types.Event` dataclass is a
different, lower-level concept — one generation call's own private
streaming primitive — noted explicitly in the doc so Task 24 doesn't
conflate the two.

## Task 24: Answer service callable

**Description:** `answer(question, history) -> Iterator[Event]`. **No web
framework imported anywhere in this module.** This is what makes the API a thin
shell and the UI genuinely optional — it is importable from a script, a test, or
a notebook.

This is also where the project's persona is decided, and persona and
prompt-safety are not separable: T16 (`decisions/0005`) hardened
`mcrag/generate/prompting.py` against *passage*-borne injection (scraped page
text shaped like an instruction). This task is the first place a live,
adversarial *user* turn exists in the pipeline — everything before it only
ever ran pre-authored gold questions — so it is also the first place
*user*-borne injection ("ignore your instructions and...", "reveal your
system prompt", role-play jailbreaks) needs a defense. It has never been
named as a requirement anywhere before now: PLAN's adversarial gold slice
tests false-premise resistance, not injection resistance, and the risk table
had no row for it (added, §6). Recorded here rather than at T25/T27 because
persona and system-prompt content are decided in *this* module and the
service layer must not need to change to add the defense later.

**Acceptance criteria:**
- [x] Runs the frozen Checkpoint-E config end to end — `mcrag/service/answer.py`, model `gemma4:31b`, retrieval built from the new shared `mcrag/retrieval/frozen_pipeline.py` (extracted from `scripts/run_phase3c_baseline.py` so both use the identical build, not a hand-synced copy)
- [x] Retrieved passages reach the prompt whole: `build_user_prompt`'s 1,400-char default cut hid 37% of retrieved text and 9% of retrieved gold passages at the frozen chunk size (`decisions/0008`). Pass `passage_chars=None` and let the context guard refuse real overflow — `answer()` calls `build_user_prompt(question, chunks, passage_chars=None)`
- [x] Yields typed events per T23, in contract order — `sources → refusal → done` or `sources → token*/citation* → done`, verified in `tests/test_service.py`
- [x] `import fastapi` does not appear in the module or its imports (asserted by test) — `test_no_fastapi_import_in_answer_module_or_its_direct_imports` (AST-based, not a string grep)
- [x] Same code path used by the eval harness, so product and experiment cannot drift — shared `mcrag.retrieval.frozen_pipeline` module, `scripts/run_phase3c_baseline.py` refactored to import from it too rather than kept as a separate copy
- [x] Per-stage latency captured and attached to `done` — `embed`/`dense`/`bm25`/`literal`/`fuse` timed individually (embed timed via a documented, deliberately redundant local call: `DenseIndex.search` embeds internally with no seam to inject a precomputed vector), `rerank=None` (off, decisions/0007), `generate_ttft`/`generate_total` from the token stream, `server_ns` from the provider's own `eval_duration`/`prompt_eval_duration` (added as an additive field to `mcrag.generate.ollama_cloud`'s `done` event data)
- [x] System prompt/persona explicitly instructs the model to ignore any
      user-turn attempt to override its instructions, disclose the system
      prompt, or act outside the RAG/citation contract, and this is covered
      by dedicated test cases (not folded into the false-premise adversarial
      gold slice, which tests a different failure mode) — `SERVICE_SYSTEM_PROMPT` (`mcrag/generate/prompting.py`, built on the adopted rung 1 `SCOPE_STRICT_SYSTEM_PROMPT`, decisions/0014)

**Verification:** `pytest tests/test_service.py` drives it with no server running (15 tests; every double is a plain Python object duck-typing the real `Generator`/retrieval-leg interfaces, no socket opened, no index read off disk, no quota spent). Grep-equivalent (AST) asserts no framework import. Three fixed user-turn injection attempts (system-prompt disclosure request, instruction override, role-play jailbreak) are run through the service; asserted: the same fixed `SERVICE_SYSTEM_PROMPT` reaches every generation call regardless of the attempt, the user turn always lands inside `<question>` tags, and a refusal-shaped reply is routed as a structured `refusal` event rather than streamed as an answer. Full suite: 572 passed. **What this does not claim:** whether the real `gemma4:31b` model actually refuses these three attempts live is a fact about that model on that text, not this module's code, and isn't something a test double can pin — that is a separate, real-quota report, same convention as every other LLM-behavior claim in this project (e.g. `decisions/0014`), not yet run.

**Dependencies:** T23 · **Scope:** M

**Resolution:** done 2026-09-24. `mcrag/service/answer.py` (`answer()`), `mcrag/retrieval/frozen_pipeline.py` (new, shared retrieval build), `mcrag/generate/prompting.py` (`SERVICE_SYSTEM_PROMPT`), `tests/test_service.py` (new, 15 tests). Refusal routing is deliberately partial: only the `model` pathway is wired (routes to Admissions, `data/offices.yaml`'s generic front door, as an explicit placeholder); the threshold gate (τ = 4.96, decisions/0009), the answerability gate, real per-silo office resolution, and any-signal-wins precedence are T27's job, which this task does not depend on and does not attempt.

## Task 25: FastAPI + SSE shell

**Acceptance criteria:**
- [x] `POST /ask` streams the T24 events as SSE, thin by construction — no logic beyond transport — `mcrag/service/api.py`; `_stream` only pulls from `answer()` and reformats each event via `mcrag.service.events.to_sse`, nothing else
- [x] CORS configurable by origin allowlist — `Settings.cors_origins` (`mcrag/service/config.py`, `MCRAG_CORS_ORIGINS` env, comma-separated) wired to `CORSMiddleware`
- [x] Simple API token check, config-driven — `Settings.api_token` (`MCRAG_API_TOKEN` env), `X-API-Key` header, `secrets.compare_digest`; unconfigured fails closed (every request rejected), not open
- [x] Client disconnect cancels the upstream generation call rather than burning quota to nobody — `_stream` checks `request.is_disconnected()` before every pull; see the granularity caveat below
- [x] `GET /health` reports index build id and corpus hash — `mcrag/service/health.py`: `index_build_id` hashes the frozen chunk file every retrieval leg is built from, `corpus_hash` reuses T10's `indexes/corpus.lock` `snapshot_hash`

**Verification:** `tests/test_api.py` (11 tests, `fastapi.testclient.TestClient` against `create_app(settings=..., pipeline=...)` — no real server process, fakes reused from `tests/test_service.py`): auth (missing/wrong/unconfigured token all 401, correct token streams), CORS preflight (allowed origin echoed, unlisted origin gets no CORS header), `/health` reports real fields (also unit-tested against tmp files), a `model` refusal streams `refusal` not `token`, and two tests drive `_stream` directly against a fake `Request.is_disconnected()` (`TestClient`'s in-memory ASGI transport does not reproduce real disconnect timing deterministically) confirming the generator is fully drained to `done` when nothing disconnects and that disconnecting between the `sources` pull and the next pull means `FakeGenerator.generate` is never called at all. Full suite: 583 passed. Live-server smoke test (`uvicorn`, real `/health` against the real frozen chunk file and `indexes/corpus.lock`, real 401s) run manually, zero generation quota spent — confirmed `index_build_id`/`corpus_hash` are real, non-placeholder values and auth rejects over the wire, not just in-process. **What this does not claim:** a live `curl -N POST /ask` against `gemma4:31b` — that would spend real generation quota and has not been run; SSE framing over a real network socket for a real generation call is asserted only via `TestClient`, not via a live process, same convention as every other not-yet-spent real-quota check in this project (e.g. `decisions/0014`, T24). **Cancellation granularity is real but bounded, documented in `mcrag/service/api.py`'s module docstring:** `answer()` buffers the full model reply before yielding any `token`/`citation` (refusal must replace them entirely, not retract after the fact), so the generator is only suspended at a `yield` before retrieval starts (moot) and right after `sources`/before the model call begins (the one place that matters, and the one this task's disconnect test exercises) — a disconnect noticed mid-generation-call cannot interrupt that call early with this generator shape.

**Dependencies:** T24 · **Scope:** M

**Resolution:** done 2026-09-23. New: `mcrag/service/api.py` (`create_app`, `_stream`, `AskRequest`), `mcrag/service/config.py` (`Settings`), `mcrag/service/health.py` (`get_health_info`), `tests/test_api.py` (11 tests). `pyproject.toml`: new `service` extra (`fastapi`, `uvicorn[standard]`) — optional, `mcrag.service.answer` stays importable with nothing here installed; `httpx` added to `dev` (`TestClient`'s transport).

## Task 26: Early `sources` emission + freshness

**Description:** The single most important behavior in the contract. Generation
TTFT is the entire reasoning phase, potentially 10s+ of blank screen (§4b).
Emitting sources at rerank time lets *any* client fill that gap with the trust
surface instead of a spinner — widget, site and terminal all get it free.

**Acceptance criteria:**
- [x] `sources` is emitted **before the first generation token is requested**, not merely before the first token is yielded — already true of T24's `answer()` by construction (the `yield SourcesEvent(...)` happens before `pipeline.generator.generate(...)` is ever called); now proved rather than merely ordered, by `test_no_generation_call_happens_before_sources_is_consumed` (pulls exactly one event, asserts the fake generator's call list is still empty)
- [x] Each source carries `title`, `url`, `silo`, `heading_path`, `rerank_score`, `last_verified` — done in T24; unchanged here
- [x] Staleness flag computed from `crawled_at` against a configurable threshold — new `SourceChunk.stale` field (`mcrag/service/events.py`), computed in `mcrag/service/answer.py`'s `_source_events` against `DEFAULT_STALENESS_DAYS = 180` (a starting default, not a measured/decided value — no staleness/trust study backs it), overridable per call via `answer(..., staleness_days=..., now=...)`
- [x] Measured gap between `sources` and first `token` is logged — `mcrag.service.answer`'s stdlib `logging.getLogger(__name__)` logs `sources_to_first_token_ms` once TTFT is known, timed from the instant `SourcesEvent` is yielded (not from when the prompt happens to finish building), regardless of whether the request is later refused

**Verification:** `tests/test_service.py` (+4 tests): the suspension-point proof above; `stale` true/false against a fixed `now` and threshold on either side; the log line asserted via `caplog`. `docs/stream_contract.md` updated (`stale` field + JSON example) and `tests/test_stream_contract.py`'s doc/model round-trip catches any future drift (`extra="forbid"` — a `stale`-less doc example now fails loudly, same mechanism T23 built). Full suite: 587 passed. **What this does not claim:** the plan's own "sources arrives at least 1s before first token on a reasoning-heavy question" needs a real `gemma4:31b` reasoning delay to observe — a fake generator responds instantly, so that number isn't something a test double can produce honestly; not yet run, same real-quota-report convention as T24's injection check and T25's live `/ask`.

**Dependencies:** T25 · **Scope:** S

**Resolution:** done 2026-09-23. Changed: `mcrag/service/events.py` (`SourceChunk.stale`), `mcrag/service/answer.py` (`DEFAULT_STALENESS_DAYS`, `_source_events` threshold logic, `logger`/`sources_to_first_token_ms`, `answer(staleness_days=, now=)`), `docs/stream_contract.md`, `tests/test_service.py` (+4 tests). No new files, no dependency changes — this task extended T24's module rather than adding a new one.

## Task 27: Refusal path + office routing

**Acceptance criteria:**
- [x] Threshold and model-initiated refusal wired, with **any-signal-wins** precedence (§4e), realized as short-circuit order: the threshold (Task 21's raw cross-encoder MaxP score over the frozen top 5, refuse below τ = 4.96, `decisions/0009`) runs first, on retrieval output alone, so a threshold refusal spends no generation quota; `model` (the model declining in its own text, T24) is only reached when `threshold` passed. It adds a local cross-encoder pass per answer, and that latency is now reported in `LatencyMs.rerank` (previously always `null`, since `decisions/0007` only froze the *retrieval* reranker stage off — this is a different use of the same model). **The third named signal, `gate` (an answerability gate ahead of generation), is deliberately not wired** — see Resolution below
- [x] Both wired signals plus the resolved winner logged per request (`mcrag.service.answer`'s `logger`, `refusal_signals ...` line); `gate` is logged as a fixed `False`/`None` rather than omitted
- [x] Refusal resolves the owning office via `data/offices.yaml` (T8, new `mcrag/offices.py`) and emits contact fields, keyed on the top-ranked retrieved chunk's silo
- [x] Unroutable refusal (no chunk retrieved, or its silo has no row) falls back to a general contact (`mcrag.offices.GENERAL_SILO = "admissions"`, a Task 27 policy decision) rather than emitting an empty office

**Verification:** `tests/test_offices_module.py` (4 tests, `mcrag.offices.resolve` against a fake table and the real one). `tests/test_service.py` (+7 tests): threshold-fires-and-skips-generation, threshold-passes-and-generation-proceeds, zero-retrieved-chunks refuses via `threshold` with no score, silo-routed office on a threshold refusal, general-fallback office when nothing was retrieved, `gate` is never emitted across three forced scenarios (threshold fires / model fires / neither fires), all-signals-plus-winner logged. `docs/stream_contract.md` updated (`reason`/`rerank` field descriptions, JSON examples) and `tests/test_stream_contract.py`'s doc/model round-trip still passes unchanged (no new fields, `extra="forbid"` still holds). Full suite: 598 passed.

**Dependencies:** T26, T8, T21 · **Scope:** M

**Resolution:** done 2026-09-23. **The `gate` pathway is explicitly out of scope for this task**, by human decision (`AskUserQuestion`, this session): `decisions/0014` already built and rejected a dedicated two-step LLM answerability gate (rung 3) — it fully closed the out-of-scope gap but cost `-0.217 [-0.350, -0.083]` refusal_correct, outside every noise floor measured in this project and worse than rung 2's own rejected cost. Re-wiring a gate here without new evidence would re-litigate a settled, evidence-backed decision, which this project's ablation-logging convention (log every arm tried and why losers lost) exists to prevent. `RefusalEvent.reason`'s `"gate"` literal stays schema-valid for forward compatibility; no code path in `mcrag/service/answer.py` ever constructs one (asserted by test). Changed: `mcrag/offices.py` (new — silo → contact lookup, `OfficeContact`, `resolve`, `GENERAL_SILO`), `tests/test_offices_module.py` (new, 4 tests), `mcrag/service/answer.py` (`TAU`, threshold-gate wiring ahead of generation, `_office_fields`, any-signal-wins short-circuit, `refusal_signals` logging, `LatencyMs.rerank` now populated, `AnswerPipeline.score_pairs`), `tests/test_service.py` (+7 tests, `FakeScorer`, `_pipeline(score_pairs=...)`), `docs/stream_contract.md`.

## Task 28: Conversation memory + follow-up rewriting

**Description:** The mechanism the ~15-question multi-turn gold slice measures.

**Acceptance criteria:**
- [x] History accepted per-request; server holds no session state it cannot rebuild — `AskRequest.history` (prior user turns only, no session id, no server-side store); prior turns are re-answered live each request rather than cached, so a restart loses nothing and two processes need no session affinity
- [x] De-contextualization rewrites a follow-up into a standalone query before retrieval (§4c step 5) — `LlmDecontextualizer` (`mcrag/retrieval/reformulation.py`), wired as `AnswerPipeline.reformulator`, called before any retrieval leg runs
- [x] `rewritten_query` is visible in the response payload and in logs — `SourcesEvent.rewritten_query` (documented in `docs/stream_contract.md`) plus a `rewritten_query=...` log line; `null`/absent when no rewrite happened, so the field never falsely claims one
- [x] Evaluated against the multi-turn slice; **result reported even if it is bad** — `decisions/0015`, pre-registered before running, all three arms logged with why the loser lost

**Verification:** `scripts/run_t28_decontextualization.py`, pre-registered in `decisions/0015-decontextualization.md` before any arm ran. Pool: the 9 dev+train `multi_turn` questions (test's 6 excluded — spent once at T22b and not read here); dev-only n=3 reported as a pre-registered secondary. `all_golds_retrieved@5` (≡ `recall@5` on this slice: every multi-turn question has exactly 1 gold ref): arm 0 raw follow-up **0.222** → arm 1 free history-concatenation **0.556** (+0.333 [−0.111, +0.778], 4 improved / **1 regressed** → fails the pre-registered zero-regression clause) → arm 2 `LlmDecontextualizer` **0.667** (+0.444 [+0.111, +0.778], 4 improved / 0 regressed → clears). Noise floor for arm 2: **+0.0000 [+0.0000, +0.0000]**, the rerun reproducing all 9 rewrites byte-identically at `temperature=0`; 0 fallbacks. Arm 2 beats arm 1 by exactly one question (mt-03, +0.111 [+0.000, +0.333]). Tests: `tests/test_reformulation.py` (+14, 29 total: both step-5 arms, no-call-without-history, quote/label stripping, all four fallback paths, usage accounting), `tests/test_service.py` (+11, 38 total: retrieval-on-rewrite, generation-on-original, `rewritten_query` published and logged, fan-out takes the first query only, `latency_ms.reform`, threshold gate scores the rewrite, no state between requests, shipped-default guard), `docs/stream_contract.md` + `tests/test_stream_contract.py` round-trip. Full suite: **624 passed**.

**Dependencies:** T27 · **Scope:** M

**Resolution:** done 2026-09-23. **Arm 2 adopted as the service default** (`get_default_pipeline` configures `LlmDecontextualizer` at `gemma4:31b`, `temperature=0`, `max_tokens=128` — the configuration measured, not a re-tuned one). Two decisions were escalated before running, because both would have been post-hoc selection if made after seeing results: (a) **the eval pool** — T28's stated verification names the dev multi-turn slice, which is only n=3; the human decision was the 9 dev+train questions as primary with dev-only as a pre-registered secondary, on the grounds that no model is trained anywhere in this project so `train` had never been read by any script (now spent, recorded in `decisions/0015` so no later task treats it as unused); test stays excluded. (b) **metered authorization** for arm 2 (~18 short completions including the noise-floor rerun). Two things are deliberately *not* claimed: mt-02/mt-07/mt-11 miss at k=5 under all three arms despite good rewrites — a retrieval/coverage ceiling step 5 cannot fix, so the slice goes 2/9 → 6/9, not 9/9 — and `mrr` slightly favors arm 1 (0.481 vs 0.454) purely because arm 1 *drops* mt-03 instead of carrying it at rank 4, which is why the primary metric was fixed in advance. Also flagged, not fixed: τ (4.96, `decisions/0009`) now scores against the rewritten query, but was calibrated on standalone questions containing no under-specified follow-ups, so that choice is reasoned rather than validated; re-calibrating τ for multi-turn traffic is out of scope. Changed: `mcrag/retrieval/reformulation.py` (`HistoryConcatenationReformulator`, `LlmDecontextualizer`, `DECONTEXTUALIZE_SYSTEM_PROMPT`, `Sequence` history on all rungs), `mcrag/interfaces.py` (`Reformulator.reform`'s `history` annotation corrected from the never-read `list[tuple[str, str]]` to `Sequence[str]`), `mcrag/service/events.py` (`SourcesEvent.rewritten_query`, `LatencyMs.reform`, `RefusalEvent` docstring's stale `gate` description), `mcrag/service/answer.py` (`reformulator` field, rewrite-before-retrieval, retrieve-on-rewrite/generate-on-original, `REWRITE_MAX_TOKENS`, adopted default), `mcrag/service/api.py` (`AskRequest` statelessness docstring), `decisions/0015-decontextualization.md` (new), `scripts/run_t28_decontextualization.py` (new), `docs/stream_contract.md`, `tests/test_reformulation.py`, `tests/test_service.py`.

## Task 29: Reference client (disposable)

**Description:** ~40 lines of HTML/JS whose only jobs are proving the stream
works and demoing. **A test fixture, not a product.** When the real front end is
decided it is a new client against a frozen contract.

**Acceptance criteria:**
- [x] Renders every event type, sources first — `clients/reference_client.html`: `sources` (title link, heading trail, silo, `last_verified`, a `stale` badge, `rewritten_query` when non-null), `token` (appended, re-rendered), `citation`, `refusal`, `done` (per-stage `latency_ms`, `refused`, `schema_version`); a `null` stage prints `—`, never `0`
- [x] Inline citation links to live source URLs — the client splices an `<a href>` at the `claim_span` offsets the server sent, so it never re-parses prose to find what a citation covers; overlapping spans resolve first-wins rather than nesting
- [x] Refusal renders the office contact — `office` as a link to `contact_url` plus a `mailto:` for `email`, and the `reason` verbatim; no prose is parsed to find any of it
- [x] File header states plainly that it is disposable, so nobody grows a product on it — the file opens with `DISPOSABLE REFERENCE CLIENT. NOT A PRODUCT. DO NOT BUILD ON THIS.` and says outright that the real front end is a *new* client against `docs/stream_contract.md`, and that this file should be deleted then

**Verification:** Manual, at zero generation quota. `scripts/serve_reference_client_demo.py` stands up the real `create_app` + real `answer()` + real event models + real SSE framing with only the paid/on-disk leaves faked (the doubles `tests/test_service.py` already defines, imported rather than re-invented, as `tests/test_api.py` does), and the *real* free `HistoryConcatenationReformulator` so `rewritten_query` is genuinely non-null on a follow-up. Three questions over that server: "What is the deposit?" → `sources`(2 chunks, one deliberately 2024-crawled so `stale: true` renders) · `token` · `citation` · `done`; a follow-up with `history` → `rewritten_query: "What is the deposit? When is it due?"`; anything mentioning parking → `sources` · `refusal`(`reason: model`, routed to Admissions) · `done` with no `token` at all. Frame-by-frame SSE output captured for all three. Rendering itself was then checked by extracting the client's `handle()` and driving it with those exact captured payloads under a stubbed DOM (`node`) — citation spliced at the server's offsets, `stale` badge, `rewritten_query`, office `mailto:`, `reform=—` for a null stage, and server-supplied HTML escaped rather than injected. **Not done:** opening it in a real browser (the Chrome extension is not connected in this session) and any live `gemma4:31b` answer — flagged open, same convention as T24/T25/T26's deferred real-quota checks.

**Dependencies:** T26 · **Scope:** S

**Resolution:** done 2026-09-23. **No product code changed for this task** — `clients/reference_client.html` and `scripts/serve_reference_client_demo.py` are both new files, and nothing under `mcrag/` was touched, which is the strongest available evidence that the contract really is the whole client surface. Two deliberate choices: the client hand-rolls SSE parsing over `fetch` rather than using `EventSource`, because `EventSource` is GET-only and cannot set the `X-API-Key` header T25 requires (worth knowing before a real front end is designed); and the render harness used to verify it was left in the scratchpad rather than committed as a test, because a permanent test suite around a file whose header says *delete me* is exactly the kind of growth the disposability warning exists to prevent. The client holds the conversation itself — prior user turns only, oldest first — matching T28's statelessness rather than inventing a session id the server would ignore.

### ✅ Checkpoint F — backend complete
- [x] Contract frozen and documented; a second client could be written from the doc alone (T29 client built against the doc; found the `EventSource`/`X-API-Key` gap)
- [x] Service callable runs with no server (`tests/test_service.py`)
- [ ] Sources-before-tokens verified by timing test — **RUN LIVE 2026-09-24, CLAIM NOT MET; box stays open.** Real `gemma4:31b`, three warm answered calls: sources->first token 0.65s, 1.07s, 0.63s against the >=1s claim (held for 1 of 3). Tokens, citation and `done` arrive within ~0.05s of each other, so answers arrive in one piece rather than streaming. Also run live (n=1 per case; `docs/LIMITATIONS.md` section 7): `curl -N POST /ask` works over real SSE (T25); the three fixed injection attempts (T24) were refused by the retrieval gate before the model, and with the gate patched off in memory the model declined all seven attack cases with no system-prompt leak and no injected output, but 4 of 7 refusals were not classified as `refusal` events (no office routing). **Open decision:** treat the timing claim and the unrouted refusals as fixes or as documented limitations. Real-browser open of the client (T29) was done against the zero-quota demo server only: sources with `stale` badge, citation, `rewritten_query` on a follow-up and the refusal block all rendered; stage timings were stub zeros, so null-stage `—` rendering is unchecked.
- [x] Refusal always routes to a real office (code + tests; live refusal run still open, see above)
- [x] **No UI decision has been made or needed**

---

# Phase 6 — Portfolio

## Task 30: Results table generator

**Acceptance criteria:**
- [x] `RESULTS.md` regenerated from `runs/` — never hand-edited (`scripts/generate_results.py`)
- [x] Every row carries n, split, and cost alongside quality (cost = median `wall_s`, PLAN 4f; `--` for retrieval-only runs)
- [x] Baseline rows marked as controls — 3a and 3c only: there is no 3b run dir (3b was a read-through, not a scored run)
- [x] Quality/cost Pareto frontier plotted (§4b) — `results_pareto.svg`, hand-written SVG so output is deterministic; dev split only, faithfulness vs median wall time

**Verification:** Delete and regenerate; output is byte-identical. — done 2026-09-24: sha1 of `RESULTS.md` and `results_pareto.svg` identical across delete/regenerate; also `test_regeneration_is_byte_identical`. 628 tests pass.

**Resolution:** the Pareto frontier is faithfulness-only, so `answerability_gate_gemma4_31b` sits on it despite being rejected in `decisions/0014` (it refuses more: refusal_correct 0.683). The generated text says so rather than letting the plot endorse it. Test-split runs are in the table but deliberately off the frontier.

**Dependencies:** T22 · **Scope:** M

## Task 31: Architecture diagram + README

**Acceptance criteria:**
- [x] Offline ingest and online query paths both drawn (mermaid in README)
- [x] Three-line crawl policy statement present (T2)
- [x] Corpus coverage numbers cited from the manifest (T4), not estimated — found `docs/coverage.md` stale (fetched 1857 vs manifest 1847); regenerated
- [x] Setup instructions actually followed on a clean checkout — found two README gaps (missing service/index/scoring extras) and fixed them; 626 pass, 2 need gitignored corpus artifacts, documented

**Dependencies:** T30 · **Scope:** S

## Task 32: Limitations + writeup

**Acceptance criteria:**
- [x] Self-authored eval set, author-is-designer blind spots, cloud attributability-not-reproducibility, single-model abstention — each stated plainly, **not buried in footnotes**
- [x] Judge-human agreement number reported if a Tier 3 judge was used (§4d) — κ = 0.146, judge dropped
- [x] Test-split access log reproduced verbatim (from `notes.md`)
- [x] What actually moved the numbers, including what did not (`docs/LIMITATIONS.md`)

**Dependencies:** T30 · **Scope:** M

## Task 33: Recorded demo walkthrough

**Acceptance criteria:**
- [ ] Covers a single-silo question, a cross-silo question, and a refusal that routes
- [ ] Sources-render-before-answer behavior visible on camera
- [ ] Recorded, not a live deploy — Phase 5 is local unless the public checklist is done

**Dependencies:** T29, T31 · **Scope:** S

### ✅ Checkpoint G — shipped
- [ ] `RESULTS.md` generated, limitations written, demo recorded
- [ ] Ablation table is the centerpiece, not the demo


---

# Phase 6b — Service hardening (added 2026-09-24)

Origin: the live safeguard check in `docs/LIMITATIONS.md` section 7 (4 of 7 refusals
unrouted, sources-to-token gap under 1 s, answers arriving in one piece, no input
escaping) plus the industry research (OWASP LLM prompt-injection cheat sheet,
Microsoft delimiting/datamarking, structured abstention). Free tasks first; the
one task that spends quota (T41) waits for its own go-ahead. Every arm is
pre-registered before it runs and every arm tried is logged with why losers lost.
`train`/`dev` only: the test split is not touched.

## Task 37: Scan the corpus for indirect-injection text (free)
Instruction-like text inside crawled pages is the one injection route the live check did not cover.
**Acceptance:**
- [x] A deterministic scanner over `corpus/chunks.jsonl` flags instruction-like patterns; the pattern list is fixed in the script before the first run
- [x] Output: count, per-pattern hits and the flagged chunk ids and URLs, in `docs/`
- [x] Every hit is triaged by hand as benign or real, and the tally is reported (no "clean" claim without the list)
**Result:** 37 candidates, 0 real (`docs/injection_scan_triage.md`).
**Verification:** re-running (done: identical) the scanner on the same `chunks.jsonl` gives a byte-identical report.

## Task 38: Escape delimiter tokens in user text (free)
`</question>` in a user turn is not escaped today.
**Acceptance:**
- [x] A `PromptSanitizer` class behind an interface neutralises `<question>`, `</question>`, `<passages>` and `</passages>` in user and history text; a benign question is unchanged
- [x] Applied at the one place the user turn is wrapped; unit tests cover each token, case variants and a benign control
- [x] The frozen retrieval config and generation prompt text are untouched
**Verification:** full suite 642 passed (was 628 + new tests); the fake-tag live case is re-run in T39. `NoOpSanitizer` is the control arm.

## Task 39: Injection regression suite (free, then small live)
**Acceptance:**
- [ ] A fixed case file: the 7 live cases plus new phrasings, multi-turn attacks and encoded payloads (base64, typoglycemia), each with its expected outcome; written before any run
- [ ] A runner with a stubbed generator (in pytest) checks plumbing; a separate script runs it live and writes a dated report, never a pytest assertion
- [ ] Live results reported per case, n=1 and marked non-deterministic; repeated runs for any case that flips
**Verification:** live report committed under `docs/`; pass/fail counts stated, failures listed.

## Task 40: Service refusal classifier, offline replay (free)
The eval classifier `looks_like_a_refusal` stays frozen so historical `refusal_correct` stays comparable.
**Acceptance:**
- [ ] `ServiceRefusalClassifier` class behind the refusal interface, in the service only; variants pre-registered: (0) current, (1) widened phrases, (2) cite-nothing rule, (3) 1+2 combined
- [ ] Replay over saved `per_query.jsonl` answers, dev and train only, plus the 4 missed live refusals; report catch rate on known refusals and legitimate answers wrongly flipped, for every variant
- [ ] Decisions doc lists every variant and why losers lost; the winner is wired only if it catches the 4 misses with zero legitimate answers flipped, otherwise the result is logged and nothing ships
**Verification:** replay script is deterministic and re-runnable; full test suite passes.

## Task 41: Structured decision field for refusal (live quota)
Answer or abstain becomes a schema field rather than parsed prose. Changes the frozen prompt of `decisions/0014`, so it is an A/B and not a swap.
**Acceptance:**
- [ ] **Waits for an explicit go-ahead**, because it spends generation quota and touches a frozen prompt
- [ ] Arms pre-registered: control = current prompt + T40 winner; arm = structured `decision` field; noise-floor rerun of the control beside it
- [ ] Dev only. Report refusal_correct, out-of-scope answered count, Tier 1 faithfulness, and cost as a median, each with CI and against the noise floor
- [ ] Adopted only if it clears the noise floor; otherwise logged as rejected
**Verification:** run dirs with config, split hash and model lock; decisions doc with every arm.

## Task 42: Sources-before-tokens timing and one-piece delivery
Live check: gap 0.65 s, 1.07 s, 0.63 s against a claim of at least 1 s; token, citation and done arrive within about 0.05 s of each other.
**Acceptance:**
- [ ] Find out whether the generator is non-streaming or the service buffers; report the cause with evidence (code path and timestamps)
- [ ] Decide fix or limitation: either make streaming incremental, or change the claim to what was measured; state which
- [ ] If a fix is made, re-measure live over at least 5 warm calls and report the median, not the best
**Verification:** measured numbers in `docs/LIMITATIONS.md`; the claim in the plan matches them.

### ✅ Checkpoint 6b: service hardening reviewed
- [ ] T37 to T40 and T42 done or explicitly waived; T41 done or explicitly deferred
- [ ] `docs/LIMITATIONS.md` section 7 updated to what the new numbers say
- [ ] Layer table (input, gate, prompt, model, output, access, ops) states what each layer now covers and does not

---

# Phase 7 — Maintenance

Development ends; the college's website does not. This phase is **a cron job and
four alerts** (PLAN §Phase 7). It is not an ops practice: no dashboards, no
uptime SLO, no on-call rotation, no retraining loop.

## Task 34: Scheduled re-crawl + the four alerts

**Description:** One scheduled job that re-runs crawl → extract → manifest →
incremental reindex, and shouts when any of the four decay modes fires. Silence
is the success condition.

**Acceptance criteria:**
- [ ] Single entry point runs the whole ingest chain unattended and exits non-zero on failure
- [ ] Alert 1 — **extraction regression**: any pinned snapshot page (T6) whose extracted text changes shape, or goes empty on an HTTP 200
- [ ] Alert 2 — **corpus shape drift**: new 404s on previously-fetched URLs, or the manifest `other`-silo rate crossing 10%
- [ ] Alert 3 — **volume anomaly**: fetched-page count moving more than a set fraction versus the last run, in either direction
- [ ] Alert 4 — **stale gold** (T35): any gold question whose source `content_hash` changed
- [ ] Every run appends a dated row to a maintenance log; **no row is ever deleted or edited**
- [ ] An alert is a written record plus a non-zero exit, not a notification service

**Verification:** Force each of the four conditions against a fixture corpus and
confirm each fires independently and names the offending URLs.

**Dependencies:** T6, T10, T35 · **Scope:** M

## Task 35: Gold-set decay — content-hash pinning and stale accounting

**Description:** The decay mode that degrades *measurements* rather than the
product, and the only one invisible from the outside. A gold answer keyed to a
page the college has since rewritten is silently wrong, and every metric
computed against it is silently wrong too.

**Acceptance criteria:**
- [ ] Every gold reference carries the `content_hash` of the page it was read from, written at authoring time (amends T12/T13)
- [ ] A changed hash marks the question `stale`; stale questions are **excluded from metrics until a human re-reads the page**
- [ ] The **stale count is itself reported** on every results table — a shrinking denominator is a different metric, not the same one measured better
- [ ] Re-verification updates the pin and records who re-read it and when
- [ ] Stale-marking never edits or deletes the original question text

**Verification:** Mutate a fixture page, re-run, and confirm the affected
questions drop out of the metric and appear in the stale count with their URLs.

**Dependencies:** T12, T13, T30 · **Scope:** M

## Task 36: Re-run trigger and result versioning

**Description:** Decides *when* the published numbers stop being true.

**Acceptance criteria:**
- [ ] Trigger fires when >10% of pages have changed since the `corpus.lock` behind `RESULTS.md`, or when any T34 alert is open
- [ ] A fired trigger re-runs the frozen Checkpoint-E config only — **not a new tuning round**; re-tuning is a decision, not a maintenance action
- [ ] New numbers are added to `RESULTS.md` as a dated row against the new `corpus.lock`; **old rows stay**
- [ ] The test split is not re-spent by maintenance re-runs; any re-use is logged in the test-split access log

**Verification:** Simulate a 12% corpus change and confirm the trigger fires, the
re-run reuses the frozen config, and both rows survive regeneration.

**Dependencies:** T30, T34 · **Scope:** S

### ✅ Checkpoint H — maintenance mode
- [ ] One scheduled job covers all four decay modes
- [ ] Stale gold is measured and reported, not quietly dropped
- [ ] Nothing here requires a human unless an alert fires

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Retrieval proxy doesn't track answer quality | **High** | Checkpoint D gate (T16) before any tuning |
| Quota exhausts mid-sweep | Med | T17 resumability; free ablations first; T3 budget known up front |
| Gold labels too coarse to score cross-silo | **High** | Heading-level refs + conjunctive flags decided in T12, before authoring |
| Silo taxonomy doesn't fit the real IA | Med | `other` rate measured in T8; >10% triggers revision |
| Extraction silently degrades after a site reskin | Med | Snapshot regression tests (T6) |
| 300 hand-written questions is too much effort | Med | Split by slice across sessions; reduce total only by shrinking train, never test |
| A silo is named but has no office behind it | Med | T8 rejects any silo without an `offices.yaml` row — it folds or is marked ownerless |
| Corpus gaps invisible; a gold question has no supporting chunk and nobody knows why | Med | T4 manifest records every URL *considered* with a class-prefixed reason |
| UI decisions leak into the backend, making the front end hard to swap | Med | T24 asserts no web-framework import in the service module; T23 freezes the contract first |
| Gold answers rot as pages are rewritten; metrics stay confident and wrong | **High** | T35 pins refs to `content_hash`; stale questions leave the metric and the stale count is published |
| Maintenance quietly turns into an unplanned tuning round | Med | T36 re-runs the frozen Checkpoint-E config only; re-tuning is a separate decision |
| The disposable reference client quietly becomes the product | Low | Header states it is disposable; it is a test fixture with no styling budget |

## Open questions

- SmartCatalogIQ **terms of use** — robots permits crawling, terms unread (T7)
- ~~Whether Ollama Cloud returns `eval_duration`~~ -- **closed by T3: it does not,**
  on either surface. Cost accounting is client wall-clock, labelled as such in
  `timing_source`; the native endpoint offers `total_duration` and nothing finer
  (`docs/quota-calibration.md`)
- τ calibration method — three candidates, decided empirically (T21)
- Whether a Tier 3 judge is used at all, pending κ against hand-scores (T19)
- Single-label vs multi-label silos — **multi-label chosen**, cross-silo defined
  at page level instead; revisit only if the `other` rate or hand-check accuracy
  says the labels are unusable (T8)
- **Front-end form is deliberately undecided** — widget, standalone site, or
  something else. Phase 5 is built so this can be answered after Checkpoint F
  without touching the backend

## Resolved 2026-09-10

- Multi-turn slice **kept** at ~15 questions rather than cut (PLAN Phase 2)
- Silo discovery has a procedure: *a silo is a topic with an office that has a
  published contact page.* T8b folded into T8
- Crawl policy trimmed to robots + rate limit; `CRAWL_POLICY.md` dropped, three
  README lines instead
- Crawl manifest records every URL considered, with a reason for every omission
- Analysis plan is pre-registered at Checkpoint D; significance claims confined
  to the pooled test set, slices reported as effect size + CI only
- Phase 4 retrieval ablations are factorial, not OFAT; the metered half stays
  OFAT as an explicit quota decision
- Long-term shape is maintenance, not a second build: four decay modes, four
  alerts, and an explicit not-doing list
- Phase 5 is a backend with a versioned stream contract; UI deferred by design
