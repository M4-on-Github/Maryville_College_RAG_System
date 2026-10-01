# 0018 — Suffix decision field (T41b)

**Date:** 2026-09-24 · **Status:** pre-registered, not yet run. Split: **dev only.**
Everything above `## Results` was written and committed **before the first generation
call** and is not edited once a result is seen.

> **Added after the run, 2026-09-30:** ran, **rejected** on criterion 1 — see
> `## Results`. The pre-registration above this line is byte-identical to what was
> committed in `c61e954` before the first generation call; the status is recorded here
> rather than by editing that line, because the line itself forbids editing it.

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

**Date:** 2026-09-30 · **Verdict: REJECTED** on criterion 1. Criteria 2-5 all pass.
Per the stopping rule above, **the answer-level labelling route is now closed**: layer 5
stays as T40 left it and its blind spot stays documented rather than patched.

### How the run was actually executed — a deviation from `decisions/0010`, logged

The 180 calls were not spent in one session. The batch of 2026-09-24 was killed by the
harness at 53 of 60 questions per arm for **system memory pressure** — not a fault in
the run, and not a result. On 2026-09-30 the runner was restarted intending a clean
180-call rerun; **T17 resumability reused the existing run dirs** instead of creating
new ones, so it spent only the 21 remaining calls and appended them. That was not the
option chosen, and it is recorded here rather than presented as the plan.

What this costs, stated precisely:

- the pooled 60 questions span two sessions (53 on 09-24, 7 on 09-30: `ss-75`, `ss-76`,
  `temporal-04`, `temporal-09`, `temporal-10`, `temporal-11`, `temporal-13`);
- what `decisions/0010` actually protects is **preserved**: all three arms stopped and
  resumed at the same question boundary with identical qid sets, so every
  candidate-vs-control pair is between arms run in the same session as each other;
- what is lost is cross-session comparability *within* the pooled estimate: if the
  endpoint drifted between 09-24 and 09-30, that drift enters the 7 tail questions.
  Evidence against drift, not proof: the `expected_model` guard quarantined **0 of 60**
  records in all three arms, and the noise floor is +0.000 pooled;
- the 7 tail questions are 2 `single_silo` and 5 `temporal`. Both slices come out at
  **exactly 0.000** candidate-vs-control, so the tail contributes nothing to the primary
  effect either way. The verdict does not rest on the deviating records.

### Primary — `refusal_correct` on `shipped`, candidate − control `_a`

| comparison | effect [95% CI] | noise floor |
|---|---|---|
| pooled dev (n=60) | **+0.033 [−0.050, +0.133]** | +0.000 [−0.050, +0.050] |
| `out_of_scope` (n=12) | **+0.250 [+0.000, +0.500]** | +0.000 [+0.000, +0.000] |

Same statistic on the other two channels, pooled: `frozen` +0.000 [−0.067, +0.067],
`t40` +0.000 [−0.067, +0.067]. On `out_of_scope` both read **−0.167 [−0.417, +0.000]** —
the prose-matching channels score the candidate *worse* there, because with its trailing
line stripped its abstention wording is less recognisable to a regex than the control's.
That is the blind spot T41 measured, reproduced from the other side: the win is only
visible if you read the field.

### Per slice (`shipped`)

| slice | n | effect [95% CI] |
|---|---|---|
| `out_of_scope` | 12 | +0.250 [+0.000, +0.500] |
| `multi_turn` | 3 | +0.333 [+0.000, +1.000] |
| `single_silo` | 16 | +0.000 [+0.000, +0.000] |
| `adversarial` | 5 | +0.000 [+0.000, +0.000] |
| `exact_match` | 5 | +0.000 [+0.000, +0.000] |
| `temporal` | 5 | +0.000 [+0.000, +0.000] |
| `cross_silo` | 14 | **−0.143 [−0.429, +0.143]** |

The whole pooled effect is **2 net question flips out of 60**: +3 on `out_of_scope`,
+1 on `multi_turn`, −2 on `cross_silo`. T41's prefix arm lost `cross_silo` at −0.500
[−0.786, −0.214]; the suffix form cuts that to −0.143 but does not remove it.

### Per arm

| | candidate | control `_a` | floor `_b` |
|---|---|---|---|
| `refusal_correct[shipped]` | 0.917 [0.850, 0.983] | 0.883 [0.800, 0.950] | 0.883 [0.800, 0.950] |
| `refusal_correct[frozen]` | 0.883 [0.800, 0.967] | 0.883 [0.800, 0.950] | 0.883 [0.800, 0.950] |
| protocol violations | **0/60** | n/a | n/a |
| field present | 60/60 | 0/60 | 0/60 |
| out-of-scope answered | **0/12** | 3/12 | 3/12 |
| field vs `t40` disagreements | 8 | 0 | 0 |
| faithfulness, answered in-scope | 0.603 [0.484, 0.720] (n=43) | 0.555 [0.429, 0.680] (n=44) | 0.515 [0.388, 0.643] (n=44) |
| median `completion_tokens` | 69.0 [63.0, 96.0] | 62.0 [51.0, 73.0] | 60.5 [48.0, 73.0] |
| median `wall_s` | 1.180 [1.106, 1.318] | 1.197 [1.139, 1.241] | 1.040 [0.962, 1.187] |
| quarantined (model drift) | 0/60 | 0/60 | 0/60 |

