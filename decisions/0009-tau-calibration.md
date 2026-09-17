# 0009 — Abstention threshold τ: calibration method (Task 21)

**Date:** 2026-09-17 · **Status:** accepted: gate adopted **post hoc** at an 80% floor (the pre-registered 95% analysis found no usable gate)

## Context

τ gates answering: when the confidence signal falls below τ, the system refuses
and routes to the owning office (PLAN Sec 4e). The Task 20 control shows why it
is needed: with no abstention it answers 6 of 12 out-of-scope dev questions.
PLAN names three calibration methods for the signal; `decisions/0006` row 3
pre-registers choosing among them by **coverage at ≥95% precision**.

Three facts shaped the design (decided with the human reviewer, 2026-09-17):

- **PLAN assumed a reranker that `decisions/0007` froze off.** PLAN gates on
  "top rerank score < τ". The frozen pipeline's own score, RRF, is built from
  rank positions (max 3/60), so it measures leg agreement, not relevance.
- **No retrieval scores were ever stored** (T18 and T20 saved chunk ids only).
  They are recomputed here, at zero quota, and this time every raw score is
  stored per question so the analysis re-derives offline.
- **The train split (120 questions) had never been used.**

## Pre-registered analysis

Everything in this section was written before any confidence score or curve was
computed. Nothing here changes after results exist; anything added later is
marked as such.

### Human decisions

1. **"Correct" = evidence retrieved.** A question *should be answered* iff it
   has gold refs and every gold passage is in the frozen top 5
   (`all_golds_retrieved@5` via content-overlap canonicalization, the metric
   `decisions/0005` checked against hand scores at 76% agreement). Out-of-scope
   questions, and in-scope questions whose evidence retrieval missed, should be
   refused. A proxy for answer correctness, chosen because it is deterministic,
   free, and unaffected by the rerun nondeterminism measured in `decisions/0008`.
2. **Confidence signal = the cross-encoder** (`cross-encoder/ms-marco-MiniLM-L-6-v2`,
   already local), used to *score* the frozen top-5, never to reorder it. Dense
   cosine similarity is computed for the same passages and reported as an
   **exploratory reference only; it cannot be selected.**
3. **Fit on train + dev (180 questions).** The test split is not loaded.
   Consequence, accepted: T22's dev abstention numbers will be in-sample for τ;
   only the test split gives a clean estimate.

### Scores

- Cross-encoder scores are **raw logits** (`activation_fn` is Identity, verified),
  so margins and z-scores are not compressed by a sigmoid.
- **MaxP windowing.** A query plus a fixed 512-token chunk measured 708 tokens
  against the model's 512-token limit, so the cross-encoder would silently read
  only each passage's head. Each passage is cut into overlapping ≤1,000-char
  windows (`premise_windows`, shared with Tier 1), and its score is its best
  window's. Pairs over the model limit are counted, and must be 0.
- For each question: the frozen top-5 passages; the 20-passage fused candidate
  pool (top-5 included); and a **null set of 100 passages**, sampled once from
  the frozen chunk set with seed 42 and identical for every question.

### Features (s = scores of the frozen top 5, sorted high to low)

| Method | Feature | Role |
|---|---|---|
| raw | s₁ | **Reference**, not a candidate: the uncalibrated baseline. A global percentile of s₁ across queries is a monotone transform of it, so it has the identical curve; that reading of PLAN's "percentile" is represented here |
| normalized | (s₁ − mean(pool)) / pstdev(pool), 0 if pstdev = 0 | Candidate |
| margin | s₁ − s₂ | Candidate |
| percentile | fraction of the 100 null scores below s₁ (ties count half) | Candidate |

A 20-passage null was considered and rejected before running: 21 possible
values is too coarse to trace a curve. **Prediction recorded in advance:** top
retrieved passages likely beat random passages for nearly every query,
answerable or not, so `percentile` may saturate near 1.0 and fail to separate
the classes. If so, that is a finding about PLAN's percentile method, and the
method loses on the rule below like any other.

