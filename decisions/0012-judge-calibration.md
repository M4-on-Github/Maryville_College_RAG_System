# 0012 — Tier 3 judge calibration (T22b prerequisite)

**Date:** 2026-09-22 · **Status:** calibration run complete. Both Tier 3 and
the Tier 1 re-check fail their pre-registered gates. Decision on how T22b
proceeds without a calibrated judge is pending — see bottom.

## Context

`decisions/0008` left Tier 3 (PLAN Sec 4d) unbuilt-in-practice: the
calibration round was declined at Task 20 and flagged as still owed before
Task 22b, which PLAN reserves Tier 2/3 scoring for. `mcrag/eval/tier3_judge.py`
and `mcrag/eval/judge_calibration.py` were built and tested at T19 (fake
`judge_fn` only) — never run against a real model. This doc is that run.

**Judge model:** `nemotron-3-nano:30b`, checked against `/v1/models`
2026-09-17 (`decisions/0010`). Not `gemma4:31b` or `gpt-oss:20b` — those are
T22b's two arms, and `Tier3JudgeScorer.__post_init__` raises
`JudgesItsOwnOutputError` if the judge and judged model ever match, so the
guard is enforced in code, not just by choosing carefully. Temperature 0,
enforced the same way (`TemperatureNotZeroError`).

## Calibration-set design, pre-registered before any human or judge score existed

- **Source:** the two dev runs T22b's arms are built from —
  `free_form_gemma4_31b` and `free_form_20b_a`, both dev, both already on
  disk from `decisions/0010`. No new generation, no quota spent building the
  set. Never test — `mcrag/eval/calibration_set.py`.
- **n=50, seeded (42), slice-stratified, 25/25 by model**, largest-remainder
  allocation so `multi_turn` and `adversarial` (the smallest slices) still
  get at least one item.
- **Blind.** No model name, no judge score, no NLI score on the sheet the
  human scored from — PLAN's "pipeline proposes, human accepts" workflow is
  right for production labelling and wrong for a calibration set: a human
  anchored on a proposed label makes kappa measure suggestibility, not
  agreement.
- **Gate, fixed in code before this run** (`mcrag/eval/judge_calibration.py`,
  built at T19): κ ≥ 0.6 (Landis & Koch "substantial"). `assert_calibrated`
  raises on every call a `Tier3JudgeScorer` makes, not just once, so a score
  can't be reported by a scorer built before the gate was checked.

## Results

`scripts/run_judge_calibration.py`, `data/calibration/calibration_result.json`:

| Check | Result | Floor | Passes? |
|---|---|---|---|
| Tier 3 (Nemotron) vs human, Cohen's κ | **0.146 [−0.113, 0.540]** (n=50) | 0.6 | **no** |
| Tier 1 (NLI) vs human, Spearman | **0.030 [−0.248, 0.300]** (n=40, refusals excluded) | CI excludes 0 | **no** |

Both fail. Tier 1's failure is not new — `decisions/0008` Finding 2 found the
same thing on Task 16's 25-item set (Spearman 0.166 [−0.158, 0.457]); this
re-run, on an independent, larger (n=40 vs n=46 scoreable) set, reproduces
it. **The primary generation metric's validity concern from `decisions/0008`
stands, now with more power behind it, not less.**

### Why Tier 3's raw agreement (86%) doesn't mean much here

45 of 50 human labels are 2, 5 are 1, **0 are 0**. `cohens_kappa` corrects
for the agreement two raters would hit by chance given their own label
frequencies — and when one rater's distribution is this lopsided, chance
agreement is already high (both raters saying "2" most of the time costs
nothing to predict), so the *correction* eats almost all of the raw 86%.
Confusion matrix:

| | judge=0 | judge=1 | judge=2 |
|---|---:|---:|---:|
| **human=0** | 0 | 0 | 0 |
| **human=1** | 0 | 1 | 4 |
| **human=2** | 0 | 3 | 42 |

Every disagreement is a 1-vs-2 flip; nothing scored a 0 by either rater. The
judge is not obviously *wrong* — it never called something correct that was
actually hallucinated, in this set — but there's no evidence either way on
that axis, because the set contains no ground-truth hallucination to detect.
**This is a property of the calibration set, not (necessarily) of the
judge**, and it's the same failure mode `decisions/0008` flagged for the
T16 hand-scored set (20 twos, 3 ones, 2 zeros): "can expose a broken metric
but has almost no power to confirm a working one." Sampling from *already
generated, already-decent* dev answers reproduces that imbalance almost by
construction — the system mostly gets things right, so a representative
sample of its answers mostly deserves a 2.

### The 7 disagreements

| Item | Slice | Generator | Human | Judge |
|---|---|---|---:|---:|
| cal-010 | single_silo | gpt-oss:20b | 1 | 2 |
| cal-012 | out_of_scope | gemma4:31b | 1 | 2 |
| cal-014 | cross_silo | gpt-oss:20b | 2 | 1 |
| cal-022 | out_of_scope | gpt-oss:20b | 1 | 2 |
| cal-024 | multi_turn | gemma4:31b | 2 | 1 |
| cal-039 | cross_silo | gpt-oss:20b | 2 | 1 |
| cal-050 | single_silo | gemma4:31b | 1 | 2 |

No generator bias worth reading into 25-item halves: agreement is 88%
(gemma4:31b) vs 84% (gpt-oss:20b), and mean scores are within 0.04 of each
other on both sides. The judge leans slightly generous (4 of 7 disagreements
are judge-higher-than-human) but n is far too small to call that a pattern
rather than noise.

## Conclusion for this doc

**Tier 3 is not usable for T22b as calibrated here.** `assert_calibrated`
mechanically blocks `Tier3JudgeScorer.judge()` from returning anything until
a passing `CalibrationResult` is attached — so this isn't a policy T22b's
script has to remember to honor, it's an exception it would hit immediately
if it tried. **Tier 1 stays exactly where `decisions/0008` left it**: primary
metric by human decision, interpreted only as a paired arm difference,
labelled unvalidated — this run adds evidence, it doesn't reopen that
decision.

The honest reading of both failures together: the calibration set this
project can build for free (real dev answers, not synthesized failures) is
systematically too easy, because the system it's sampling from is already
fairly accurate. Validating a metric's ability to catch *wrongness* needs
examples of wrongness, and there are too few of those lying around
unprompted at n=50.

## Decisions pending (the user's)

T22b's acceptance criteria (`tasks/plan.md`) allow Tier 2 (human) or a
*calibrated* Tier 3 at the final pass — Tier 2 was never conditioned on
Tier 3 succeeding, so it stays available regardless of this result. Three
non-exclusive options:

1. **Drop Tier 3 for T22b.** Run the confirmatory pass on Tier 0 + Tier 1
   (caveated, per `decisions/0008`) + Tier 2 human scoring, which PLAN
   already reserves for exactly this final pass (n≈120, "feasible... not
   across every ablation"). No further judge quota spent.
2. **One more calibration attempt, deliberately harder.** A fresh,
   pre-registered set built to contain real wrongness — e.g. oversampling
   `out_of_scope`/`adversarial` (where T22's #9 findings show real refusal
   gaps) rather than a representative slice-proportional sample — accepting
   this is no longer "representative of production traffic," it's
   "designed to have variance." Costs another ~50-item hand-scoring round.
3. **Both** — run T22b now on option 1's scorers, and treat a harder
   recalibration as separate, unblocking work that could upgrade a later
   pass if it succeeds, never re-touching test either way.
