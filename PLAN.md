
# Maryville College RAG Chatbot — Project Plan

**Target:** working product + portfolio artifact + reproducible experiment logs.
**Scope:** whole-site, cross-silo (all of `maryvillecollege.edu` + SmartCatalogIQ catalog).
**Status:** personal project, no institutional backing.

---

## 0. Framing

Maryville College (Maryville, TN; ~1,132 undergrads; founded 1819) already ships
**"Ask Scottie — Academic Catalog Assistant,"** a SmartCatalogIQ vendor widget on
`/academics/catalog/`. Its scope appears limited to the catalog.

> **Ask Scottie is context, not the measurement target.** It is a vendor widget
> outside our control, and in practice not reliably accessible for testing.
> Anchoring the thesis to beating it would make the project's central claim
> depend on a system we can neither access nor pin. **Demoted to background.**
> If it is working when Phase 6 arrives, run the comparison opportunistically
> and report it as an anecdote (§4). Nothing else depends on it.

**The thesis stands on the site's own structure, not on the incumbent.**
Financial aid, International Student Services, registrar, residential life and
athletics are substantial, **separately-maintained** sections — and the questions
students actually have cut straight across them. That split is verifiable
directly from the site's information architecture; it needs no comparator.

Do not build "a chatbot for Maryville College." Build **the cross-silo one**.
Three claims, each measurable without reference to any other system:

1. **Cross-silo capability** — answers questions requiring ≥2 separately-owned
   pages, measured with conjunctive scoring on a held-out test split.
2. **Abstention discipline** — refuses what it cannot support and routes to the
   owning office, reported as a correct/false-refusal pair.
3. **A reproducible ablation record** — control conditions, locks, and a
   quality/cost frontier showing what actually moved the numbers.

Claim 3 is the portfolio artifact. Claims 1 and 2 are the product.

### Name collision — do not get this wrong

- **Maryville College** — Maryville, TN. `maryvillecollege.edu`. SmartCatalogIQ. <- this project
- **Maryville University** — St. Louis, MO. `catalog.maryville.edu`. Acalog. <- not this project

---

## 1. Corpus

From `robots.txt`, three declared sitemaps:

| Sitemap | Contents | In corpus? |
|---|---|---|
| `wp-sitemap-posts-page-1.xml` | ~800–900 pages — the main site | ✅ yes |
| `wp-sitemap-posts-post-1.xml` | **~850 dated news posts** | ❌ **excluded — see below** |
| `wp-sitemap-posts-academic_programs-1.xml` | program pages | ✅ yes |

**News is excluded (verified Sept 2026).** The sitemap holds ~850 dated
announcements — dean's lists, coach hirings, 2021 virtual-event notices, MLK day
activities. Three reasons:

- **Stale-date hallucination.** "MC will host a virtual Meet Maryville event
  March 27" retrieved against an admissions-events query yields a confident
  answer about a five-year-old event — precisely the high-stakes failure this
  project exists to avoid.
- **Dilution.** ~850 news chunks would roughly double the corpus and compete
  against the policy pages students actually need.
- **It confirms the `lastmod` warning empirically:** a 2017 article carries a
  `lastmod` of 2026-02-02. WordPress bulk-edits these, so `lastmod` is useless
  as a change signal and content hashing is mandatory (§2e).

Revisit only as a separate, clearly-labelled index if "what's happening on
campus" ever becomes a target query class. Not in v1.

**SmartCatalogIQ:** `maryvillecollege.smartcatalogiq.com/en/current/academic-catalog/`
— 13 sections, course-level detail, 2026–27 edition, archived editions as PDFs.

**Its `robots.txt` permits this (verified Sept 2026):** the only `Disallow` is
`/sitecore/`, the Sitecore CMS backend. No `Crawl-delay`, and — importantly —
**no declared sitemap.** URL discovery must walk the catalog's own navigation
tree, so this needs its own crawler adapter rather than the sitemap path used
for WordPress. Terms of use are a separate question from robots; check the
catalog footer before ingesting (Phase 1).

Section structure observed: about; academics (divisions, faculty, registrar,
library, success center); admissions and financial aid (scholarships, federal
grants, state aid, student employment); international (ISS: immigration,
pre-arrival, orientation, support services; study abroad: semester, summer,
travel-study); campus life (residential, counseling, disability resources,
health, dining, IT); athletics; alumni; giving; governance; Title IX; consumer
information; accreditation.

**Estimated 3,000–6,000 chunks.** Revised: news exclusion removes ~850 pages,
but the 600→400 token cap (§2c) raises chunks-per-page roughly 1.5×, and the
second effect dominates. Still small. Retrieval *quality* is the entire problem;
scale is not a problem at all. Do not reach for infrastructure sized for a
corpus you do not have. Recount after Phase 1 and correct this figure.

### Crawl policy — two load-bearing rules, and a manifest

Trimmed to what actually does work. Two parties are affected: the college's web
infrastructure, which cares only that you do not hammer it, and a reader of the
portfolio, for whom a crawler that ignored a site's stated rules undercuts the
methodological-rigor pitch on page one. Both are satisfied cheaply.

**The two rules that matter:**

- **Rate limit ~1 req/sec, identifying User-Agent carrying a contact address.**
  Four lines of code; removes the infrastructure risk entirely.
- **Honor every `robots.txt` Disallow.** The parser is required anyway to
  discover the sitemaps, so enforcement is nearly free. Known WordPress
  disallows: `/wp-content/uploads/*`,
  `/academics/catalog/smart_catalog_course/*`, `/news/smart_catalog_block/*`,
  `/news/smart_catalog_prog/*`, `/niche-direct-admissions.html`.

**Standing constraints, stated once:** sitemap-driven fetching, never blind
recursive crawling; public pages only — no authenticated content, no student
records, **no FERPA surface in this project and it must stay that way**; read
the SmartCatalogIQ footer terms once during Phase 1 and write down what they
say; carry an "unofficial, not affiliated with Maryville College" disclaimer if
this is ever public. The catalog itself states it is not a binding contract.

*No separate policy document.* The above lives as three lines in the README and
as assertions in the fetcher. A `CRAWL_POLICY.md` that nothing reads is ceremony.

### The crawl manifest — know what you have and what you could not get

`corpus/manifest.jsonl`, **one record per URL considered, not per URL fetched.**
The distinction is the whole point: a corpus that records only its successes
cannot tell you what is missing from it.

```jsonc
{"url": "...", "source": "wp-sitemap-posts-page-1", "status": "fetched",
 "http": 200, "content_hash": "...", "fetched_at": "...", "bytes": 48213,
 "extracted_chars": 3117, "silo": ["finaid"], "chunks": 6}

{"url": "...", "source": "wp-sitemap-posts-post-1", "status": "excluded",
 "reason": "policy:news_excluded"}

{"url": "...", "source": "catalog-nav", "status": "excluded",
 "reason": "robots_disallow:/sitecore/"}

{"url": "...", "source": "catalog-nav", "status": "failed",
 "http": 404, "reason": "http_error", "attempts": 3}

{"url": "...", "source": "wp-sitemap-posts-page-1", "status": "skipped",
 "reason": "unchanged_hash", "content_hash": "..."}
```

Status is one of `fetched` · `excluded` · `failed` · `skipped`. Every
non-fetched record **must** carry a machine-readable `reason` prefixed by its
class: `robots_disallow:` · `policy:` · `http_error` · `extraction_empty` ·
`unchanged_hash`. A bare "excluded" is useless six weeks later.

Four things it buys, each of which is otherwise guesswork:

1. **A defensible coverage claim.** "N of M sitemap URLs indexed, with every
   omission attributed" is a sentence the writeup can actually make.
2. **Gap diagnosis.** When a gold question has no supporting chunk, the first
   check is whether the page was never fetched, fetched but extracted empty, or
   fetched and chunked but simply not retrieved. These have completely different
   fixes and the manifest separates them in one grep.
3. **`corpus.lock` accounting.** The lock hashes what was indexed; the manifest
   explains it.
4. **Re-crawl diffing.** New URLs appearing, old URLs going 404, and extraction
   silently collapsing to empty are all visible as manifest diffs between runs.

`extraction_empty` deserves its own status rather than hiding inside `fetched`:
a page that returned HTTP 200 and extracted to nothing is the exact signature of
the `trafilatura` regression that §2e exists to catch.

---

## 2. Architecture

Python 3.11+.

**OFFLINE — ingest & index** (re-runs on a schedule; §2e)

```
sitemaps ──> polite fetcher ──> raw snapshot store (content-hashed, dated)
                                        │
                                        v
                          trafilatura main-content extraction
                          (strips shared nav/footer chrome)
                                        │
                                        ├──> extraction regression test
                                        v
                       heading-aware chunking + metadata stamping
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              v                         v                         v
       dense index               BM25 index               literal index
       (LanceDB)                                          (substring/regex)
```

Changed pages only: content-hash diff → delete-by `source_url` → re-insert.

**ONLINE — query path**

