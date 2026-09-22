# 0013 — Task 22b: test-split confirmatory pass (pre-registration)

**Date:** 2026-09-22 · **Status:** design pre-registered, **not yet run**. This
is the one place in the project that spends the 120-question test split, so
per the standing rule (PLAN Sec 4f, `decisions/0006`) the design below is
fixed and written down *before* any test-split call is made — not chosen
after seeing what a first look would show.

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
production. Final call is the user's.
