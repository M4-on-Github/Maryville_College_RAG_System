# 0017 — Structured decision field for refusal (T41)

**Date:** 2026-09-24 · **Status:** pre-registered, not yet run. Split: **dev only.**
Everything below the line `## Pre-registration` was written and committed
**before the first generation call**; results go under `## Results` afterwards and
nothing above the line is edited once a result is seen.

## Why

Layer 5 of the service (`docs/LIMITATIONS.md` §7) decides "did the model refuse?"
by matching regexes against generated prose. T40 (`decisions/0016`) improved that
matcher but could not remove the underlying weakness: refusal is inferred from
wording, so a refusal phrased in a way the pattern list does not anticipate is
streamed to the user as an ordinary answer with no `refusal` event and no office
routing. The four live misses T40 fixed were found by hand, not by a method that
would find the fifth.

The industry alternative, and the one the research pass named (structured
abstention schema): stop inferring. Make the model *emit* the decision as a field,
and read the field. If the model complies, detection stops being a guessing game.

Two reasons this is an A/B and not a swap:

1. It changes `SCOPE_STRICT_SYSTEM_PROMPT`, the prompt adopted in `decisions/0014`
   after a four-rung ladder. Anything that touches it has to earn it on the same
   evidence standard.
2. Asking for a protocol line changes what the model writes *after* the line too.
   A prompt that improves refusal detection while degrading answer faithfulness or
   inflating cost is not an improvement, and only a paired run can tell.

Prompt-only abstention is known weak in the literature. The plausible outcome is
that the field is emitted inconsistently, or that it is emitted and is simply
wrong — both of which this design has to be able to report as a rejection.

---

## Pre-registration

### Arms — 3, interleaved question-major (`decisions/0008`), 60 dev questions each, 180 calls

| arm | system prompt | role |
|---|---|---|
| `decision_field_gemma4_31b` | `DECISION_FIELD_SYSTEM_PROMPT` (scope-strict + protocol line) | the candidate |
| `scope_strict_gemma4_31b_a` | `SCOPE_STRICT_SYSTEM_PROMPT` | control = adopted config (`decisions/0014` rung 1) + T40 winner as its detector |
| `scope_strict_gemma4_31b_b` | `SCOPE_STRICT_SYSTEM_PROMPT` | **noise floor** — identical to `_a`, differs only in endpoint non-determinism |

All three `gemma4:31b`, temperature 0.0, frozen retrieval config (`decisions/0007`,
k=5 of 20, reranker off, silo boost off), full dev split. The eval harness does not
run the `TAU` gate, exactly as in every prior generation arm (`decisions/0009`), so
this compares prompts, not the shipped stack.

### The protocol

The arm's prompt requires a first line of exactly `DECISION: ANSWER` or
`DECISION: ABSTAIN`. Parsing is fixed in `mcrag/generate/decision_field.py` before
the run: a leading line matching `^\s*DECISION:\s*(ANSWER|ABSTAIN)\s*$`
(case-insensitive) is consumed along with one following blank line.

- `field_present` — the line was there and parsed.
- **The stripped text is what gets scored.** Citation accuracy/validity, exact-match
  presence and Tier 1 faithfulness all run on the answer with the protocol line
  removed, so the arm is not rewarded or punished for the scaffolding itself.
- A missing or malformed line is a **protocol violation**, counted and reported.

### Three detection channels, recorded per record for every arm

| channel | what it is | why it is here |
|---|---|---|
| `frozen` | `mcrag.eval.tier0_scoring.looks_like_a_refusal` | comparability with every historical number, including the single test pass (`decisions/0013`). Left frozen, as T40 decided. |
| `t40` | `mcrag.service.refusal.NarrowPhraseClassifier` | what the service ships today |
| `field` | the parsed `DECISION` value | defined only where the field is present |

**`shipped` channel** = what each arm would actually do in production: `field` for
the candidate, falling back to `t40` on a protocol violation; `t40` for both control
arms. The primary comparison uses `shipped`, because the candidate's whole claim is
about the detection channel, not about the prose.

### Primary comparison

`refusal_correct` under the `shipped` channel (`refused != expects_answer`),
`decision_field_gemma4_31b` minus `scope_strict_gemma4_31b_a`, on the pooled dev
split and on the `out_of_scope` slice.

**Noise floor:** the same statistic for `scope_strict_gemma4_31b_b` minus
`scope_strict_gemma4_31b_a`. Reported beside every effect.

### Secondary, all reported whatever the primary does

- `refusal_correct` under the `frozen` channel (the comparable-with-history number)
- out-of-scope **answered** count per arm (the T22b error class this is aimed at)
- Tier 1 NLI faithfulness on answered in-scope questions, on stripped text
- protocol-violation rate, and field-vs-`t40` disagreement count
- cost: **median** `completion_tokens` and median `wall_s` per arm, with bootstrap CI
  on the median — never a mean (`decisions/0011`)

Effect size and bootstrap CI only. **No p-value on dev** — dev is selection, not
inference (PLAN 4f); the reporting guard in `mcrag.eval.significance` enforces it.

### Adopt / reject rule, fixed here before the run

Adopted only if **all four** hold:

1. primary `refusal_correct` gain on pooled dev **exceeds the noise floor's
   absolute magnitude**, and its CI excludes 0;
2. out-of-scope answered count does not increase versus the control;
3. faithfulness on answered in-scope does not fall by more than the noise floor's
   absolute magnitude;
4. protocol-violation rate ≤ 10%.

Any one failing → **rejected and logged**, with the arm table and the reason, and
the frozen prompt stays as `decisions/0014` left it. A rejection is a result, not a
retry: there is no rung 2 here, and no second variant gets a turn on the strength of
a near miss.

### Verification

Three run dirs under `runs/`, each with its config, a corpus lock, a model lock and
the dev split hash; the analysis JSON at `runs/t41_decision_field_analysis.json`;
this doc's `## Results` section listing every arm.

---

## Results

_Not yet run._