### The five criteria, scored

| # | criterion | result | verdict |
|---|---|---|---|
| 1 | pooled gain beats the floor's magnitude **and** its CI excludes 0 | +0.033 beats a 0.000 floor, but CI [−0.050, +0.133] **contains 0** | **FAIL** |
| 2 | out-of-scope answered does not increase | 0/12 against the control's 3/12 — it fell | PASS |
| 3 | faithfulness does not fall by more than the floor's magnitude | +0.048 above the control (floor magnitude 0.040); it rose | PASS |
| 4 | protocol violations ≤ 10% | 0/60 = **0%** | PASS |
| 5 | tokens not below the control beyond the floor, **and** no content lost in triage | paired `completion_tokens` **+16.12 [+5.27, +25.32]** (floor −1.75 [−12.33, +6.12]); triage finds **0** content losses | PASS |

One failure is a rejection, as fixed before the run.

### The hand triage, pre-registered and done (`docs/t41b_abstain_triage.md`)

5 in-scope answers carry a trailing `DECISION: ABSTAIN`. All five classified by hand
against what control `_a` wrote for the same question:

| class | n | cases |
|---|---|---|
| control also refused | 2 | `adversarial-01`, `cs-28` (bodies near-identical; `cs-28`'s is identical) |
| **content lost** | **0** | — |
| label disagrees with its own body | 3 | `cs-14`, `cs-26`, `cs-63` |

**This is the result the variant was built to get, and it got it.** T41's prefix arm had
5 content losses out of 12 in-scope abstentions; the suffix arm has **0 out of 5**, and
writes 16 tokens *more* than the control rather than 10 fewer. `cs-14` is the clearest
case: under an `ABSTAIN` label the candidate wrote 122 tokens including the Division of
Education's role in licensure, where the control wrote 67 and stopped at the gap. The
diagnosis in `decisions/0017` — that the prefix form's damage came from committing
before writing, not from labelling as such — is confirmed.

The 3 remaining mislabels are the inverse error, and they are what sinks criterion 1.
In each, the body is a partial answer that notes a gap — precisely the case this
prompt's "if your reply answers the question even partly ... write `DECISION: ANSWER`"
clause was added to resolve — and the model labelled it `ABSTAIN` anyway. Since these
are in-scope, each one converts a question the control got right into one the candidate
gets wrong, and all three fall in `cross_silo`. The added wording reduced this failure
mode without eliminating it. A third attempt would be a third variant of the same idea,
which the stopping rule does not permit.

### Why this is a rejection and not a near-miss worth one more rung

The candidate is genuinely better at the thing it was built for: it never answers an
out-of-scope question (0/12 against 3/12) and its field is perfectly reliable (60/60).
But `refusal_correct` is the pre-registered primary, and on it the candidate buys 4
questions and gives back 2, for a net 2 of 60 with a CI straddling zero. On a
60-question dev split that is indistinguishable from no effect, and `decisions/0011` is
explicit that a more expensive rung which does not beat the cheaper one gets no further
turn — and the suffix arm is more expensive, at +16 completion tokens per answer.

The honest summary is narrower than "labelling does not work": **self-labelling fixes
the out-of-scope blind spot and introduces an in-scope one of comparable size.** The
model is better at noticing that it has nothing to say than at noticing that what it
just wrote was in fact an answer. That is worth recording as a finding about the model,
not only as a verdict about a prompt.

### Not adopted, and what stays as it was

`SCOPE_STRICT_SYSTEM_PROMPT` and the frozen generation config (`decisions/0014` rung 1)
are **untouched**. `SUFFIX_DECISION_FIELD_SYSTEM_PROMPT` and
`SuffixDecisionFieldClassifier` are kept in the tree, marked rejected, wired nowhere —
the same convention as the rejected v1-v3 classifiers in `decisions/0016` and T41's
prefix prompt. The parse rules and their 24 tests stay: they are the evidence the field
was read strictly rather than generously.

### Verification

Run dirs `runs/20260924T143258Z_b8758fe076af` (candidate), `…_a5f129337e5f` (control
`_a`), `…_2e5268506548` (floor `_b`) — 60 records each, with corpus/model/split locks
and a `PROVENANCE.txt` recording the two-session write. Analysis:
`runs/t41b_suffix_field_analysis.json`. Triage: `docs/t41b_abstain_triage.md`.
(`runs/` is gitignored; the artifacts are on disk.)