### Operating point and selection

- For a threshold τ, a question is answered iff feature ≥ τ.
  **coverage** = answered / all; **precision** = should-answer among answered.
- **τ for a set of questions:** the lowest τ with precision ≥ 0.95 (that is,
  maximum coverage subject to the floor); if none, τ = +∞ (answer nothing).
- **5-fold cross-validation**, stratified by slice, seed 42, identical folds for
  every method: τ is fitted on four folds and applied to the fifth, giving
  out-of-fold decisions for all 180 questions.
- **Selection rule** (among the three candidates only): the method with the
  highest out-of-fold coverage among those with out-of-fold precision ≥ 0.95.
  If none meets the floor out of fold, that is reported as the headline, and the
  method with the highest out-of-fold precision is selected (ties: coverage,
  then name).
- If the **raw reference** beats the selected method, that goes to the human
  reviewer, not silently shipped and not silently dropped.
- **Final τ** for T22/T27: the selected method refitted on all 180.
- **Uncertainty:** seeded percentile bootstrap (10,000 draws) over questions for
  coverage, precision and false-refusal rate; paired bootstrap for method
  differences. This is selection data, so no p-values (`decisions/0006`).
- **Model-initiated refusals, measured separately:** on dev only, from the
  Task 20 control answers (no generation exists for train). Reported as a gate ×
  model × label cross-tab, plus PLAN's any-signal-wins combination; in-sample.

## Results

*Pending — to be added below this line, without editing anything above.*

*Added 2026-09-17, after the run. Nothing above was edited.*

Run: `runs/20260917T133042Z_340a8f03a310` (`tau_calibration.json` has every
curve, fold τ and cross-tab; `tau_curves.png` the plots; every raw score is in
`per_query.jsonl`). 180 questions, 87 should-answer (48%). Cross-encoder pairs
over the model limit: **0**. Dev labels match the Task 20 control exactly.
Generation quota: 0. One precision on the text above: test questions are read
from the gold file and filtered out at load, as in every earlier task. None was
evaluated.

### Pre-registered result: no method meets the floor

Out-of-fold, at each method's cross-validated τ:

| Signal | Method | OOF coverage | OOF precision | OOF false-refusal |
|---|---|---|---|---|
| cross-encoder | raw (reference) | 0.017 [0.000, 0.039] | 0.667 (n=3) | 0.977 |
| cross-encoder | normalized | 0.022 [0.006, 0.044] | 0.500 (n=4) | 0.977 |
| cross-encoder | **margin** | 0.022 [0.006, 0.044] | 0.750 (n=4) | 0.966 |
| cross-encoder | percentile | 0.000 | — (never answers) | 1.000 |
| dense (exploratory) | raw | 0.000 | — | 1.000 |
| dense (exploratory) | normalized | 0.072 [0.039, 0.111] | 0.923 (n=13) | 0.862 |
| dense (exploratory) | margin | 0.039 [0.011, 0.067] | 1.000 (n=7) | 0.920 |
| dense (exploratory) | percentile | 0.000 | — | 1.000 |

**Headline, as the rule requires: no cross-encoder candidate meets 95% precision
out of fold.** The fallback selects the highest out-of-fold precision:
**margin, τ = 12.44**, which answers 2.2% of questions and refuses 96.6% of
answerable ones. The rule was followed, and its output is not a usable gate.

**The pre-registered escalation condition fired, and a second reason to escalate appeared:**
- *Pre-registered: the raw reference beats the selected method* over the whole
  usable range of the curve (e.g. ~0.80 vs ~0.70 precision at 20% coverage),
  though not at the 95% operating point, where both are useless.
- *Not pre-registered: the exploratory dense signal beats the primary.* Dense
  margin is the only method meeting the floor out of fold, on 7 answered
  questions. Not selectable by design, and too small to act on.

