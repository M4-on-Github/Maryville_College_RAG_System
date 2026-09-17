# 0006 — Pre-registered analysis plan (Task 16b)

**Date:** 2026-09-16 · **Status:** accepted, locked at Checkpoint D, governs every Phase 4 run

## Context

PLAN 4f: "Without this section the ablation table is a leaderboard of noise."
This is written and committed *before* the first Phase 4 run (T17/T18), because
its entire purpose is to make Phase 4 confirmatory rather than a search for a
story. Written after seeing results, it is worthless — the whole point is that
nothing below can be revised once an ablation table exists to tempt a revision.

## Decision

### Primary metrics, frozen

**Retrieval:** `all_golds_retrieved@k`, chosen empirically in Phase 3b
(`decisions/0005-primary-retrieval-metric.md`, Checkpoint D, human-signed-off
2026-09-16). Not re-opened here — re-choosing it after seeing Phase 4 results
is the exact garden-of-forking-paths failure this whole structure exists to
prevent.

**Generation:** Tier 1 (local NLI faithfulness — PLAN 4d) is primary. It is
the cheapest tier above deterministic checks that is *graded* (so it carries
real signal, not just a pass/fail), it runs free and local so every Phase 4
ablation can be scored on it (unlike Tier 2/human, feasible only at n≈25 and
n≈120), and it measures the property Phase 3b's own quadrant analysis singled
out as the actual risk for an institutional bot: whether the answer is
grounded in retrieved content, not whether it merely reads well. Tier 0
(citation accuracy, citation validity, refusal correctness — all binary) are
secondary metrics, each scored with exact McNemar where a paired comparison is
made. Tier 2 (human) and Tier 3 (calibrated LLM judge, κ reported) are reserved
for T20's control run and the final test-split confirmation — not run per
ablation arm.

**Abstention:** coverage at the stated precision floor (PLAN 4e): *of the
questions the system chooses to answer, ≥95% must be correct; subject to
that, maximise coverage.* The primary number is **coverage at the ≥95%
precision operating point**, read off each config's own precision/coverage
curve — not a fixed τ value, since τ itself is uncalibrated across configs
and its calibration method is T21's separate job. This is a metric-family
choice, not a threshold choice; nothing about the method that produces τ
needs deciding here.

### Comparisons the test split will be spent on