```
user question
     │
     v
reformulation ladder (§4c)
  acronym dict ─ normalize ─ decompose ─ multi-query ─ ...
    (free)        (free)      (cloud)      (cloud)
     │
     v
entity-pattern detection ──> query type ──┐
     │                                    │ (weights)
     ├───────────────┬───────────────┐    │
     v               v               v    │
   dense           BM25          literal  │   literal fires only
     │               │               │    │   on a pattern hit
     └───────────────┴───────────────┘    │
                     │                    │
                     v                    v
        fusion: RRF → rule-routed weights → MoR  (§4c)
                     │
                     v
          cross-encoder rerank  (top-50 → top-k)
                     │
                     ├──> score < τ ──> refuse + route to responsible office
                     v
        gpt-oss:20b-cloud + forced citations
                     │
                     v
              FastAPI SSE ──> chat UI
       (sources render at rerank, before generation returns — §4b)
```

**Boilerplate stripping is the single highest-leverage step.** ~900 WordPress
pages share identical nav and footer text. Embed that chrome and every chunk
looks like every other chunk; retrieval collapses. Run `trafilatura` before
anything else.

**Chunk metadata is mandatory**, not optional — it is what makes cross-silo
routing and citation possible:
`source_url`, `title`, `breadcrumb`, `silo` (admissions / finaid / iss /
registrar / ...), `heading_path`, `crawled_at`, `content_hash`, `catalog_year`.

### Stack choices (recommendations, with the reason)

| Layer | Pick | Why |
|---|---|---|
| Extraction | `trafilatura` | Best-in-class boilerplate removal for CMS pages |
| Chunking | heading-aware, **~400 tok cap**, ~15% overlap | Site has real H2/H3 — respect it. 400 not 600: the embedder truncates at 512 and heading prefixes need headroom. See §2c |
| Embeddings | `BAAI/bge-base-en-v1.5` (109M) via `sentence-transformers` | Corpus is English-only — 5× lighter than `bge-m3` at comparable English quality, and m3's sparse output is redundant next to real BM25. **512-token limit couples to chunk size — see §2c.** English-only is fine for the *Future* Spanish item: that is served by a translate-in layer, not a multilingual index |
| Vector store | LanceDB | Embedded, file-based, zero ops — and a file-based index is *version-controllable*, which the experiment log needs |
| Lexical | BM25 alongside dense | Course codes, form names, and dollar figures are exact-match queries that embeddings fumble |
| Literal | pattern-triggered substring/regex scan | BM25 is bag-of-words and loses adjacency + punctuation (`I-20`, `$1,500`). Milliseconds at this corpus size. Trigger on query entity patterns only — see §4c |
| Fusion | RRF baseline → rule-routed weights → MoR | RRF needs no tuning but weights every retriever equally on every query, which is wrong for a mixed exact/conceptual workload. §4c |
| Rerank | `cross-encoder/ms-marco-MiniLM-L-6-v2` (22M) | Sub-second on CPU for 50 pairs; `bge-reranker-base` (278M) is the quality ablation |
| Generation | `gpt-oss:20b` via **Ollama Cloud**, over the **OpenAI-compatible API** | No local weights, no VRAM ceiling. The API shape — not the model — is the portability contract. See §2a |
| Serving | FastAPI + SSE streaming | Streaming is required for acceptable perceived latency |

### 2a. Model posture — cloud LLM, local retrieval models

**The one architectural decision that matters: program against the
OpenAI-compatible `/v1/chat/completions` interface.** Ollama Cloud, local
Ollama, vLLM, llama.cpp server, Groq, Together, OpenRouter and DeepInfra all
speak it. Use the `openai` SDK with `base_url` pointed at whichever is running,
so the backend is a **config string in `config.yaml`**, not a code change.

```python
client = OpenAI(base_url="https://ollama.com/v1", api_key=os.environ["OLLAMA_API_KEY"])
```

**Three model roles — only one of them is the LLM.** Conflating them is the
mistake to avoid here:

| Role | Model | Size | Where it runs | Why |
|---|---|---|---|---|
| Generation | `gpt-oss:20b-cloud` | ~12.8GB | **Ollama Cloud (free)** | Reasoning MoE (~21B total / ~3.6B active). Hosted → no VRAM ceiling, no offload. Confirmed in the free **starter** model set; **level 1 — the lightest usage class**. Note the `-cloud` tag suffix |
| Embedding | `bge-base-en-v1.5` | 109M | local `sentence-transformers` | Not offered on Ollama Cloud. Index build embeds ~3k chunks and re-embeds on **every** chunking ablation — thousands of metered calls for a model that finishes in seconds locally |
| Reranking | `ms-marco-MiniLM-L-6-v2` | 22M | local `sentence-transformers` | **Ollama exposes no rerank endpoint in any form.** Cross-encoder pair scoring is not generation or embedding; it runs under PyTorch or it does not exist |

The two retrieval models total **131M parameters, under 1GB combined.** They
were never the VRAM problem — `gpt-oss:20b` was, and cloud solves that. Losing
the reranker to a "no local models" rule would forfeit one of the two largest
quality levers in the whole pipeline (boilerplate stripping being the other) in
exchange for nothing.

**Free-tier shape (verified Sept 2026)** — this is what Phase 4 must live inside:

| Property | Value |
|---|---|
| Metering | **GPU time**, not tokens or requests |
| Published caps | **None** — no RPM/TPM figures given; must be measured empirically |
| Reset clocks | session every **5 hours**, plus a **weekly** reset |
| Concurrency | **1 request at a time** — eval runs are strictly sequential, no async fan-out |
| Model access | starter set only (GPT-OSS, Gemma 4, MiniMax, Nemotron); credits unlock the rest |
| Upper rung | `gpt-oss:120b-cloud` exists for ablation #10 if quota allows |

Sequential-only is the binding practical constraint: at ~5–15s/query with
reasoning, one 150-question pass is **~12–40 min wall-clock**. Sweeps are
overnight jobs, not coffee breaks. See §4a for the execution strategy.

- **⚠️ `num_ctx` silently truncates (default ~4096).** A RAG prompt carrying
  5–10 chunks plus a system prompt will have its retrieved context quietly
  dropped — recall@k looks fine while answers are garbage, and the bug reads as
  a retrieval failure. Set it explicitly and assert prompt token length against
  it at runtime, before every call.
- **`gpt-oss:20b` emits a reasoning channel.** Parse/strip it before citation
  extraction; budget for inflated output-token count in latency metrics.
- **Set `temperature: 0` and log it.** Cloud endpoints may not honor seeds, so
  temperature is the only determinism lever you fully control.
- **Local `gpt-oss:20b` is the escape hatch, not the plan.** ~12.8GB MXFP4
  exceeds both RTX 5070 configs (12GB desktop / 8GB laptop), so it would mean
  partial expert offload at ~25–40s/query. Ollama ships native MXFP4 kernels
  targeting RTX 50-series, so it works — just slowly. Keep it documented for
  the case where cloud quota runs dry mid-experiment.
- **Scale path:** same code, `base_url` → vLLM with continuous batching on a
  rented GPU, or any hosted OpenAI-compatible endpoint.
- **Honest note on "scalable":** at ~3k chunks the whole index fits in RAM.
  Retrieval does not need to scale. Only concurrent generation does — which is
  exactly what the vLLM swap addresses.

### 2b. Retrieval evaluation is free — build that loop first

**Retrieval metrics require no LLM.** The gold set maps question → gold
**heading/chunk refs** (Phase 2); the retriever returns ranked chunks carrying
the same metadata. recall@k, MRR and nDCG are pure set arithmetic over those two
lists. No generation, no cost, milliseconds per query.

```
config.yaml → build index → run ~300 gold questions → metrics.json
```

Consequence for phasing: **ablations #1–#5 (boilerplate, chunking, retrieval
mode, reranker, `k`) — the ones with the largest effect sizes — are tunable in
a tight, free, seconds-long loop before a generator is wired up at all.**
Build the retrieval-only harness first; attach the generation harness second.

Cache embeddings keyed on `(model_name, chunk_text_hash)` so repeated configs
don't re-embed unchanged text.

**Chunk size is coupled to the embedding model** — `bge-base-en-v1.5` truncates
at 512 tokens, silently. Resolved in §2c: 400-token cap, swept as coupled
`(chunk_size, k)` pairs.

### 2c. Silo taxonomy and chunk sizing

**A silo is the office that owns the content.** It is a metadata tag on every
chunk, derived from URL path plus breadcrumb, and it is load-bearing in four
places — which is why it needs a fixed taxonomy, not a vague list:

1. **It defines the thesis.** "Cross-silo" means *spanning two or more silos*.
   Without the tag you cannot even identify which questions those are.
2. **It stratifies the gold set** — the cross-silo slice is defined by it.
3. **It drives routed retrieval weights** (§4c).
4. **It makes refusal useful** — "contact the Financial Aid Office at <link>"
   requires knowing which office owns the topic.

Starting taxonomy (finalise against the live IA in Phase 1; `other` permitted
but tracked as a coverage defect):