**The percentile prediction held.** Both signals' percentile features saturated
and never answered at the floor.

**Model-initiated refusals (dev, in-sample):** the model refused 9 of 60, and all
9 were should-refuse, so it never refused a question whose evidence was
retrieved. It caught 9 of 26 should-refuse questions. Policies on dev: always
answer precision 0.567; the model's own refusals alone 0.667 at 85% coverage,
0% false refusals; the selected gate 1.000 at 3.3% coverage (2 questions).
Any-signal-wins equals the gate here, since the gate refuses 58 of 60.

### Exploratory: why (computed after the result; selects nothing)

**The raw cross-encoder score carries real signal** (AUC 0.743, should-answer vs
rest), but not enough for a 95% floor at a 48% base rate.

| Group | n | CE raw top score, median [IQR] |
|---|---|---|
| in scope, all evidence retrieved | 87 | 4.03 [1.71, 5.81] |
| in scope, partial evidence | 25 | 2.47 [0.27, 4.53] |
| in scope, no evidence retrieved | 32 | −0.47 [−3.17, 2.05] |
| out of scope | 36 | −0.47 [−3.46, 2.20] |

Out-of-scope questions and in-scope questions whose retrieval found nothing are
indistinguishable to the gate, which is correct: both should be refused. The
failure is overlap. The top quarter of out-of-scope questions scores as high as
the bottom quarter of answerable ones.

**The calibration methods destroy out-of-scope detection.**

| Signal | Method | AUC in-scope vs out-of-scope |
|---|---|---|
| cross-encoder | raw | 0.717 |
| cross-encoder | normalized | **0.467** |
| cross-encoder | margin | **0.501** |
| dense | raw | 0.763 |
| dense | normalized | 0.654 |
| dense | margin | 0.592 |

For an out-of-scope question *every* candidate scores low, so its best passage
still stands out from its own pool, and still leads the second-best, by as much
as an answerable question's does. Normalizing and differencing remove the
absolute level, which is exactly the "nothing here is relevant" signal
abstention needs. **PLAN Sec 4e's premise that these methods fix calibration is
backwards for abstention.** They can help pick out an exceptionally strong single
match (dense normalized and margin do best at the extreme high-precision end),
but not decide whether anything relevant was found.

**Triage does not rescue retrieval scores either.** PLAN's fallback answers above
τ_high, refuses below τ_low, and sends the band between to a judge. With the
best signal (CE raw), the largest safe extremes in-sample are:

| Floor on both sides | Confidently refused | Confidently answered | Uncertain band |
|---|---|---|---|
| 95% | 8 (4.4%) | 1 (0.6%) | **171 (95%)** |
| 90% | 8 (4.4%) | 21 (11.7%) | 151 (84%) |
| 80% | 25 (13.9%) | 41 (22.8%) | 114 (63%) |

At PLAN's own floor, 95% of queries would go to the judge, which defeats the
point of triage ("intelligence spent only where needed"). **On this corpus,
retrieval scores cannot carry abstention.** It has to come from answer-level
signals: the model's own refusals (precise but low recall on dev), an NLI
answerability gate, or an LLM answerability judge.

## Decision

*Human reviewer, 2026-09-17:* **lower the precision floor.** Not the
recommendation (that was no τ gate, with abstention from answer-level
signals). The rule's pre-registered output (margin, τ = 12.44) is recorded
above and not adopted.

### Re-selection procedure (post-hoc, written before it was computed)

This is **not pre-registered.** The floor is changed after seeing results, and
the in-sample curves and triage table above were seen before choosing it
(e.g. raw cross-encoder: 41 of 180 answered at ≥80% in-sample). Everything
below is labelled post-hoc wherever it is reported.

