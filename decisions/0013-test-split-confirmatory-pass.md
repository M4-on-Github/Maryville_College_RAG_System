# 0013 — Task 22b: test-split confirmatory pass (pre-registration)

**Date:** 2026-09-22 · **Status:** design pre-registered and resolved,
about to run. This is the one place in the project that spends the
120-question test split, so per the standing rule (PLAN Sec 4f,
`decisions/0006`) the design below is fixed and written down *before* any
test-split call is made — not chosen after seeing what a first look would
show.

## Context

Checkpoint E froze a single config (`decisions/0007` retrieval, unchanged;
`decisions/0011` no reformulation; `decisions/0010`'s generation model
switched to `gemma4:31b`). `decisions/0012` resolved the one remaining
prerequisite: Tier 3 is dropped for this pass (calibration failed its own
gate), so scoring here is Tier 0 + Tier 1, plus whatever Tier 2 (human)
scope is decided below.

**Only one axis actually changed at Checkpoint E: the generation model.**
Retrieval is byte-identical between the frozen config and the Task 20
baseline — `decisions/0007` predates both, and `decisions/0011` kept
`IdentityReformulator` (no-op) rather than adding a reformulation step the
baseline never had either. So T22b is, mechanically, `decisions/0010`'s
#10 comparison (`gemma4:31b` vs `gpt-oss:20b`, free-form prompt, no
citation forcing, no abstention gate — `decisions/0010`'s `#9` found real
tradeoffs but nothing from #8/#9 was adopted into the frozen config) —
replayed on test, with real inference statistics instead of dev's
effect-size-only.

## Design

### Three arms, interleaved (question-major, `run_interleaved`)

| Arm | Model | Purpose |
|---|---|---|
| `t22b_baseline_20b_a` | gpt-oss:20b | Task 20 baseline's methodology, replayed on test |
| `t22b_baseline_20b_b` | gpt-oss:20b, identical config | **noise floor** — a second, independent live pass, never cached (`decisions/0008`) |
| `t22b_frozen_gemma4_31b` | gemma4:31b | the single frozen Checkpoint-E config |