`admissions` · `finaid` · `iss` (international) · `study_abroad` · `registrar` ·
`academics` · `residential` · `student_health` · `disability` · `athletics` ·
`title_ix` · `consumer_info` · `giving` · `alumni` · `governance` · `other`

**Silo discovery — the procedure, resolved.** The taxonomy above is a starting
guess and must not stay one. The test that makes discovery robust rather than a
matter of taste:

> **A silo is a topic that has an office with a published contact page.**

That is falsifiable from the site alone. If you cannot name an owner with an
email address, it is not a silo — it is a topic, and it folds into its parent or
becomes ownerless. Four steps, in order:

1. **Harvest every URL path prefix from the manifest and count pages under
   each.** Mechanical, no judgment, and it produces the candidate list *with
   sizes* — a prefix holding three pages is not an office.
2. **Pull the top navigation and every breadcrumb trail.** Published information
   architecture is the org chart as the college presents it, and it is what a
   student actually navigates. Where nav and URL structure disagree, that
   disagreement is itself worth recording.
3. **Match each candidate against the staff/office directory.** A match promotes
   the candidate to a silo **and fills one row of the contact-routing table in
   the same step.** No match means fold or mark ownerless.
4. **Assign labels by rule** — path prefix plus breadcrumb, multi-label
   permitted — then hand-check ~10 pages per silo and record the accuracy.

**This merges T8 and T8b into one task.** The contact table was never separate
work: it is the byproduct of doing silo discovery properly, and treating it as a
follow-on is what let it go missing in the first place.

The remaining open questions resolve as consequences of the test above:

- **Granularity** — a division is its own silo if and only if it has its own
  contact page. `academics` splits exactly where the college itself splits it.
- **Ownerless content** — About, history and similar pages genuinely have no
  owner, so `other` is *correct* there, not a defect. What is tracked is the
  **rate**: above ~10% the mapper is broken, not the site.
- **Taxonomy source** — neither URL structure nor org chart alone. Step 1 gives
  candidates, step 3 gives authority, and the directory is the tiebreak.

**Remaining open question — the one the procedure does not settle:**

1. **Single-label or multi-label?** A page on international student financial
   aid belongs to ISS *and* finaid. Forcing one owner is lossy; allowing several
   muddies "cross-silo". **Resolution: allow multi-label chunks, and define the
   thesis at page level instead —**

   > A **cross-silo question** is one whose gold refs span **≥2 pages owned by
   > ≥2 different offices.**

   This matters more than it looks. If one page already covers both offices, the
   college has *already done the integration work* — that is not the gap this
   project claims to fill. The claim is about information split across
   separately-maintained pages.
   Note that the contact-routing table this depends on is no longer a gap: it
   falls out of discovery step 3 above. **"I don't know" is worth far less than
   "I don't know — here is the Financial Aid Office,"** and that difference is
   the headline abstention feature, so the table is load-bearing rather than
   decorative.

**Chunk size: `chunk_size` and `k` are not independent.** Under a fixed
generation context budget, `chunk_size × k ≈ budget`. Sweeping them separately
compares context *volume*, not chunking — (512, 20) is 10k tokens while
(256, 5) is 1.3k, and no conclusion drawn across them is about chunking at all.

Decision procedure:

1. **Hard ceiling.** `bge-base-en-v1.5` truncates at 512 tokens, silently.
   400 is the working cap, leaving room for heading-path prefixes.
2. **Fix a context budget** (~4,000 tokens), then sweep coupled pairs that hold
   it roughly constant: **(256, 16) · (384, 10) · (512, 8)**.
3. **Score on retrieval metrics** — free, so the entire sweep costs no quota.
4. **Validate the winner end-to-end** via the Phase 3b procedure before freezing.

This turns ablation #2 from "guess a number" into a one-dimensional sweep along
a real constraint surface.

### 2e. Ingest is stable, but verify it

Crawl → extract runs repeatedly and unattended, so it needs two mechanisms:

- **Extraction regression test.** `trafilatura` is heuristic. A site reskin can
  silently turn extraction into nav chrome or empty strings, and retrieval
  quality degrades weeks before anyone notices. Pin ~20 hand-picked pages (one
  per silo) with snapshot files of expected extracted text; diff on every crawl
  and fail loudly.
- **Incremental reindex.** Sitemap `lastmod` is a cheap pre-filter but
  unreliable on WordPress — the content hash is the real signal. Changed hash →
  re-extract → re-chunk → delete-by-`source_url` → insert. This is why
  `source_url` in chunk metadata is load-bearing: it is the delete key.

---

## 3. Phases

### Phase 0 — Foundations

Repo scaffold, dependency pinning, `.env` handling, and the two logging
conventions that make this rigorous rather than vibes:

- `decisions/` — dated ADRs, one per architectural choice, each stating the
  alternative rejected and why.
- `runs/` — one directory per experiment (see §5).

Write the crawl-etiquette policy down as a file *before* writing the crawler.

### Phase 1 — Corpus

Sitemap parser -> polite fetcher -> raw snapshot store -> extraction -> clean
corpus with manifest. SmartCatalog gets its own adapter; it is a different
platform with a different DOM.

Store **raw HTML snapshots, content-hashed and dated.** This buys reproducibility
(re-run any experiment against the exact bytes) and re-crawl diffing (detect what
the college changed). It costs a few hundred MB. Worth it.

### Phase 2 — Gold evaluation set — build this BEFORE any retrieval code

This is the discipline move that separates the project from a weekend demo, and
it is the phase most people skip. ~120–150 questions, each hand-labeled with the
gold source URL(s):

| Slice | n | Purpose |
|---|---|---|
| Slice | n @150 | **n @300** | Purpose |
|---|---|---|---|
| Single-silo factual | ~50 | **~80** | Baseline competence; direct Ask Scottie comparison |
| **Cross-silo (2+ offices)** | ~25 | **~70** | The differentiation claim, tested |
| **Out-of-scope / unanswerable** | ~30 | **~60** | Abstention — see below |
| Temporal / freshness | ~15 | **~25** | Deadlines, calendar, current catalog year |
| Exact-match | ~15 | **~25** | Course codes, form names, dollar amounts |
| Adversarial / leading | ~15 | **~25** | "Is it true that MC guarantees..." — resist the premise |
| **Multi-turn follow-up** | — | **~15** | **Kept, decided 2026-09-10.** De-contextualization is called *mandatory* in §4c and Phase 5 ships conversation memory, so it is measured rather than cut. ~6 test items is thin, but it catches total failure — and shipping a chat interface whose follow-up handling was never tested once is the worse option |

**Growth is deliberately non-proportional.** Cross-silo nearly triples because
it carries the thesis and is split 40/20/40 like everything else — at ~25 total
the test slice would be ~10 questions, too few to support the project's central
claim. Out-of-scope doubles because it drives the headline abstention metric.
The remaining slices grow modestly; they are supporting evidence, not the claim.

### Sizing and splits — decide before writing a single question

**Everything selected by looking at gold-set metrics is fitted**, even though
nothing takes a gradient step: chunk size, overlap, `k`, the RRF constant,
routed retriever weights, MoR weights, the generation prompt, the
synonym/acronym dictionary — and above all **the abstention threshold τ**.
τ is a scalar tuned to maximize correct-refusal rate, which *is* the headline
metric; selecting and reporting it on the same questions is circular.

The dictionary is the insidious one: "students say *money for school*, the site
says *institutional aid*" feels like domain knowledge, but if it was learned
from failures it is fitted, and it belongs to dev.

**Therefore ~150 questions is too few.** Split three ways, the out-of-scope
slice reports correct-refusal on n≈8 — noise, not a measurement.

| | Target |
|---|---|
| Total gold set | **~300 questions** (up from 150 — the split forces this) |
| Split | **40 / 20 / 40** train / dev / test, **stratified within every slice** |
| Test set | touched **once**, at the very end. Log every access in `notes.md` |
| Gold granularity | **heading/chunk level, not page level** — see Phase 3b |
| Multi-gold questions | mark **conjunctive** (all sources required) vs disjunctive |

The last two rows are cheap to decide now and expensive to retrofit. A
cross-silo question whose golds are labeled only as page URLs cannot be scored
correctly, because "hit the right page" and "hit the passage that answers it"
are different events on a long page — and averaged recall silently gives half
credit for an answer that is wholly wrong.

40/20/40 rather than 60/20/20 because you are fitting roughly six scalars, not
a neural network — train needs are modest, so mass belongs where statistical
power matters: the numbers actually reported.

