# TODO — Maryville College RAG

Detail, acceptance criteria and verification steps live in `tasks/plan.md`.
Design rationale lives in `PLAN.md`.

## Phase 0 — Foundations
- [x] T1 · Config schema + run-logging harness (M)
- [x] T2 · Robots enforcement + rate limiter (S)
- [x] T3 · Ollama Cloud smoke test + quota calibration (S) — `docs/quota-calibration.md`; 2.3s/query, no server durations, silent truncation confirmed
- [ ] ~~T0 · Verify the Ask Scottie premise~~ — **dropped.** Incumbent demoted to background (§0); the three project claims are measurable standalone
- [x] **Checkpoint A** — harness, robots, written quota budget — human review cleared 2026-09-10: catalog gap accepted (handled via decision 0002 referrals), events exclusion kept, go-ahead given for the full crawl

## Phase 1 — Corpus
- [x] T4 · Sitemap parser → **crawl manifest** (M) — one record per URL *considered*, reason on every omission
- [x] T5 · Polite fetcher + raw snapshot store (M) — code + tests done; **full live crawl completed 2026-09-10**, 77.1 min, 2189 changed/new, 210 failed (all one server-side infinite-redirect loop on the staff sitemap, confirmed not a fetcher bug), 0 robots-refused (`runs/full_crawl.log`, `docs/coverage.md` regenerated)
- [x] T6 · Extraction + regression snapshot test (M) — + corpus-level boilerplate filter; breadcrumbs come from the site's JSON-LD; re-run over the full crawl: 2243 snapshots -> 1699 documents (fixed a redirect-fan-in dedup bug under T10/T11 that had inflated this to 1847; see `tasks/plan.md` T11 note)
- [x] T7 · ~~SmartCatalogIQ nav-tree adapter + terms check~~ **Catalog coverage assessment** (M) — decision 0001 already showed there's no separate host/nav-tree to crawl; verified course-level substitute (763/772 course pages extracted, 98.8%) and confirmed the program-requirements gap is real (program pages carry overviews, not requirement lists), see `tasks/plan.md`
- [x] T8 · **Silo discovery + mapper + contact-routing table** (M) — absorbs former T8b; routing table gains a referral destination column (decision 0002); all 4 steps done. Human reviewed `data/office_candidates.csv` (decision 0002's hand-check), then `data/silos.yaml` (26 silos) + `data/offices.yaml` (routing table) were built from the reviewed candidates plus 7 more real office contacts found by full-corpus search where the original top-5-shortest-page heuristic missed them (admissions, finaid, title_ix, giving, families, event_operations, orientation) — see `decisions/0003-silo-taxonomy.md`. `other` rate 10.3%, explained (79/175 are ownerless `/news/*`, residual 5.6%). `scripts/map_silos.py` stamped real silo labels onto the corpus; `mcrag/silo_mapper.py`; `tests/test_silo_mapper.py` (6), `tests/test_offices.py` (4)
- [ ] ~~T8b · Office contact-routing table~~ — **merged into T8.** It is a byproduct of discovery step 3, not follow-on work
- [x] T9 · Heading-aware chunker + metadata stamping (M) — built as paragraph-boundary chunking, not heading-boundary (measured heading sparsity, see `tasks/plan.md`); re-validated against the full corpus (3237 chunks over the corrected 1699-document corpus, max 509 tokens, 0 violations); `silo` now carries real labels from T8, re-chunked and re-indexed after `scripts/map_silos.py` ran
- [x] T10 · Incremental reindex (M) — `mcrag/index_pipeline.py`; content-hash diff, delete-by-source_url then upsert, true no-op on an unchanged corpus, `corpus.lock` snapshot hash; does not depend on T8
- [x] T11 · Build dense + BM25 + literal indexes (M) — `mcrag/retrieval/{dense,bm25,literal}.py` + `embedding_cache.py`; `scripts/chunk_corpus.py` persists `corpus/chunks.jsonl`, `scripts/build_indexes.py` builds `indexes/` for real (LanceDB dense, pickled BM25/literal); did not depend on T8. Caught and fixed a real extraction-pipeline dedup bug (redirect fan-in) along the way — see `tasks/plan.md`
- [x] **Checkpoint B** — corpus indexed, chunks reviewed, coverage reconciled. Human cleared the silo-assignment sample, the referral-link spot-check, and the 20-random-chunks quality review

## Phase 2 — Gold set
- [x] T12 · Gold-set schema + split tooling (M) — `mcrag/eval/gold.py`, `mcrag.types.GoldQuestion`; schema carries an expected referral; refusal correctness splits into refused-correctly and routed-correctly (decision 0002); did not need T8's final `offices.yaml` to build
- [x] T13 · Author ~300 questions (L — split by slice, incl. the ~15 multi-turn slice) — 300/300, exact slice-target match, `provenance: "synthetic"` (decision 0004); `data/gold/gold_v1.jsonl` + `data/gold/split.lock` (40/20/40 stratified, seed 42); `tests/test_gold_v1.py` (7 tests) guards the committed file. Human 20-question spot-check done, no corrections needed
- [x] **Checkpoint C** — dataset validated, split, locked, human-reviewed

## Phase 3 — Baselines
- [ ] T14 · Retrieval eval harness, zero quota (M)
- [ ] T15 · Phase 3a retrieval baseline (S)
- [ ] T16 · Phase 3b end-to-end sanity check (M) ⚠️ **risk gate**
- [ ] T16b · **Pre-registered analysis plan + stats tooling** (M) ← *written before any Phase 4 run, worthless after*
- [ ] 🚨 **Checkpoint D — GO/NO-GO** — does the retrieval proxy track answer quality?

## Phase 4 — Ablations
- [ ] T17 · Ablation runner, resumable + cached (M)
- [ ] T18 · Free retrieval ablations — **factorial, 32 cells, not OFAT** (L)
- [ ] T19 · Generation scoring ladder (M)
- [ ] T20 · Phase 3c generation baseline (S)
- [ ] T21 · τ calibration study (M)
- [ ] T22 · Metered ablations #6, #8, #9, #10 — **interleaved by question** (L)
- [ ] **Checkpoint E** — freeze config *before* test is ever touched

## Phase 5 — Product backend · **UI deferred by design**
- [ ] T23 · Event schema + stream contract, versioned (S) ← *contract before code*
- [ ] T24 · Answer service callable, **no web framework** (M)
- [ ] T25 · FastAPI + SSE shell, CORS + token (M)
- [ ] T26 · Early `sources` emission + freshness fields (S) ← *fills the TTFT gap*
- [ ] T27 · Refusal path + office routing (M)
- [ ] T28 · Conversation memory + follow-up rewriting (M)
- [ ] T29 · Reference client — **disposable test fixture, not a product** (S)
- [ ] **Checkpoint F** — backend complete, no UI decision made or needed

## Phase 6 — Portfolio
- [ ] T30 · Results table generator from `runs/` (M)
- [ ] T31 · Architecture diagram + README (S)
- [ ] T32 · Limitations + writeup (M)
- [ ] T33 · Recorded demo walkthrough (S)
- [ ] **Checkpoint G** — shipped

## Phase 7 — Maintenance · *a cron job and four alerts*
- [ ] T34 · Scheduled re-crawl + the four alerts (M)
- [ ] T35 · **Gold-set decay** — content-hash pinning, stale accounting (M) ← *the one that corrupts measurements, not the product*
- [ ] T36 · Re-run trigger + result versioning (S)
- [ ] **Checkpoint H** — maintenance mode; nothing needs a human unless an alert fires

*Not in scope: dashboards, uptime SLO, on-call, retraining loop.*

---

**Standing rules**
- Test split is touched **once**, after Checkpoint E. Log every access.
- Free retrieval work finishes before any generation quota is spent.
- No task starts without acceptance criteria from `tasks/plan.md`.
- **Every swappable stage is a class behind an interface.** An ablation arm is a config value, not an edited function.
- **Checkpoints are sprint boundaries.** Each one demonstrates working software or it is not done.
- Done means acceptance criteria met *and* the verification step passing.
- **No client is privileged.** Nothing in the service knows what renders it.
- Every URL the crawler considers gets a manifest record, fetched or not.
- Significance claims live on the pooled test set only. Slices get effect size and a CI.
- Old results rows are never deleted. A re-run adds a dated row.