Both real arms: frozen retrieval (`decisions/0007`), `IdentityReformulator`
(no-op, `decisions/0011`), free-form prompt (`SYSTEM_PROMPT`, not
citation-forced), no pre-generation abstention gate (matches Task 20's
"no abstention threshold" baseline — the model may still refuse in its own
text, scored by Tier 0's `refusal_correct`, same as every prior task).
Temperature 0. All three answer the full 120-question **test** split,
out-of-scope questions included.

### The one pre-registered comparison

**`t22b_frozen_gemma4_31b` vs `t22b_baseline_20b_a`, pooled over all 120
test questions.** This is the only comparison this doc licenses a p-value
for. Anything else computed (by-slice breakdowns, the noise floor itself)
is reported as effect size + CI, exploratory, same as every dev-split number
in the project.

**Metrics and test type**, per PLAN 4f's binary/graded split:

| Metric | Type | Test |
|---|---|---|
| `refusal_correct` (Tier 0) | binary | exact McNemar + paired bootstrap CI |
| `citation_accuracy`, `citation_validity` (Tier 0, when a URL is cited) | binary | exact McNemar + paired bootstrap CI |
| `faithfulness` (Tier 1, answered only, **unvalidated** per `decisions/0008`/`0012`) | graded | paired bootstrap CI only |
| `wall_s`, `completion_tokens`, `reasoning_char_share` | cost/graded | paired bootstrap CI only |
| `all_golds_retrieved@5` | binary | **sanity check only, not a comparison** — retrieval is identical between arms by construction, so a real difference here would indicate a bug, not a finding |

`assert_reportable` is called on every `ComparisonResult` before it's
written to the report — a guard against a `split="dev"` typo reaching a
p-value, not because test needs protecting from itself.

### Noise floor

`t22b_baseline_20b_b` vs `_a`: identical config, a second live pass, same
method `decisions/0008` and `decisions/0010` used. Reported beside the
primary comparison's effect for every metric — an effect inside the noise
floor's band is not distinguished from rerunning the control.

### Scoring tiers

- **Tier 0** (deterministic) and **Tier 1** (NLI faithfulness) — always, free.
- **Tier 3** — not run. `decisions/0012`: calibration failed (κ=0.146 vs a
  0.6 floor); `Tier3JudgeScorer` mechanically refuses without a passing
  `CalibrationResult`.
- **Tier 2** (human) — PLAN reserves this for exactly this pass, feasible at
  "n≈120." Scope **not yet decided** — see below.

### Test-split access log

Per the standing rule ("log every access"), the run appends a dated entry
to `notes.md` (repo root, new — no such log existed before this doc) naming
the frozen config, the arms, and the split-lock hash, at the moment the
first test-split question is actually sent to a generator, not before.

## Open before this can run

**Tier 2 scope.** Hand-scoring 120 questions per arm (240 total) is a large
time cost; hand-scoring a sample is a middle option; skipping it entirely
leaves Tier 0 + Tier 1 as the only scoring, same as every dev-split ablation
in this project. PLAN says Tier 2 "may" be spent here, not "must" — it does
not force a choice. Recommendation: **skip full Tier 2**, given the 50-item
calibration set (`decisions/0012`) already produced an independent
hand-scored check this session, and Tier 1's own validity concern is
already flagged rather than hidden. A human spot-check of the confirmatory
pass's disagreement cases (if any) remains available afterward at near-zero
cost, the same "propose, human confirms" pattern PLAN describes for
production.

## Resolution — 2026-09-22

**Tier 2: skip full hand-scoring.** Confirmatory pass runs on Tier 0 + Tier
1 only. **Go-ahead given** to write and run the script now.

## Results — 2026-09-22

`scripts/run_t22b_test_confirmatory.py`, all 360 calls completed cleanly (no
quota pause, 0 quarantined records in any arm).
`runs/t22b_test_confirmatory_analysis.json`. Run dirs:
`runs/20260922T151047Z_18b214bce36b` (`t22b_baseline_20b_a`),
`runs/20260922T151047Z_4185e547c9ee` (`t22b_baseline_20b_b`),
`runs/20260922T151047Z_9a6295b654ee` (`t22b_frozen_gemma4_31b`).

### Retrieval sanity check

`recall@k`, `mrr`, `ndcg@k`, `all_golds_retrieved@k` are **bit-identical
across all three arms** (0.65625 / 0.56615 / 0.56389 / 0.58333, n=96) — as
they must be, since retrieval is byte-identical by construction. Confirms
no bug crept into the arm-swap; not a finding.

### Primary comparison — frozen (gemma4:31b) − baseline (gpt-oss:20b), pooled n=120

| Metric | Δ | 95% CI | McNemar p |
|---|---:|---|---:|
| refusal_correct | −0.017 | [−0.083, +0.050] | 0.81 |
| citation_accuracy | +0.036 | [+0.000, +0.107] (n=28) | 1.00 |
| citation_validity | +0.000 | [+0.000, +0.000] (n=28) | 1.00 |
| faithfulness | −0.053 | [−0.139, +0.030] (n=93) | — (graded) |
| wall_s | **−5.503** | [−6.134, −4.921] | — |
| completion_tokens | **−297.8** | [−332.2, −265.0] | — |
| reasoning_char_share | **−0.755** | [−0.782, −0.727] | — |

No metric that got a McNemar test shows a discordant-pair pattern
distinguishable from chance (p≥0.81 on all three). `faithfulness`'s CI
crosses 0. The three cost/latency metrics don't: gemma4:31b is faster,
shorter, and virtually reasoning-channel-free on test, at effect sizes an
order of magnitude past the noise floor below. **This reproduces
`decisions/0010`'s dev-side #10 finding, now on held-out test, with real
inference statistics instead of dev's effect-size-only comparison.**

### Noise floor — second gpt-oss:20b pass − first, pooled n=120

| Metric | Δ | 95% CI |
|---|---:|---|
| refusal_correct | +0.050 | [−0.008, +0.117] |
| faithfulness | +0.015 | [−0.039, +0.067] |
| citation_accuracy | +0.058 | [+0.000, +0.154] (n=26) |
| citation_validity | +0.026 | [+0.000, +0.077] (n=26) |
| wall_s | +0.409 | [−0.244, +1.169] |
| completion_tokens | +14.5 | [−11.9, +42.5] |
| reasoning_char_share | −0.005 | [−0.028, +0.019] |
| exact_text_match | 0.158 | [0.092, 0.225] |

Every noise-floor interval sits inside a band close to zero (`wall_s`
±~1s, `completion_tokens` ±~40, `reasoning_char_share` ±0.03). The primary
comparison's cost/latency effects (−5.5s, −298 tokens, −0.755 share) are
5-25x past that band — not noise. The primary comparison's accuracy
effects (refusal_correct, faithfulness) are the same size or smaller than
the noise floor's own spread, consistent with their CIs crossing 0.
`exact_text_match` at 0.158 (not 1.0) confirms `gpt-oss:20b` is not
perfectly deterministic at temperature 0 even on identical input — same
finding as `decisions/0008`'s reproducibility check.

### By-slice (effect size + CI only, not individually licensed for a p-value)

`reasoning_char_share` drops by 0.67-0.85 in **every** slice — the effect
is not concentrated anywhere. `faithfulness`'s point estimate is negative
in most slices, largest at `temporal` (−0.352 [−0.704, 0.000], n=9) and
`out_of_scope` (−0.144 [−0.417, 0.106], n=12), but every slice's CI still
crosses 0 and n is small enough (6-32) that none of these should be read
as a per-slice finding — full detail in
`runs/t22b_test_confirmatory_analysis.json`.

### Per-arm absolute numbers (for context, not part of the paired comparison)

| | `t22b_baseline_20b_a` | `t22b_baseline_20b_b` | `t22b_frozen_gemma4_31b` |
|---|---:|---:|---:|
| refusal_correct | 0.808 | 0.858 | 0.792 |
| faithfulness | 0.414 | 0.436 | 0.345 |
| citation_validity | 0.956 | 0.974 | **1.000** |
| wall_s | 6.47 | 6.88 | **0.97** |
| completion_tokens | 376.2 | 390.7 | **78.4** |
| reasoning_char_share | 0.755 | 0.750 | **0.000** |

`gemma4:31b`'s `reasoning_char_share` is exactly 0.0 on test (not just
lower) — it produced no separately-tagged reasoning channel at all on any
of the 120 test questions, consistent with `decisions/0008`/`0010`'s
characterization of it as a non-reasoning-channel model relative to
`gpt-oss:20b`.

## Conclusion

**Checkpoint E's frozen config confirms on test.** The generation-model
swap (`gpt-oss:20b` → `gemma4:31b`) that Checkpoint E adopted shows no
accuracy or faithfulness cost distinguishable from noise on the held-out
120-question test split, and a large, tight-CI, far-outside-noise-floor
win on every cost/latency metric. `citation_validity` reaches 1.000 on
test for the frozen arm (vs 0.956/0.974 for the two baseline passes) —
consistent with, not contradicting, the accuracy-neutral finding, since
`citation_validity` conditions on citing at all and gemma4:31b cites more
often (`citation_accuracy` +0.036, CI includes 0). Retrieval's identical
numbers across all three arms confirm the arm-swap touched only the
generation model, as designed. No further test-split access is needed for
Checkpoint E's question; Task 22b is closed.