**Cross-validate where it is free.** Retrieval metrics cost zero LLM calls, and
the τ sweep is computable offline from stored retrieval scores (§4a #3). k-fold
those over train+dev at no quota cost. Reserve test for one final pass — and
note that reporting on ~120 test questions instead of 300 makes the final
generation pass *cheaper*.

⚠️ **Splits fix hyperparameter overfitting. They do not fix the self-authored
distribution problem** — questions written by reading the site are drawn from
the corpus's own distribution in a way real student questions are not. A clean
test number invites false comfort here. Report these as two independent
limitations.

**Abstention is the headline metric, not an afterthought.** The literature is
explicit: one published academic-services RAG system reports **81.25% correct
refusal** on out-of-context questions as its central result. For a college bot
the asymmetry is brutal — a confidently wrong answer about visa status, aid
eligibility, or a filing deadline does real harm to a real student, while
"I don't know, contact the Financial Aid Office at <link>" costs nothing.
Track **correct-refusal rate** and **false-refusal rate** as a pair; either alone
is trivially gameable.

Write the questions yourself from lived knowledge of the college. Without
institutional backing you cannot harvest real student queries, so be honest in
the writeup that the query set is self-authored — a stated limitation, not a flaw
to hide.

### Phase 3 — Baselines (two of them, not one)

The ablations split across two metric families with different costs (§4a), so
they need **two control conditions**. Collapsing them into a single "RAG v0"
would spend generation quota at the point of maximum ignorance and leave the
free retrieval ablations with nothing to compare against on their own terms.

**Phase 3a — retrieval baseline. Costs zero.**
Deliberately naive: fixed 512-token chunks, dense-only, top-k=5, no literal leg,
no rerank, no query rewriting. Score recall@k / MRR / nDCG against gold URLs on
**dev**. This is the control for ablations #1–#5 and #7, all of which run free
and finish before any generator exists.

**Phase 3b — end-to-end sanity check. ~25 dev questions, trivial quota.**
Attach the naive generator to the 3a retrieval config and read the answers.
This is *not* the generation control condition — it exists to answer one
question: **does recall@k actually track answer quality on this corpus?**

Retrieval metrics are a proxy. A config with lower recall@5 but higher
precision can generate better answers, and tuning the proxy to completion
without ever validating it is the main risk the free-first strategy carries.
25 questions costs almost nothing and de-risks all of Phase 4.

**Hand-score the 25 answers 0/1/2 yourself.** Do not build an LLM-judge
pipeline for 25 items — validating the judge is more work than reading the
answers, and an unvalidated judge is worse than no judge.

**Diagnose by disagreement quadrant, not by a single correlation number.** The
two ways retrieval score and answer quality can disagree have unrelated causes:

*High retrieval score, bad answer* — retrieval worked, generation failed:

1. **`num_ctx` truncation first.** This failure signature is exactly what silent
   truncation produces (§2a). Rule it out before anything else.
2. **Distractors.** recall@k is blind to precision: 10 chunks with 1 gold and 9
   plausible-but-wrong can beat 3 chunks with 1 gold on recall while generating
   worse — wrong chunks induce hallucination and dilute attention.
3. **Chunk ordering in the prompt.** Lost-in-the-middle is real. A prompt-
   assembly fix, not a retrieval fix.

*Low retrieval score, good answer* — looks like good news, usually is not:

1. **The model answered from parametric knowledge, not the corpus.** For an
   institutional bot this is dangerous: it will state generic college facts
   confidently that are wrong for Maryville specifically. Check whether the
   answer actually cites retrieved chunks. If not, this is a grounding failure
   wearing a success costume.
2. **Gold labels are incomplete** — several pages could legitimately answer and
   only one was labeled.

**The two fixes most likely to be needed:**

- **Gold labeling granularity.** If gold is labeled per `source_url` but the
  answer lives in one section of a long page, retrieval "hits gold" with a chunk
  from the wrong part of it. Label at heading/chunk level instead. Expensive to
  fix retroactively — decide it in Phase 2, before questions are written.
- **Conjunctive scoring for cross-silo.** A cross-silo question needs chunks
  from finaid *and* ISS. Averaged recall gives 0.5 for finding one of two, but
  **partial recall on a conjunctive question is worth zero** — the answer is
  still wrong. Score those slices with all-golds-retrieved@k. This is specific
  to the project's central claim and is the most likely single culprit.

**The real deliverable of 3b: pick the primary retrieval metric empirically.**
If nDCG tracks hand-scored answer quality better than recall@k, optimize nDCG.
Choosing the proxy by convention is what causes this problem in the first place.

**Phase 3c — generation baseline.** Once retrieval is frozen after the free
ablations, run the naive prompt (no forced citations, no abstention threshold)
over the **dev** split. This is the control for #6, #8, #9 and #10.

All three are logged as ordinary runs (§5) with `split.lock` recording dev.

### Phase 4 — Ablations (the science)

Each fully logged. Ordering is set by **cost, not just effect size**: #1–#5 and
#7 are free and score against the Phase 3a retrieval baseline; #6, #8, #9 and #10
spend quota and score against 3c. Finish every free one and freeze retrieval
before running any of the metered ones.

**The free half is a factorial, not one-factor-at-a-time.** OFAT exists to
economise on expensive runs, and these runs cost nothing (§2b), so the economy
buys only a blind spot: OFAT cannot estimate interactions, and the interactions
here are expected rather than hypothetical. Reranking should help more at large
`k` than small. Boilerplate stripping changes what chunking has to work with.
The literal leg should matter on one stratum and nowhere else.

Split the factors by whether they force an index rebuild:

| | Factors | Levels | Cost |
|---|---|---|---|
| **Index-time** | boilerplate strip; chunking scheme | 2 × 2 | 4 index builds, minutes each |
| **Query-time** | reranker; fusion mode; silo boost | 2 × 2 × 2 | free, seconds per eval |

**4 index builds × 8 query-time configs = 32 evaluations**, and `k` sweeps
*within* each as a nested level rather than as a factor, since the
`(chunk_size, k)` coupling (§2c) already makes it non-orthogonal. The full
crossing is cheaper than the sequential OFAT plan it replaces, and it returns
main effects *and* two-way interactions from the same 32 runs.

Report main effects with the §4f paired intervals, and report the interaction
table separately — "the reranker is worth +X at k=20 and +Y at k=5" is a more
useful portfolio finding than either number alone.

**The metered half stays OFAT.** Quota, not design preference, decides that: a
factorial over generation factors multiplies runs by the number of cells, and
§4a's budget does not support it. Say so explicitly in the writeup rather than
letting the asymmetry look accidental.

⚠️ **Interleave metered runs by question, never by config.** Running config A to
completion and then config B confounds config with wall-clock, and §5 already
establishes that hosted weights can change silently behind a tag. `model.lock`
detects that drift but cannot unpick it — if it lands between two sequential
arms, the comparison is void and the lock only tells you so afterwards.
Interleaving spreads any drift across all arms equally, which turns a fatal
confound into ordinary noise. This is the one place where run order matters, and
it costs nothing to get right.

1. Boilerplate stripping on/off <- expect the single biggest jump
2. Chunking: fixed vs heading-aware vs semantic, sweeping **coupled
   `(chunk_size, k)` pairs** under a fixed context budget — §2c
3. Retrieval legs and fusion — dense / BM25 / **+literal (grep)** / hybrid+RRF /
   **rule-routed weights** / **MoR**. See §4c
4. Reranker on/off
5. `k` sweep (3, 5, 10, 20)
6. Query reformulation — run as a **ladder, cheapest first** (see below)
7. Metadata filtering by silo — **soft boost, not hard filter**; a hard silo
   filter is precisely how cross-silo queries, the thesis of this project, break
8. Prompt: citation-forced vs free-form
9. Abstention threshold sweep — plot the correct/false refusal tradeoff curve
10. Generation model: `gpt-oss:20b` vs a lighter cloud model at fixed retrieval
    — expect the abstention and cross-silo slices, not the single-silo factual
    slice, to separate them. Run this *last*, once retrieval is frozen, so it
    spends quota only on a settled pipeline

### 4c. Retrieval legs, fusion, and query reformulation

**Third leg: literal (grep) retrieval.** BM25 is weaker on the exact-match
slice than it looks — it is bag-of-words, so `MATH 1110` matches a chunk with
`MATH` in one paragraph and `1110` in another, and tokenization destroys the
very strings that identify these entities (`I-20` vs `I 20`, `$1,500` vs
`1500`). At ~3k chunks a substring scan is milliseconds.

**Use it as a trigger, not a blind third leg.** Detect entity patterns in the
*query* first; run literal retrieval and weight it heavily only on a hit:

```python
PATTERNS = {
    "course_code": r"\b[A-Z]{3,4}\s?-?\s?\d{3,4}\b",   # MATH 1110
    "form":        r"\b[IF]-\d{1,3}\b",                 # I-20, F-1
    "money":       r"\$[\d,]+(?:\.\d{2})?",
}
```

Literal search returns exact hits or nothing, so it never injects noise — but
running it unconditionally wastes a fusion slot on empty lists for the ~80% of
queries containing no code at all.

**Fusion: RRF baseline → rule-routed weights → MoR.** RRF weights every
retriever equally on every query, which is provably wrong here: an exact-match
query should lean on BM25/grep, a cross-silo conceptual one on dense.
**MoR** ([arXiv 2506.15862](https://arxiv.org/abs/2506.15862), EMNLP 2025)
computes *query-specific* retriever weights, Mixture-of-Experts style, and
reports +10.8% over the best single retriever at 0.8B total params.

The fit is unusually good — **the gold-set slices already are the query types**
MoR would weight over. But keep RRF as the control and try the cheap version
first: **rule-based routing** (detect query type → retriever weights from a
lookup table) is a hand-rolled MoR approximation that is free, deterministic,
explainable, and on a corpus this jargon-heavy probably captures most of the
gain. ⚠️ Tuning per-query-type weights against a *self-authored* gold set is a
real overfitting risk — hold out a slice.

**Ablation #6, the query-reformulation ladder** (each step costs more than the
last; stop when gains flatten):

1. **Domain synonym/acronym dictionary, bidirectional** — FAFSA, SEVIS, I-20,
   ISS, CRN, "MC". Must expand *and* contract: the query may say "International
   Student Services" while the page says "ISS", or the reverse. Hand-written,
   deterministic, free, zero latency. Exhaust this first.
2. **Spelling/format normalization** — free, and students misspell institutional
   jargon constantly.
3. **Query decomposition** — "Can I get financial aid as an international
   student?" → two retrievals (international eligibility, aid requirements),
   union the results. **This is the cross-silo thesis operationalized**: no
   single chunk answers a genuinely cross-silo question, so no amount of
   reranking a single query will find one. Highest-value model-based step here.
4. **Multi-query expansion** — 3 paraphrases, retrieve each, RRF-fuse. Attacks
   the vocabulary gap: students say "money for school," the site says
   "institutional aid."
5. **Conversational de-contextualization** — "what about for international
   students?" → standalone question. Mandatory for multi-turn.
6. **Step-back prompting** — generate a broader question alongside the narrow
   one when the specific query hits nothing.
7. **HyDE** — embed a hypothetical generated answer rather than the question.
   Evidence is mixed; treat as a test, not an assumption.

⚠️ **Steps 3–7 each cost a cloud LLM call**, at one-request-at-a-time (§2a).
Decomposition or multi-query roughly **doubles per-query quota and latency**.
Reformulation is therefore the one place where generation quota is spent to buy
*retrieval* quality, and it must be justified on the §4b quality/cost frontier
rather than on recall alone. Steps 1–2 cost nothing — exhaust them first.

### 4a. Running Phase 4 against a metered backend

Every generation call now costs quota against an undocumented cap (§2a). The
naive execution — ~150 questions × ~10 generation-touching configs ≈ 1,500
calls in a burst — will hit a wall, and **a partially-completed ablation is not
a slow result, it is a void one**: config A complete and config B dead at
question 87 are not comparable. Four mitigations, in order of leverage:

1. **Ablations #1–#5 and #7 cost zero LLM calls.** Boilerplate, chunking,
   retrieval mode, reranker, `k`, and silo routing are scored purely as set
   arithmetic against gold URLs (§2b). That is the majority of the science and
   the largest effect sizes, entirely quota-free. Finish all of it, freeze
   retrieval, and only then spend a single token on generation.
2. **Checkpointed, resumable runs — the architectural fix.** Cache every
   generation keyed on `(model, digest, prompt_hash)`; append to
   `per_query.jsonl` incrementally; resume from the last completed question on
   restart. This converts a quota wall from a void run into a **pause**, and it
   makes re-running an unchanged config free. Build this before the first
   sweep, not after the first wall.
3. **The abstention sweep (#9) barely needs generation.** If refusal triggers
   on *top rerank score < τ*, the refusal decision is computable entirely from
   retrieval scores already on disk. Sweep τ across the full gold set for free;
   generate once for the queries passing the loosest τ and reuse those outputs
   at every threshold. Only *model-initiated* refusals ("context insufficient")
   require a real pass — measure those separately, since they are a second and
   independent refusal pathway.
4. **Generation ablations run on the dev split, never the full set.** Dev is
   ~60 questions against ~300 total (Phase 2), so this is both the correct
   methodology *and* a ~5× quota reduction — the split discipline and the quota
   constraint happen to want the same thing. Test is spent once, at the end, on
   the frozen configuration. Report n alongside every metric.

**Calibrate before committing.** No RPM/TPM caps are published, so run ~20
questions through `gpt-oss:20b-cloud` in Phase 0 and record `eval_duration` per
query. That converts directly into "full gold-set passes affordable per weekly
reset," which is the number that decides whether mitigation #4 is sufficient or
whether the generation subset has to shrink further. Discovering this in Phase 0
is free; discovering it mid-sweep in Phase 4 costs a week.

**Metrics**

- *Retrieval:* recall@k, MRR, nDCG against gold URLs — **plus
  all-golds-retrieved@k on conjunctive (cross-silo) questions**, where partial
  recall is worth zero. Primary metric chosen empirically in Phase 3b
- *Generation:* see §4d — scored by a validated ladder, not a single judge
- *Abstention:* correct-refusal rate, false-refusal rate — τ calibration, §4e
- *Ops:* see §4b — latency and cost are the same measurement here

**Answer-quality rubric** (used in 3b, in the ladder's human tier, and in the
Ask Scottie comparison — one rubric everywhere, or the numbers aren't comparable):

| Score | Meaning |
|---|---|
| **2** | Correct **and** grounded — every factual claim is supported by a cited retrieved chunk |
| **1** | Substantially correct but flawed — missing a required part of a conjunctive answer, an uncited claim, or a correct answer citing the wrong source |
| **0** | Wrong, unsupported, or a hallucinated specific (deadline, dollar figure, policy) |
| **R** | Refused — scored separately as correct/false refusal, never folded into 0-2 |

A correct answer that cites nothing scores **1, not 2**: ungrounded correctness
is the failure mode §3b warns about, and collapsing it into "correct" hides it.

### 4d. Who scores generation quality

There is no frontier judge available and quota is metered, so build a **ladder
and validate upward** rather than picking one method. `gpt-oss:20b` must never
grade its own output.

| Tier | Method | Cost | Measures |
|---|---|---|---|
| **0** | Deterministic | free | Citation accuracy (cited URL ∈ gold?), citation validity (chunk exists and was retrieved?), refusal correctness, exact-match presence (regex: course codes, dollar figures) |
| **1** | Local NLI | free | Faithfulness — split answer into sentences, run a DeBERTa-class entailment model over retrieved context, score proportion entailed. Same tool class as the reranker, runs under `sentence-transformers` |
| **2** | Human | time | Hand-score 0/1/2. Gold standard. Feasible at n=25 (3b) and n≈120 (final test); not across every ablation |
| **3** | LLM judge | quota | A **different** free-tier model (Gemma 4 / Nemotron). ⚠️ **temperature 0 mandatory** — same-verdict consistency is >95% at temp 0 and falls to ~70% at temp 1 |

**Tier 0 does more work than it looks.** Published RAG citation accuracy runs
only 65–70% without attribution training, so it discriminates between configs.

**The rule that makes Tier 3 legitimate:** hand-score a calibration set first,
measure judge-human agreement (Cohen's κ or correlation) on it, use the judge
only where agreement is acceptable, and **report that agreement number in the
writeup**. An uncalibrated judge is worse than no judge — judge quality tracks
training strategy, not parameter count, so size is no guarantee.

**Production workflow: two scorers, human on disagreement only.**

```
Tier 1 NLI  ─┐
             ├─ agree ──> accept label
Tier 3 judge ┘
             └─ disagree ──> human adjudicates
```

Disagreement is an uncertainty signal, so human effort concentrates on hard
cases instead of spreading evenly across easy ones. The **inter-scorer agreement
rate is itself a reportable quality number**, and it costs nothing extra.

⚠️ **Have the pipeline propose a label and let the human accept or correct it**,
never score from a blank slate. Reviewing a proposed judgment is several times
faster than producing one — that is the difference between human oversight being
feasible across ablations and being abandoned after the first one.

### 4e. Calibrating τ

τ is the abstention threshold: if the best rerank score is below τ, refuse and
route to the owning office rather than generate. Raising τ refuses more (safer,
but false refusals make the bot useless); lowering it covers more (and invites
confident nonsense). Sweeping τ traces the correct/false-refusal tradeoff curve.

⚠️ **Open problem: cross-encoder scores are not calibrated across queries.** A
0.6 on one question does not mean what 0.6 means on another, so a single global
τ may be meaningless. Three candidates to test — the sweep is free (§4a #3), so
test all three:

1. **Per-query normalisation** of the score distribution.
2. **Margin-based** — use `top1 − top2` instead of an absolute score. Robust to
   per-query scale shifts.
3. **Percentile-based** — threshold on rank position within the query's own
   score distribution.

**Choosing a cutoff: state the operating point, then read τ off the curve.**
"Sweep τ and pick a good spot" has no decision rule. Specify the requirement
instead:

> *Of the questions we choose to answer, **≥95% must be correct**. Subject to
> that, maximise coverage.*

τ is then not a taste judgment but the largest coverage achievable at a stated
precision floor — how safety-critical systems are actually specified, and
defensible in the writeup. (Alternative framing: weight the asymmetry explicitly
and minimise `w·wrong + false_refusal`. Same curve, but it requires inventing a
ratio; prefer the precision floor.)

**Abstention is not only a threshold.** Six mechanisms, not mutually exclusive:

| Mechanism | Cost | Notes |
|---|---|---|
| Score threshold τ | free | The calibration problem above |
| Margin / percentile / normalised | free | Fixes calibration; still purely retrieval-side |
| **NLI entailment gate** | free, local | Does retrieved context entail an answer? Reuses the §4d Tier-1 model. Deterministic, no quota |
| **LLM answerability judge** | 1 cheap call | "Is there sufficient evidence? yes/no", constrained output |
| Self-abstention in prompt | free | Already tracked as model-initiated refusal. Unreliable alone |
| Logprob confidence | free if exposed | Check whether Ollama returns logprobs |

**Recommended architecture: triage, not a single mechanism.** Use two
thresholds, τ_low and τ_high:

```
score ≥ τ_high  ──> answer            (free, the easy majority)
score <  τ_low  ──> refuse + route    (free)
τ_low..τ_high   ──> LLM answerability judge   (paid, uncertain band only)
```

Intelligence is spent only where it is needed, which matters under metered
quota — and it yields a real finding for the writeup: **what fraction of queries
land in the uncertain band, and does the LLM gate beat a threshold there
specifically.**

**Precedence when mechanisms disagree.** Three pathways can fire independently,
so the resolution rule must be explicit rather than emergent:

> **Any refusal signal wins.** If the threshold, the answerability gate, or the
> model itself declines, the system refuses and routes.

Rationale: the domain asymmetry (a wrong aid/visa answer harms a student; a
routed refusal costs little) makes the conservative disjunction correct. Log
**all three signals** plus the resolved winner (§5) — otherwise a disagreement
rate that is itself a finding becomes invisible.

Report which calibration method was chosen and why; this is a finding, not a
config detail.

### 4b. Measuring latency and cost

**Cost is GPU-seconds, not dollars.** Ollama Cloud meters GPU time, so there is
no dollar figure to record and **latency and cost collapse into one
measurement**. Any latency win is directly a quota win. Two traps:

- **Reasoning tokens are a hidden multiplier.** `gpt-oss:20b` generates
  chain-of-thought that is discarded before display but costs real GPU time.
  Logging only visible answer length understates cost — by the largest margin
  on hard questions, i.e. exactly the cross-silo slice this project exists to
  serve. Log reasoning tokens as their own field.
- **~~Use server-side durations, not client wall-clock.~~ Measured false for
  this model (Task 3, 2026-09-10).** The claim was that Ollama returns
  `total_duration`, `prompt_eval_duration`, `eval_duration`, `prompt_eval_count`
  and `eval_count` in nanoseconds on the final chunk, for cloud models too. What
  `gpt-oss:20b-cloud` actually returns:
  - OpenAI-compatible `/v1/chat/completions`: token counts only, and only when
    `stream_options: {include_usage: true}` is sent. **No durations at all.**
  - Native `/api/chat`: `total_duration`, `prompt_eval_count`, `eval_count`.
    **No `prompt_eval_duration`, no `eval_duration`.**

  So the app uses the OpenAI-compatible surface and **client wall-clock is the
  cost measure**, recorded as `timing_source` on every `Usage` so no reader has
  to assume it. Wall-clock includes queueing behind the free tier's single
  concurrency slot, making it an upper bound on GPU time — conservative, which
  is the right direction for a budget to err in. Probed head to head,
  `total_duration` ran about 0.2s under wall-clock on calls of 1.3-2.1s.
  Evidence: `docs/quota-calibration.md`, `runs/*/native_probe.json`.
- **⚠️ Trust durations over counts — not an option here.** `prompt_eval_count`
  reports the *total context size sent*, not GPU work actually performed: a
  cached prompt prefix still counts in full, so it **overstates burn on every
  query reusing a cached system prompt**. `prompt_eval_duration` would be the
  honest number, and this endpoint does not report it. Nothing separates prompt
  processing from generation, so an arm that inflates the prompt and an arm that
  inflates the answer are indistinguishable on cost. Report counts and seconds
  side by side; present neither as GPU time.

**Decompose latency per stage** — the total is not actionable:

| Stage | Where | Expectation |
|---|---|---|
| Query embed | local | 5–20ms |
| Dense ANN + BM25 | local | 1–10ms each at ~3k chunks |
| Rerank (50 pairs) | local | 100ms–1s — the only local stage that can get slow; scales with `k` (#5) |
| **Generation** | **cloud** | **seconds — expect >90% of total** |

Measure the local stages anyway, to *prove* the cloud call dominates rather
than assume it.

- **TTFT vs total.** With SSE, time-to-first-token is what users perceive — and
  a reasoning model's TTFT is the *entire* thinking phase. Track both.
- **Cold vs warm.** Free-tier cold starts corrupt p50/p95 if mixed in. Tag each
  call and report the distributions separately.

**The payoff: the results table becomes a quality/cost Pareto frontier.** With
cost logged next to quality on every run, ablations stop reading as "more is
better" and start showing *where more context stops paying for itself*. That
knee is a stronger portfolio artifact than a quality-only leaderboard, and
under metered quota it decides what is actually affordable to serve.

### 4f. Analysis plan — decided before Phase 4, not after

Without this section the ablation table is a leaderboard of noise. It is written
now, and locked at Checkpoint D, so that Phase 4 is confirmatory rather than a
search for a story.

**The unit of analysis is the question, and every comparison is paired.** Each
config is scored on the *same* gold questions, so question difficulty is a
blocking factor and must be removed from the error term rather than left in it.
Unpaired comparisons here would be strictly worse for no reason.

| Outcome type | Test |
|---|---|
| Binary per question — hit/miss, all-golds-retrieved, correct refusal | **Exact McNemar** on discordant pairs |
| Graded — nDCG, MRR, the 0/1/2 rubric | **Paired bootstrap** over questions, 10k resamples, seeded |
| Cost — GPU-seconds, latency | Paired bootstrap on the median; **never the mean** (cold starts skew it) |

**⚠️ The design is underpowered at the slice level, and that is a stated
limitation, not a fixable one.** Detectable effect at 80% power, α=0.05, paired:

| Comparison | n | Minimum detectable effect |
|---|---|---|
| Pooled test set | 120 | **~12 points** |
| Dev (all ablation selection happens here) | 60 | ~16 points |
| Cross-silo test slice | 28 | ~20 points |
| Out-of-scope test slice | 24 | ~21 points |

By simulation of the exact test, 3k replicates, assuming ~20% of questions land
discordant between the two configs. A config pair that disagrees *more* often
needs a larger effect, not a smaller one: at 30% discordance the pooled figure
rises to ~15 points and the cross-silo slice to ~28. Reproduce with
`scripts/mde.py`; the normal approximation understates all of these by roughly a
point and should not be used.

**Growing the gold set does not rescue this.** Doubling the cross-silo slice to
48 test items moves its detectable effect only from ~20 to ~16 points. Slice-level
significance is out of reach at any corpus-authoring effort that is realistic
here, so the plan does not pretend otherwise. Two consequences, both binding:

1. **Slice-level results are reported as effect size + 95% CI and described, with
   no significance test attached.** A wide interval is the honest output and is
   reported as such. No p-values appear next to a slice.
2. **Significance claims are confined to the pooled test set**, and realistically
   only to effects large enough to clear ~12 points. Boilerplate stripping (#1)
   is expected to; most others are not, and saying so in advance is what makes
   the eventual "no significant difference" a *result* rather than a failure.

**Dev is selection, not inference.** No p-value computed on dev appears in the
writeup. Dev exists to rank configs and pick one; ranking does not need a
hypothesis test and reporting one would invite a multiplicity correction for a
question nobody is asking. The only inferential pass is the single test-split
run on the frozen config, which keeps the comparison count small enough that
multiplicity is handled by pre-specification rather than by α-adjustment.

**Pre-specify, in `decisions/`, before the first Phase 4 run:**

- The primary retrieval metric, chosen empirically in Phase 3b (§3) and **frozen
  at Checkpoint D**. Choosing it after seeing Phase 4 results is the exact
  garden-of-forking-paths failure this whole structure exists to prevent.
- The primary generation metric and the primary abstention metric.
- The specific comparisons the test split will be spent on. Write the list down;
  anything not on it is exploratory and labelled exploratory.
- The τ operating point (§4e), which is already stated as ≥95% precision.

**Every reported number carries n and a 95% CI.** Bootstrap, seeded, over
questions. A number without an interval is not reportable — and given the MDEs
above, the intervals *are* the finding for most of the table.
### Phase 5 — Product backend. The UI is deliberately deferred

**The deliverable of this phase is an API, not an interface.** The front end is
undecided — embeddable widget on another site, standalone site, or something
else — and that decision does not need to be made now. It only stays deferrable
if the backend is built so that **no client is privileged**: nothing in the
service knows or cares what renders it.

That is a design constraint, not a note. It costs almost nothing to honor up
front and is expensive to retrofit.

**The stream contract is the product surface.** One endpoint, Server-Sent
Events, typed events rather than raw text:

```jsonc
POST /ask  { "question": "...", "history": [...], "session_id": "..." }

event: sources    { "chunks": [{"title","url","silo","heading_path",
                                "rerank_score","last_verified"}] }
event: token      { "text": "..." }
event: citation   { "claim_span": [104, 168], "source_url": "...", "chunk_id": "..." }
event: refusal    { "reason": "low_confidence", "office": "Financial Aid",
                    "contact_url": "...", "email": "..." }
event: done       { "latency_ms": {...}, "server_ns": {...}, "refused": false }
```

**`sources` is emitted at rerank time, before generation starts.** This is the
single most important line in the contract. `gpt-oss:20b` thinks before it
writes, so time-to-first-visible-token is the entire reasoning phase — 10s+ of
blank screen (§4b). Emitting sources early lets *any* client fill that gap with
the trust surface instead of a spinner. A widget, a full site and a terminal
client all get that behavior for free because it lives in the protocol rather
than in a UI.

`citation` carries character spans into the answer text so a client can render
inline links without re-parsing prose. `refusal` carries the routing target as
structured fields, so a client is never parsing an apology to find an email.

**What Phase 5 builds:**

- **Service layer** — a plain callable, `answer(question, history) -> events`,
  with no web framework in it. Importable from a script, a test, or a notebook.
  This is what makes the API a thin shell and the UI genuinely optional.
- **FastAPI + SSE shell** over that callable. Thin by construction.
- **Event schema, versioned and documented.** It is a public contract the moment
  a second client exists.
- **CORS + a simple API token.** Cheap now, and it is the difference between the
  widget-on-another-site option being available later or being a rewrite.
- Conversation memory and follow-up rewriting, behind the same callable.
- Refusal routing against the contact table from §2c.
- Freshness fields on every source: `last_verified`, staleness flag.

**What Phase 5 does not build: a UI.** A ~40-line reference HTML client ships
alongside, whose only job is to prove the stream works and to demo. It is a test
fixture, not a product, and it is explicitly disposable. When the front end is
decided, it is a new client against a frozen contract.

*If Streamlit or Gradio ever comes up again:* citation rendering is the trust
mechanism and the centerpiece of this product, and that is exactly what those
frameworks fight you on. This is also now moot — they would be one more client
of the same API.

**Public-upscale checklist (write once, ship later):** unofficial-disclaimer
banner, rate limiting on the public endpoint, and a cost ceiling / kill switch
on the generation call — a public link with an unmetered cloud call behind it is
the one way this project's budget problem becomes a real bill overnight. Public
deployment remains a possible later upscale, not a Phase 5 goal (§7).

### Phase 6 — Portfolio polish

README with the architecture diagram, the v0 → vN results table, honest
limitations, **a recorded demo walkthrough** (not a live deploy — Phase 5 is
local-only unless the public-upscale checklist is completed), and a short
writeup of what actually moved the numbers. **The ablation table is the
portfolio piece** — anyone can wire up a RAG demo; almost nobody shows their
control condition and their failure modes.

**Limitations section is not optional.** State plainly, without burying:
self-authored eval set; author-is-designer blind spots; comparator measured
qualitatively while the system is measured rigorously; cloud runs are
attributable but not reproducible; abstention reported against one named model.

---

### Phase 7 — Maintenance. Built once, then left running

**The premise of this phase: development ends, the college's website does not.**
Every failure below is silent by construction — the bot keeps answering fluently
while its answers quietly stop being true. None of them announce themselves, so
each one needs a scheduled check that fails *loudly* or it will not be noticed
until a student is given a wrong deadline.

Design constraint: **this is not an ops practice, it is a cron job and four
alerts.** A maintenance plan that assumes ongoing attention will not survive
contact with a personal project. Everything here either runs unattended or
does not exist.

**The four decay modes, and what catches each:**

| What decays | How it fails silently | The check | Cadence |
|---|---|---|---|
| **Corpus content** | College edits a page; index still serves the old text with a confident citation | Content-hash diff → incremental reindex (§2e, T10) | Weekly |
| **Extraction** | Site reskin turns `trafilatura` output into nav chrome or empty strings; recall degrades for weeks | Snapshot regression test over the ~20 pinned pages (§2e, T6) | Every crawl |
| **Corpus shape** | Pages disappear, sections get restructured, new silos appear with no owner | Manifest diff between crawls — new URLs, new 404s, `other`-rate drift (§1) | Every crawl |
| **The gold set** | A question's source page is rewritten, so the labeled gold ref is now wrong and every metric computed against it is quietly invalid | Gold refs pinned to `content_hash`; **a changed hash flags the question stale** | Every crawl |

**Gold-set decay is the one that is easy to miss and hardest to recover from.**
The other three degrade the product; this one degrades the *measurements*, which
means it can invalidate the portfolio artifact without touching the demo. Pin
every gold ref to the content hash it was authored against. When the hash moves,
the question is flagged stale and excluded from reported metrics until a human
re-reads the page and either re-confirms or re-labels it. **A stale-flagged
question is never silently dropped** — the count of stale questions is itself
reported, because a metric computed on a shrinking denominator is a different
metric.

**The alert surface, deliberately tiny.** Four conditions, all of which mean
"stop and look," none of which fire in normal operation:

1. Extraction snapshot test fails on any pinned page.
2. `other` silo rate crosses its threshold, meaning the IA moved under the mapper.
3. More than a threshold fraction of gold questions go stale in one crawl,
   meaning a site-wide restructure rather than ordinary editing.
4. The generation backend returns errors or the free tier's terms change.

**What is explicitly *not* here:** no dashboards, no uptime SLO, no on-call, no
retraining loop. There is no model being trained, and a local demo has no uptime
to protect. Adding those would be building an operations practice for a project
that does not have one.

**Re-running the experiments is a decision, not a schedule.** Metrics drift as
the corpus drifts, and that is expected rather than alarming. Re-run the frozen
config against the current corpus **only** when the corpus has changed enough to
make the published numbers misleading — a reasonable trigger is >10% of pages
changed since `corpus.lock`, or any alert above firing. When that happens, the
old numbers are not deleted; a new dated row is added and the corpus hash beside
it explains the difference. That is exactly what `corpus.lock` was built for.

**Triggers for the deferred work in *Future*.** These are currently a wishlist,
which is why they never happen. Each gets a condition instead:

| Deferred item | Do it when |
|---|---|
| Spanish translate-in layer | A real Spanish-speaking user asks, **and** a Spanish gold set can be authored — without the eval it is an unmeasurable feature |
| News as a separate index | "What's happening on campus" becomes a target query class, i.e. it shows up in real usage |
| Multi-turn beyond the ~15-question slice | The Phase 5 multi-turn result is good enough to be worth extending, and bad enough to need it |
| A second institution | Never on this corpus. It is a rewrite of §1 and §2c, not a config change — say so rather than implying the pipeline generalises for free |
---

## 4. Beating the baseline

**Optional and opportunistic — nothing depends on this.** Ask Scottie is a
vendor widget with no API, outside our control, and not reliably accessible.
The three claims in §0 are all measurable without it, which is deliberate: a
project whose headline rests on beating an inaccessible black box is one
outage away from having no result.

If it happens to be working at Phase 6, run ~30 queries, tabulate, and report
it **as an anecdote with its limitations stated** — never as the headline.
Two rules if you do:

1. **Draw the queries from the *test* split and count it as part of the single
   permitted test access** (Phase 2). Dev would compare on tuned data; ad-hoc
   selection is unblinded cherry-picking.
2. **Same rubric, same scorer, blind to source where practical.** Record
   refusals as refusals — a widget correctly declining an out-of-scope question
   is right, and scoring that as a win would be dishonest.

---

## 5. Experiment log format

```
runs/2026-09-01T14-22_a3f9c1/
  config.yaml       # full pipeline config — the ONLY thing that varies
  metrics.json      # aggregate metrics
  per_query.jsonl   # one record per question — schema below
  corpus.lock       # corpus snapshot hash — pins what was indexed
  model.lock        # backend + model tag + digest + sampling params
  split.lock        # gold-set split hash + which split this run scored
  notes.md          # hypothesis, result, decision
```

**`per_query.jsonl` record** — written incrementally so a quota wall leaves a
resumable partial run rather than nothing (§4a #2):

```jsonc
{
  "qid": "xsilo-014", "slice": "cross_silo", "split": "dev",
  "question": "...", "rewritten_query": "...",
  "retrieved": [{"chunk_id": "...", "source_url": "...", "dense_rank": 3,
                 "bm25_rank": 11, "rrf_score": 0.031, "rerank_score": 0.87}],
  "gold_refs": ["..."], "conjunctive": true,       // heading/chunk level, not page
  "answer": "...", "citations": ["..."],
  "refused": false,
  "refusal_signals": {"threshold": false, "gate": null, "model": false},
  "refusal_source": null,        // resolved winner, per the precedence rule
  "tokens": {"prompt": 3412, "reasoning": 890, "completion": 214},
  "latency_ms": {"embed": 12, "dense": 3, "bm25": 6, "rerank": 340,
                 "generate_ttft": 8100, "generate_total": 11200, "e2e": 11570},
  "server_ns": {"total": 11040000000, "prompt_eval": 1210000000,
                "eval": 9830000000},              // authoritative cost signal
  "cold_start": false
}
```

`reasoning` tokens are separated from `completion` deliberately — they are
invisible to the user and are the largest single source of cost
underestimation. `refusal_source` distinguishes the two independent abstention
pathways, which is what makes the §4a #3 threshold sweep computable offline.

**`model.lock` exists for the same reason `corpus.lock` does.** Pinning the
corpus makes a metric change attributable to the pipeline rather than to the
college editing a page — but nothing was pinning the *model*, and a hosted
endpoint can silently update the weights behind a tag like `gpt-oss:20b`. That
reintroduces exactly the unattributable-drift problem the corpus lock was
invented to kill. Record backend (`local` / `ollama-cloud`), model tag, the
digest Ollama reports (`ollama show --modelfile`), `num_ctx`, and temperature
and seed. For local runs pin a fixed seed.

⚠️ **Be honest about what this buys: attributability, not reproducibility.**
Cloud weights behind a tag can change and you cannot roll them back, so a run
against `gpt-oss:20b-cloud` is not re-runnable in the strict sense. `model.lock`
guarantees you will *know* the model changed and can quarantine affected runs —
it does not let you reproduce them. Claim the former in the writeup, not the
latter. Only the local escape-hatch path is reproducible end to end.

Run id = timestamp + config hash. `RESULTS.md` is regenerated from `runs/` as a
leaderboard. No MLflow — the overhead is not justified at this scale, and plain
files stay diffable and reviewable in the repo.

The rule that makes it science: **`corpus.lock` pins the corpus snapshot.**
A metric change is otherwise unattributable — you will never know whether the
reranker helped or the college edited a page.

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| Site changes mid-project, metrics drift | `corpus.lock` per run; snapshot store |
| Self-authored eval set biased toward what I know | State as a limitation; include adversarial slice. **Splits do not fix this** — it is a distributional problem, not an overfitting one |
| Hyperparameters (esp. abstention τ) tuned and reported on the same questions | 40/20/40 stratified split; test touched once and every access logged; `split.lock` per run |
| SmartCatalog terms may restrict ingestion | Check before Phase 1; site pages alone are a viable fallback |
| Confidently wrong answer on high-stakes aid/visa info | Abstention tuning + forced citations + office routing |
| Appearing to be an official college service | Explicit unofficial disclaimer; no college branding |
| Scope creep into a full agent | Ship the RAG pipeline first; agentic routing is an unscheduled *maybe*, deliberately given no phase number |
| Running up an API bill with no institutional budget | Generation is on a **free tier**, not local (§2a) — no card on file, so the failure mode is quota exhaustion, not a bill. Re-check this row if the scale path ever swaps `base_url` to a paid endpoint |
| `gpt-oss:20b` abstains worse than a frontier model, deflating the headline metric | Model choice is ablation #10; report abstention against a *named* model rather than implying a general result, and state the ceiling honestly |
| Incumbent comparison is unavailable or changes mid-project | **Structurally removed** — §0's three claims are all measurable standalone; the Ask Scottie comparison is opportunistic and reported as an anecdote (§4) |
| **Eval blind spots mirror architecture blind spots** — the author is also the designer, so question types the system handles badly may never get written | Write questions *before* seeing retrieval results; consider having a second person write a subset; report as a limitation distinct from self-authorship |
| Ollama Cloud free quota exhausts mid-experiment, voiding a run | Resumable checkpointed runs + per-query generation cache (§4a #2) turn a wall into a pause; retrieval ablations need no quota at all; local `gpt-oss:20b` with expert offload is the documented escape hatch |
| Cloud dependency makes the whole project unrunnable if the free tier changes | Backend is a `base_url` config string (§2a) — swapping to local Ollama, vLLM, or another OpenAI-compatible host is a config edit, not a rewrite |
| Hosted model silently updated → metrics drift with no code change | `model.lock` per run (§5) records backend, tag, digest and sampling params |
| Corpus gaps are invisible — a gold question has no supporting chunk and nobody can tell whether the page was never fetched, extracted empty, or simply not retrieved | Crawl manifest records **every URL considered** with a class-prefixed reason for every omission (§1). The three cases separate in one grep |
| UI decisions leak into the backend, so the front end cannot be swapped later | Phase 5 freezes the stream contract before the code and asserts no web-framework import in the service module. The reference client is explicitly disposable |
| A named silo turns out to have no office behind it, so refusals route nowhere | Discovery step 3 makes an office match the *promotion criterion* (§2c) — a silo without a contact row folds or is marked ownerless |
| Self-authored gold set has no ground truth against real student phrasing | No insider data available (§7); write the adversarial/leading slice deliberately harder to partially compensate, and say so plainly in the portfolio writeup as a limitation, not a caveat buried in a footnote |
| Retrieved passages are unreviewed scraped web text; instruction-shaped page content is indistinguishable from a real instruction in a flat prompt | `<passages>`/`<question>` delimiters + explicit system-prompt clause (`mcrag/generate/prompting.py`, found and fixed during Task 16) |
| A live user turn (Task 24 onward, the first point real adversarial input exists) attempts to override the system prompt, extract it, or jailbreak the persona | Task 24's persona/system prompt explicitly instructs the model to ignore in-conversation override attempts; dedicated injection test cases, separate from the false-premise adversarial gold slice |

---

## 7. Open questions — resolved 2026-09-02

1. **Deployed publicly, or a local demo?** → **Local demo first.** Public
   deployment is a possible later upscale, not a Phase 5 goal. See the
   public-upscale checklist in Phase 5 — built once, shipped only if/when this
   goes public.
2. **Any budget for API calls?** → **None — free tiers only.** Generation runs
   on `gpt-oss:20b` via the Ollama Cloud free tier over an OpenAI-compatible
   endpoint; the 131M of embedding + reranking models stay local because Ollama
   hosts neither (§2a). Quota is metered by GPU time with undocumented caps, so
   Phase 4 execution is explicitly designed around it (§4a).
3. **Insider knowledge of what students actually ask?** → **None.** The gold
   eval set is entirely self-authored (already flagged as a stated limitation
   in §2 and §6) — no change to Phase 2's approach, just confirmation there's
   no shortcut here.

---

## References

- URAG: Unified Hybrid RAG for university admission chatbots (HCMUT) — arXiv 2501.16276
- Marcel: lightweight open-source conversational agent for university student support — arXiv 2507.13937
- LLM-based RAG pipelines for international student admissions — MDPI Electronics 14(15):3095
- Retrieval-augmented generation for educational application: a systematic survey — ScienceDirect
- AI chatbots in higher education: comparing expectations to evidence — ScienceDirect
- Benchmarking RAG frameworks for educational chatbots — arXiv 2503.00781
- RAGBench: explainable benchmark for RAG systems — arXiv 2407.11005
- MoR: Better Handling Diverse Queries with a Mixture of Sparse, Dense, and
  Human Retrievers — arXiv 2506.15862 (EMNLP 2025)

## Future

- **Add Spanish support — as a translation layer, not a multilingual index.**
  This is the right call and it **removes** the conflict with `bge-base-en-v1.5`
  rather than creating one. The corpus is English (the college publishes in
  English), so the index should stay English; a multilingual embedder would only
  exist to bridge a gap that translation closes more cheaply.

  ```
  Spanish query ──translate──> English query ──> [entire existing pipeline]
                                                          │
  Spanish answer <──────── generate in user's language ────┘
                           (English context, Spanish output — one call)
  ```

  Three notes for whenever this becomes real:
  - **One extra call, not two.** Translate the query *in* (required — the
    embedder cannot match Spanish to English chunks), but do **not** translate
    the answer *out*; instruct the generator to answer in the user's language
    directly from English context. Avoids compounding translation error on the
    output side.
  - **Citations stay pointed at the English pages.** That is correct, not a
    defect — those pages are the authoritative source, and a student may need to
    show them to an office.
  - **The acronym dictionary (§4c step 1) already does half the work.** `I-20`,
    `FAFSA`, `SEVIS` must survive translation untouched; that normalisation
    layer is the natural place to enforce it.

  Evaluating it would need a Spanish gold set. Out of scope for v1 — the point
  here is only that **no decision made now forecloses it.**
- Multi-turn conversation beyond the ~15-question slice.
- News as a separate, clearly-labelled index (§1).
- **Program-requirement lists and admissions statistics (acceptance rate,
  retention/graduation rate, class-size figures beyond the college-wide
  averages).** These are real, published data — the requirement lists live on
  the robots-disallowed `smart_catalog_prog` pages (decision 0001), and
  admissions/outcome statistics likely exist in a source this project hasn't
  ingested (e.g. the college's Common Data Set, an external document, not part
  of `maryvillecollege.edu`'s own crawlable pages). Both are correctly
  `out_of_scope` for v1's corpus, not a mapper or extraction defect — Task 13's
  gold set deliberately tests that the bot refuses these rather than
  hallucinating a number. Filling the gap later means adding a new,
  separately-scoped ingestion source (with its own robots/terms check per
  decision 0001's discipline for the catalog), not stretching the current
  crawl scope to cover it.
