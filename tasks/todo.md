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
- [x] T14 · Retrieval eval harness, zero quota (M) — `mcrag/eval/retrieval_metrics.py` (recall@k, MRR, nDCG, all-golds-retrieved@k) + `mcrag/eval/retrieval_harness.py` (gold set -> RunDir, resumable); out_of_scope questions skipped from retrieval scoring (no gold to score against); `tests/test_retrieval_metrics.py` (13), `tests/test_retrieval_harness.py` (5)
- [x] T15 · Phase 3a retrieval baseline (S) — naive fixed-512-tok chunks (`FixedSizeChunker`) dense-only k=5; found and fixed a real bug along the way (exact-chunk-id gold matching scored a flat 0.000 against any differently-chunked index — `mcrag/eval/chunk_alignment.py` content-overlap matching fixes it for this and every future chunk-size ablation); real dev-split numbers: recall@5 0.667, MRR 0.614, nDCG@5 0.587, all-golds-retrieved@5 0.562, **conjunctive breakout 0.071** — naive retrieval essentially never finds both chunks a cross-silo question needs, the project's thesis in its first real number. `RESULTS.md` + committed control-condition run dir (nDCG corrected 0.598→0.587 under T16, see below)
- [x] T16 · Phase 3b end-to-end sanity check (M) ⚠️ **risk gate** — 25 dev questions end-to-end, hand-scored 0/1/2 (`docs/phase3b-sanity-review.md`); found and fixed two real bugs along the way (generator response-encoding mojibake; nDCG>1.0 double-counting in chunk_alignment); **primary metric chosen: `all_golds_retrieved@k`** (`decisions/0005-primary-retrieval-metric.md`) — 76% quadrant agreement, no dangerous low-retrieval/parametric-knowledge cases found; also hardened the shared prompt template (`mcrag/generate/prompting.py`) to delimit untrusted retrieved passages from the user's question before T20 freezes a baseline prompt
- [x] T16b · **Pre-registered analysis plan + stats tooling** (M) ← *written before any Phase 4 run, worthless after* — `decisions/0006-analysis-plan.md`: primary metrics frozen (retrieval `all_golds_retrieved@k`, generation Tier-1 NLI faithfulness, abstention coverage @ ≥95% precision), 10-arm test-split comparison table pre-specified; `mcrag/eval/significance.py` (exact McNemar + seeded paired bootstrap + the dev-split p-value guard), `scripts/mde.py` hardened (no more undeclared scipy/numpy dep, reuses the real test, now covers all 4 PLAN splits)
- [x] 🚨 **Checkpoint D — GO/NO-GO** — does the retrieval proxy track answer quality? **GO**, human-signed-off 2026-09-16 (`decisions/0005`). T16b (analysis-plan lock) still required before the first Phase 4 run

## Phase 4 — Ablations
- [x] T17 · Ablation runner, resumable + cached (M) — `mcrag/eval/ablation_runner.py`: `find_or_create_run_dir` (resume by config-hash suffix, not timestamp), `GenerationCache` keyed `(model, digest, prompt_hash)` shared across a whole sweep, `run_arm`/`run_matrix` + `SweepPaused` for a clean quota-wall stop. Deliberately generic — no retrieval/generation logic, just the orchestration T18+ plug `evaluate_fn` into. `tests/test_ablation_runner.py` (13) proves clean-vs-resumed-sweep metrics are identical
- [x] T18 · Free retrieval ablations — **factorial, 32 cells, not OFAT** (L) — 2^5 design (boilerplate × chunking × reranker × fusion × silo_boost), dev split, zero quota/zero network. New seams: `mcrag/retrieval/{fusion,reranker,silo_boost}.py`, `mcrag/eval/factorial.py` (main effects + 2-way interactions). Frozen config (`decisions/0007`): boilerplate OFF, `FixedSizeChunker(512)`, RRF fusion ON, reranker OFF, silo boost OFF — chosen by an explicit tie-break rule among 4 cells tied at 0.708, with a per-factor "why this lost" recorded for every rejected option, not just the winner
- [x] T19 · Generation scoring ladder (M) — Tier 0 (`mcrag/eval/tier0_scoring.py`: citation accuracy/validity, refusal correctness, exact-match presence, hand-verified against 5 real T16 answers), Tier 1 (`mcrag/eval/nli_faithfulness.py`: local NLI cross-encoder, zero quota — ⚠️ **as shipped, silently truncated its context and scored every answer 0.000; rewritten under T20, rewrite fails validation**, `decisions/0008`), Tier 3 built + calibration-gated (`mcrag/eval/judge_calibration.py` + `tier3_judge.py`) but not run for real yet — that calibration against T16's hand-scores is T20's job, per `decisions/0006`
- [x] T20 · Phase 3c generation baseline (S) — **done.** Control of record `runs/20260917T044122Z_c1d4b7284f0f` (60 dev q; retrieval reproduces 0.708; refusal_correct 0.850, out_of_scope 0.500 = the #9 gap; faithfulness 0.435, unvalidated). Found and fixed: T19's Tier 1 silently truncated (scored every answer 0.000), the prompt cut passages to 1,400 chars (hid 9% of retrieved gold), multi-turn history never passed. Temp 0 isn't deterministic → measured noise floor (refusal_correct rerun interval 15 pts wide), verification amended to metric-level and passes at the boundary. 3 human decisions recorded (`decisions/0008`, `0006` addendum)
- [x] T21 · τ calibration study (M) — `decisions/0009`, pre-registered before any score was computed. Zero quota; 180 train+dev questions, every raw score stored. Pre-registered result: no method meets 95% precision out of fold (the rule's pick would refuse 97% of answerable questions); the calibration methods cut out-of-scope detection to chance (CE AUC 0.717 raw → 0.467/0.501); triage leaves 95% of queries in the uncertain band. **Adopted post hoc** (human decision, floor lowered to 80%): raw cross-encoder gate, τ = 4.96 — OOF 23% coverage at 0.786 precision, still just short of 80%. `decisions/0006` addendum 2 records the new operating point
- [ ] T22 · Metered ablations #6, #8, #9, #10 — **dev only, selection not inference, interleaved by question** (L). Resolves a docs contradiction: `quota-calibration.md`/`decisions/0006` originally sized this against test; corrected to dev, `decisions/0006` addendum 3. τ *method* selection already done (T21). **#8/#9/#10 done** (`decisions/0010`, 360 calls, 22.6 min): citation-forcing only 53% compliant; #9's gate trades Tier0 refusal_correct (−0.40) for T21-native precision (0.567→0.938), a measurement-definition gap not a regression; **headline — gemma4:31b matches gpt-oss:20b's faithfulness at ~73pp less reasoning and is the fastest/cheapest arm**. Caught and fixed a sign bug in #9's own diff (post-hoc, zero quota) and a `ReadTimeout` crash on gemma4 (widened `quota_errors`, raised `timeout_s`). **#6 (reformulation ladder) still open**
- [ ] **Checkpoint E** — freeze config *before* test is ever touched
- [ ] T22b · Test-split confirmatory pass (S) — **new task**, PLAN's own "one final pass" that had never been scheduled. The single frozen Checkpoint-E config vs the T20 baseline, on test, exactly once. First and only place a real p-value appears in the project

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
