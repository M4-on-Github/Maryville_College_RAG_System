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
- [x] T5 · Polite fetcher + raw snapshot store (M) — code + tests done; **full live crawl launched 2026-09-10, running in background** (`runs/full_crawl.log`)
- [x] T6 · Extraction + regression snapshot test (M) — + corpus-level boilerplate filter; breadcrumbs come from the site's JSON-LD
- [ ] T7 · SmartCatalogIQ nav-tree adapter + terms check (M) — needs the full crawl to finish
- [ ] T8 · **Silo discovery + mapper + contact-routing table** (M) — absorbs former T8b; routing table gains a referral destination column (decision 0002); needs the full crawl to finish
- [ ] ~~T8b · Office contact-routing table~~ — **merged into T8.** It is a byproduct of discovery step 3, not follow-on work
- [x] T9 · Heading-aware chunker + metadata stamping (M) — built as paragraph-boundary chunking, not heading-boundary (measured heading sparsity, see `tasks/plan.md`); `silo` stamps `()` until T8 runs
- [ ] T10 · Incremental reindex (M)
- [ ] T11 · Build dense + BM25 + literal indexes (M)
- [ ] **Checkpoint B** — corpus indexed, chunks reviewed, coverage reconciled

## Phase 2 — Gold set
- [ ] T12 · Gold-set schema + split tooling (M) — schema carries an expected referral; refusal correctness splits into refused-correctly and routed-correctly (decision 0002)
- [ ] T13 · Author ~300 questions (L — split by slice, incl. the ~15 multi-turn slice)
- [ ] **Checkpoint C** — dataset validated, split, locked

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