The 120-question **test** split is touched exactly once, per the project's
standing rule, and only for the ten metered-ablation arms already sized in
`docs/quota-calibration.md` ("10 arms on the 120-question test split: 1200
queries"). Every one of these is a comparison against T20's frozen Phase 3c
naive-generation baseline unless noted otherwise. Anything not on this list
that gets reported from Phase 4 is **exploratory**, labelled as such, and
carries no p-value (dev-only, or test-split-but-unregistered numbers are
descriptive).

| # | Comparison | Outcome type(s) | Test |
|---|---|---|---|
| 1 | Query reformulation ladder (PLAN 4c #1–7) — best free step vs. +domain dictionary vs. +decomposition vs. +multi-query, stepped, stop when gains flatten | primary generation (graded) | paired bootstrap |
| 2 | Prompt: citation-forced vs. free-form (#8) | Tier 0 citation accuracy/validity (binary) + primary generation (graded) | McNemar (binary) + paired bootstrap (graded) |
| 3 | Abstention: τ calibration method — per-query normalised vs. margin-based vs. percentile-based (#9, method selection) | coverage @ ≥95% precision | paired bootstrap |
| 4 | Abstention: chosen τ method vs. no threshold (always-answer) baseline (#9) | coverage @ ≥95% precision, correct/false-refusal rates | McNemar (refusal correctness) + paired bootstrap |
| 5 | Generation model: `gpt-oss:20b` vs. a lighter cloud model, at the frozen retrieval config (#10) — run last, on a settled pipeline | primary generation (graded) + abstention coverage | paired bootstrap |
| 6–10 | Reserved: the remaining reformulation-ladder steps (#6's later, costlier steps — decomposition, multi-query, step-back, HyDE) each tested only if the cheaper step before it does not flatten gains, per PLAN 4c's own stopping rule | primary generation (graded) | paired bootstrap |

Rows 6–10 are intentionally not fully enumerated in advance: PLAN 4c's ladder
is explicitly sequential ("each step costs more than the last; stop when
gains flatten"), so how many of the five remaining reformulation steps
actually get run is itself data from row 1, not something knowable today.
What *is* fixed now is the stopping rule and the fact that every step tested
is a test-split spend against the T20 baseline — no step gets a second,
unregistered comparison against a different reference.

The free ablations (#1–5, #7 — boilerplate stripping, chunking, retrieval
legs/fusion, reranker, k-sweep, silo boost) are **not** on this list: they
score against the Phase 3a retrieval baseline on **dev**, cost no quota, and
their comparisons are selection, not inference (see below) — T18's 32-cell
factorial picks a config; it does not produce a reportable p-value.

### Dev is selection, not inference

No p-value computed on dev appears in the writeup. `mcrag.eval.significance`
enforces this mechanically: `mcnemar_exact(..., split="dev")` still computes
a p-value (the function doesn't know what the reporting layer will do with
it), but `assert_reportable` raises `DevSplitSignificanceError` if that
result's `p_value` is not `None` and `split == "dev"` — so a comparison
report can call `assert_reportable` on everything it emits and the dev/test
boundary is enforced at the point of reporting, not by trusting every caller
to remember.

### τ operating point, restated

Per PLAN 4e: *of the questions the system chooses to answer, ≥95% must be
correct; subject to that, maximise coverage.* This is the decision rule for
reading τ off the swept curve (T21) — not a taste judgment, and not
re-litigated per ablation.

## Consequences

- `mcrag/eval/significance.py` implements `paired_bootstrap_ci`,
  `mcnemar_exact`/`mcnemar_p_value`, and `assert_reportable`, all returning
  `stats.Interval`'s `(value, ci_low, ci_high, n)` shape — never a bare
  float. `tests/test_significance.py` (19 tests) includes the calibration
  round-trip T16b's own verification step asks for: a known synthetic effect
  recovered at roughly the nominal coverage rate, and the exact McNemar
  p-value roughly uniform under a true null.
- `scripts/mde.py` reproduces PLAN 4f's detectable-effect table by
  simulation, now calling `mcnemar_p_value` directly (previously reimplemented
  via `scipy.stats.binomtest`, an undeclared dependency neither declared in
  `pyproject.toml` nor exercised by the test suite) — the power-analysis tool
  and the real significance test can no longer silently drift apart. It also
  now covers all four PLAN 4f splits (pooled/dev/cross-silo/out-of-scope);
  the committed version only ever printed three.
- T17 (ablation runner) and T18 (free retrieval ablations) may now start.
  Neither may compute or report a p-value; T18 runs entirely on dev.
- Any Phase 4 finding not in the comparison table above is reported as
  exploratory, with an effect size and CI but no significance claim,
  regardless of which split it happens to be computed on.

## Addendum — 2026-09-17, after Task 20 (`decisions/0008`)

Added, not edited in: the text above stands as originally locked. This
addendum was written after the Task 20 *baseline* was scored, but before
any Phase 4 generation *comparison* had been run, so no arm-vs-arm result
existed to steer it. That timing is what makes it legitimate; the same
change made after a T22 result would not be.

1. **Tier 1 faithfulness stays the primary generation metric** (human
   decision), with its evidence stated rather than assumed. The implementation
   pre-registered here silently truncated its context and scored every
   validation answer 0.000. The corrected scorer fails its own pre-set
   validation against the Task 16 hand scores (Spearman 0.166 [−0.158,
   0.457], on an underpowered 20-answer set), and its absolute values run
   low. Therefore:
   - it is interpreted **only as a paired difference between arms**, never as
     an absolute grounding rate ("40% of claims are grounded" is not a claim
     this metric supports);
   - every report of it carries the statement that it is **not validated
     against human judgment**;
   - it is computed over **answered questions only**, with `refusal_rate`
     reported beside it, since refusals are scored separately (R) and would
     otherwise count as unfaithful answers.
2. **Every generation comparison reports the measured noise floor beside its
   effect.** Temperature 0 is not deterministic on this endpoint: two identical
   Task 20 runs flipped the refuse/answer decision on 5 of 60 questions. An arm
   difference inside the null-arm interval (control vs. a rerun of itself) is
   reported as indistinguishable from rerun noise, whatever its point estimate.
3. Unchanged: the test split is still spent once, and still only on the table above.

## Addendum 2 — 2026-09-17, after Task 21 (`decisions/0009`)

Added, not edited in. Written after Task 21's train + dev results, before the
test split was touched and before any Phase 4 generation comparison.

1. **τ operating point lowered from ≥95% to ≥80% precision** (human decision,
   post hoc). The pre-registered 95% analysis found no retrieval-score gate at
   any useful coverage: its rule's pick would have refused 97% of answerable
   questions. This supersedes the 95% figure in both places it appears
   above: the primary abstention metric (now **coverage at ≥80% precision**)
   and "τ operating point, restated". What both say otherwise still stands:
   a stated floor, not a taste judgment, and not re-litigated per ablation.
2. **Row 3 kept, at the new floor.** On the test split, compare raw, normalized,
   margin and percentile on coverage at ≥80% precision (paired bootstrap), each
   at its τ fitted on train + dev. Raw is added because it is the adopted gate.
   Train + dev already found all three original candidates dominated by raw.
   Re-running on untouched data costs no quota and is the only clean check of
   that finding.
3. **Row 4 kept, with the adopted gate:** the raw cross-encoder at τ = 4.96 vs
   always-answer. Outcomes: coverage, precision, false-refusal rate, and refusal
   correctness (McNemar). This is the gate's first clean estimate. Its
   out-of-fold precision on train + dev, 0.786 [0.655, 0.905], does not meet
   the 80% floor, and the test result is reported against that floor either way.