- **Floor: 0.80**, the value named in the option the reviewer chose.
- **Eligible methods: raw, normalized, margin, percentile** (cross-encoder
  only). Raw is made eligible because the pre-registered escalation already
  fired (raw beats the rule's pick across the usable range), the reviewer's
  choice cited the raw cross-encoder at 80%, and the exploratory analysis shows
  normalized and margin at chance for out-of-scope detection. The rule restricted
  to the three original candidates is computed and reported too.
- **Same machinery, unchanged:** 5-fold stratified CV (seed 42), the same selection
  rule, the same bootstrap, and the same stored scores. No re-scoring and no new
  features. Dense stays non-selectable.
- **Operationally relevant number:** the selected gate combined with the model's
  own refusals (any-signal-wins) on dev, in-sample, since that is what a product
  would run.
- `decisions/0006` gets a dated addendum for the new operating point before the
  test split is touched.


### Post-hoc re-selection result (floor 0.80, raw eligible)

**Post-hoc: not pre-registered.** Same run and stored scores, no re-scoring.
Artifacts: `tau_calibration_floor80_raw_eligible.json`,
`tau_curves_floor80_raw_eligible.png`. The pre-registered `tau_calibration.json`
is unchanged. `tau_curves.png` was re-rendered once, for a legend label only
("raw (reference)" became "raw (reference, not eligible)"); its data is identical.

| Method (cross-encoder) | τ (refit on 180) | OOF coverage | OOF precision | OOF false-refusal |
|---|---|---|---|---|
| **raw** | **4.96** | **0.233 [0.172, 0.300]** | **0.786 [0.655, 0.905] (n=42)** | 0.621 [0.516, 0.723] |
| normalized | 3.50 | 0.022 [0.006, 0.044] | 0.500 (n=4) | 0.977 |
| margin | 8.84 | 0.044 [0.017, 0.078] | 0.750 [0.400, 1.000] (n=8) | 0.931 |
| percentile | +∞ | 0.000 | — | 1.000 |

- **No eligible method meets 80% out of fold either.** Raw misses by 1.4 points,
  and its interval spans the floor. The rule's fallback, highest out-of-fold
  precision, selects **raw**.
- Raw's out-of-fold coverage exceeds normalized by +0.211 [0.150, 0.278] and
  margin by +0.189 [0.128, 0.250].
- The rule restricted to the three pre-registered candidates would select
  **margin**, τ = 8.84: 4.4% coverage.
- Dense (exploratory, not selectable): margin meets 80% out of fold (0.824 at
  18.9% coverage). Its interval overlaps raw cross-encoder's.
- Dev, in-sample, gate = raw τ 4.96: answers 16 of 60 at precision 0.938
  [0.789, 1.000], refuses 19 of 34 answerable. All 9 model refusals fall inside
  the gate's refusals, so any-signal-wins equals the gate alone on dev. The dev
  precision is optimistic: τ was fitted on these questions; the 0.786
  out-of-fold figure is the honest one.

### Adopted (human decision, post-hoc)

**Abstention gate: the raw cross-encoder score (`ms-marco-MiniLM-L-6-v2`,
MaxP logits, best of the frozen top 5); refuse and route when it is below
τ = 4.96.** The operating point is 80% precision, lowered from the
pre-registered 95%.

What this gate is, stated plainly so it is not overstated later:
- It **does not meet its own 80% floor out of fold** (0.786 [0.655, 0.905]).
- Out of fold it answers about a quarter of questions and **refuses ~62% of
  answerable ones**. About 1 in 5 of its answers lacks full evidence.
- It is **not** one of PLAN Sec 4e's three calibration methods. All three were
  dominated by the raw score, and two are at chance for out-of-scope detection.
- Its clean estimate comes only from the test split, since τ was fitted on
  train + dev.

Consequences:
- `decisions/0006` gets a dated addendum for the new operating point and the
  test-split comparisons that depend on it.
- T22's #9 arm evaluates this gate against always-answer.
- T27's refusal path runs this gate alongside the model's own refusals
  (any-signal-wins). The negative findings above still stand: a retrieval-score
  gate cannot reach 95% on this corpus, and answer-level signals remain the
  recorded route to higher precision.
