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

**Run:** 2026-09-24, 180 live dev calls, all three arms completed, none quarantined.
Run dirs `runs/20260924T140930Z_663bed2da821` (candidate),
`…_9b1a6dd804d0` (control `_a`), `…_ef32c7a015e1` (noise floor `_b`).
Analysis: `runs/t41_decision_field_analysis.json`.

**Verdict: rejected.** Criterion 1 fails — the pooled primary effect is *negative*.
The frozen prompt stays as `decisions/0014` left it, and
`DECISION_FIELD_SYSTEM_PROMPT` / `DecisionFieldClassifier` stay in the tree unwired,
as the rejected v1–v3 classifiers of `decisions/0016` do.

### Primary: `refusal_correct` on the `shipped` channel, candidate − control `_a`

| scope | effect | noise floor |
|---|---|---|
| pooled dev (n=60) | **−0.083 [−0.200, +0.033]** | +0.000 [+0.000, +0.000] |
| `out_of_scope` (n=12) | **+0.333 [+0.083, +0.583]** | +0.000 [+0.000, +0.000] |
| `cross_silo` (n=14) | **−0.500 [−0.786, −0.214]** | +0.000 [+0.000, +0.000] |
| `multi_turn` (n=3) | −0.333 [−1.000, +0.000] | +0.000 |
| `adversarial` (n=5) | −0.200 [−0.600, +0.000] | +0.000 |
| `single_silo`, `exact_match`, `temporal` | +0.000 | +0.000 |

### The four criteria, scored

| criterion | result |
|---|---|
| 1. pooled gain beats the noise floor, CI excludes 0 | **FAIL** — effect is −0.083 and its CI spans 0 |
| 2. out-of-scope answered does not increase | pass — **0/12** vs 4/12 for both control passes |
| 3. faithfulness does not fall by more than the floor | pass — frozen-channel paired effect +0.008 [−0.114, +0.129] |
| 4. protocol violations ≤ 10% | pass — **0/60**; the field was present and well-formed every time |

One failure is a rejection. It is not close on the criterion that decides it, and the
pre-registered design gives this candidate no second turn.

### Per arm

| | candidate | control `_a` | noise floor `_b` |
|---|---|---|---|
| `refusal_correct` (shipped) | 0.800 [0.700, 0.900] | 0.883 [0.800, 0.950] | 0.883 [0.800, 0.950] |
| `refusal_correct` (frozen) | 0.883 [0.800, 0.950] | 0.883 | 0.883 |
| out-of-scope answered | **0/12** | 4/12 | 4/12 |
| in-scope refused | **12/48** | 3/48 | 3/48 |
| median completion tokens | **53.5 [42, 67]** | 63.5 [57, 75] | 63.0 [56.5, 75] |
| median wall seconds | 1.214 [1.102, 1.283] | 1.095 [0.963, 1.250] | 1.035 [0.919, 1.173] |

Paired cost, frozen-channel comparison: completion tokens **−21.2 [−44.3, −3.9]**,
wall **+0.410 s [+0.053, +0.869]** — fewer tokens, yet slower, which is queueing on the
free tier's single concurrency slot, not generation work (`Usage.timing_source` is our
stopwatch, an upper bound on GPU time). Citation accuracy +0.034 [+0.000, +0.086],
validity unchanged.

### Why it lost: the field changes what the model writes, not only what it labels

The per-arm faithfulness figures look like a win for the candidate (0.706, n=36 vs
0.562, n=45). They are not comparable: the denominators differ *because* the candidate
abstained on 9 more in-scope questions, so it is scored on an easier subset. Selection,
not quality.

Hand triage of the **12 in-scope questions the candidate self-labelled ABSTAIN**,
against what control `_a` wrote for the same question:

- **7 were prose refusals in the control too** (`adversarial-01`, `cs-14`, `cs-25`,
  `cs-26`, `cs-28`, `cs-63`, `cs-70`). Nothing was lost here; the control was simply
  not *detected* as refusing.
- **5 lost substantive content the control supplied**: `adversarial-25` (control
  corrects the question's false premise in full, with the registrar URL; candidate
  gives the correction stripped of policy and citation), `pilot-cs-01` (control gives
  two named contacts with phone and email), `pilot-cs-06` (control gives the meal-plan
  change policy and two sources), `mt-07` (control gives the full GPA/test-score
  requirement table), `mt-08` (control gives the scholarship ranges). In every one the
  control answered *and then* noted the gap; the candidate, having committed to
  ABSTAIN on line one, stopped.
- **1 field was not truthful about its own body**: `pilot-cs-06`'s candidate text does
  state the meal-plan policy, then says the passages do not address celiac exemptions —
  and labels the whole thing ABSTAIN. Reading the field there would route an answer
  that exists to the office queue.

That is the mechanism, and it explains the token drop and the `cross_silo` collapse
together: cross-silo questions are exactly the ones that need two partial passages
stitched together, and an up-front commitment to abstain is made before the stitching
is attempted. `decisions/0014` rung 3 and `decisions/0009` both failed this same way —
a mechanism that fixes `out_of_scope` by refusing more broadly is not a fix.

### The confound, stated rather than exploited

The pooled comparison is **partly** an artifact, and honesty cuts both ways here:

Replaying the *broad* `WidenedPhraseClassifier` pattern (v1, rejected in
`decisions/0016`) offline over both arms' stored text: in-scope prose refusals are
**5 (candidate) vs 4 (control)**, out-of-scope **9 vs 8**. By that reading the two
prompts refuse at nearly the same rate, and almost all of the pooled gap is the control
being *credited with answering* on questions where it refused in prose the shipped
classifier cannot see. `refusal_correct` on the control measures "the detector noticed
nothing", not "the model answered".

So the metric flatters the control. It does **not** rescue the candidate: the
`cross_silo` collapse, the 5 hand-verified content losses and the −21-token median are
measured on the text itself and survive any choice of detector. The candidate is
rejected on what it wrote, not on how it was scored. Resolving the confound properly
would need human refusal labels on dev answers, which this project does not have —
recorded in `docs/LIMITATIONS.md`, not fixed here.

### Side finding: the noise floor was exactly zero

The two identical control passes agreed on the refusal decision for **60/60** questions
on all three channels, and produced byte-identical text for 38/60
(`exact_text_match` 0.633; faithfulness floor ±0.026, tokens ±5). At temperature 0 the
refusal decision was perfectly stable this session. That is a stronger determinism than
`decisions/0008` assumed, and it has a cost for this design: a zero-width floor gives
criterion 1 nothing to clear, so the CI does all the work. Both are reported above.
One session is not evidence that the endpoint is deterministic in general — the
`decisions/0008` policy of running a noise-floor twin stands.

### Logged, not run

Two variants would separate labelling from content commitment, and neither gets a call
without its own pre-registration and an explicit go-ahead:

1. **Suffix field** — the decision line goes *after* the answer, so the model writes
   first and labels second. Directly targets the mechanism found above.
2. **Three-valued field** — `ANSWER | PARTIAL | ABSTAIN`, so "here is what I have, and
   here is the gap" has somewhere to go. `pilot-cs-06` is the case that asks for it.

What T41 does leave standing: on `out_of_scope` the field caught **12/12** against the
shipped classifier's 8/12, with the CI excluding zero. The layer-5 blind spot is real
and measurable. This prompt is not the way to close it.
