# 0018 — Suffix decision field (T41b)

**Date:** 2026-09-24 · **Status:** pre-registered, not yet run. Split: **dev only.**
Everything above `## Results` was written and committed **before the first generation
call** and is not edited once a result is seen.

## Why this gets a turn at all

`decisions/0017` rejected the prefix decision field and said plainly that a rejection
is not a retry. This is not that candidate again. T41 did not fail because labelling
is a bad idea — the label was emitted 60/60 times and caught 12/12 out-of-scope cases
against the shipped classifier's 8. It failed because the label came **first**, and a
model that has committed to `ABSTAIN` on line one stops writing the partial answer the
adopted prompt would have given: median completion tokens 63.5 → 53.5, `cross_silo`
`refusal_correct` −0.500 [−0.786, −0.214], five hand-verified content losses.

Moving the field to the **end** attacks exactly that mechanism: the model writes the
answer first and labels what it wrote afterwards. T41 logged this variant as a
follow-up requiring its own pre-registration and an explicit go-ahead; the go-ahead was
given on 2026-09-24.

**The stopping rule still binds** (`decisions/0011`): this is the second and last
variant of the labelling idea. If the suffix form does not clear the bar, the
answer-level labelling route is closed and layer 5 stays as T40 left it, with its blind
spot documented rather than patched.

### One design cost, recorded up front

A trailing field cannot be read until generation is complete, so it forecloses the
prefix-classification streaming fix logged in T42 (`docs/LIMITATIONS.md` §7) — that idea
depends on deciding early. The prefix form would have been compatible with it. Today's
service already buffers the whole answer for the same reason, so the suffix field costs
nothing against the shipped behaviour; it costs an option that was never built.

---

## Pre-registration

### Arms — 3, interleaved question-major (`decisions/0008`), 60 dev questions each, 180 calls

| arm | system prompt | role |
|---|---|---|
| `suffix_field_gemma4_31b` | `SUFFIX_DECISION_FIELD_SYSTEM_PROMPT` | the candidate |
| `scope_strict_gemma4_31b_a` | `SCOPE_STRICT_SYSTEM_PROMPT` | control = adopted config (`decisions/0014` rung 1) + the T40 classifier as its detector |
| `scope_strict_gemma4_31b_b` | `SCOPE_STRICT_SYSTEM_PROMPT` | **noise floor** — identical to `_a` |

Both controls are **rerun fresh in the same session** rather than reused from T41, for
the same-session pairing reason `decisions/0010` gives. All arms `gemma4:31b`,
temperature 0.0, frozen retrieval (`decisions/0007`), full dev split, `TAU` gate not
run (as in every prior generation arm).

### The protocol, and the one deliberate difference from T41

The reply's **last** line must be exactly `DECISION: ANSWER` or `DECISION: ABSTAIN`.
Parsing is fixed in `mcrag/generate/decision_field.py` before the run and is as strict
as T41's, so the two are comparable: a decorated, mid-text or missing line is a
**protocol violation**, not something to go hunting for.

The prompt resolves T41's one untruthful label explicitly: if the reply answers part of
the question and notes what the passages do not cover, that is **ANSWER**, not
`ABSTAIN`. T41's `pilot-cs-06` — a body that stated the meal-plan policy under an
`ABSTAIN` label — is the case this wording exists for. It is a real change in what the
field means, and it is stated here rather than discovered later.

Scoring runs on the text with the trailing line removed, exactly as T41 scored on the
stripped text.

### Channels, metrics, and the primary comparison

Unchanged from `decisions/0017`, so the two candidates can be read side by side:
`frozen` (the frozen eval classifier), `t40` (`NarrowPhraseClassifier`, what ships),
`field` (the parsed decision), and `shipped` = field where present, `t40` on a
violation. **Primary:** `refusal_correct` on `shipped`, candidate − control `_a`, pooled
dev and on `out_of_scope`. Noise floor = `_b` − `_a` for the same statistic.

Secondary, all reported whatever the primary does: frozen-channel `refusal_correct`;
out-of-scope answered count; Tier 1 faithfulness on answered in-scope; protocol
violations; field-vs-`t40` disagreements; median `completion_tokens` and median
`wall_s` with bootstrap CI. Effect size and CI only — **no p-value on dev** (PLAN 4f).

**Pre-registered this time, because T41 had to do it post-hoc:** every in-scope question
the candidate labels `ABSTAIN` gets hand-triaged against what control `_a` wrote for the
same question, and each is classified as *control also refused* / *content lost* /
*label disagrees with its own body*. The counts go in `## Results` whatever they are.

### Adopt / reject rule, fixed here before the run

Adopted only if **all five** hold:

1. primary `refusal_correct` gain on pooled dev exceeds the noise floor's absolute
   magnitude, and its CI excludes 0;
2. out-of-scope answered count does not increase versus the control;
3. faithfulness on answered in-scope does not fall by more than the noise floor's
   absolute magnitude;
4. protocol-violation rate ≤ 10%;
5. **the content check T41 failed:** paired median `completion_tokens` is not lower
   than the control's by more than the noise floor's absolute magnitude, and the hand
   triage finds **no** case where the candidate dropped substantive content the control
   supplied.

Criterion 5 is the whole point of the variant, so it is a gate, not a note. Any one
failing → **rejected and logged**, the frozen prompt stays as `decisions/0014` left it,
and per the stopping rule above the labelling route closes.

### Verification

Three run dirs under `runs/`, each with config and corpus/model/split locks; analysis at
`runs/t41b_suffix_field_analysis.json`; this doc's `## Results` listing every arm, the
triage counts, and the comparison against T41's prefix arm.

---

## Results

_Not yet run._
