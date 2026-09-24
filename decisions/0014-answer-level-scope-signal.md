# 0014 — Answer-level out-of-scope signal (Task 22c)

**Date:** 2026-09-24 · **Status:** ladder closed. Rungs 0–3 all run. Rung
0 (zero quota) and rung 2 (zero quota, calibrated fit) both
diagnostic/rejected; rung 3 (209 dev calls: 89 gate-arm + 60 + 60
reference-arm passes) fully closes the `out_of_scope` gap but at the worst
collateral cost of any rung tried and is **not kept**.
Rung 1 (180 dev calls) remains the only rung **kept** — real,
collateral-free, does not close the gap alone. **Adopted config:
`scope_strict_gemma4_31b` (rung 1's prompt), un-stacked.** No further rung
is planned; the ladder's own stopping rule (`0011`: a more expensive rung
that doesn't beat the cheaper one doesn't get another turn) applies now
that the most expensive rung in the pre-registered design has been tried
and lost.

## Context

T22b's confirmatory pass (`decisions/0013`) found, on the frozen Checkpoint-E
config against test: 100% of false-answer errors (17/120 frozen-arm,
14/120 baseline-arm) are `out_of_scope`. `decisions/0009` (T21) already
tested the obvious fix — a pre-generation gate on retrieval/cross-encoder
relevance — exhaustively, across every method PLAN specified, and rejected
it: best case AUC 0.717–0.743 discriminating in-scope vs out-of-scope,
no method clears even an 80% precision floor out of fold, and the
adopted candidate (τ=4.96) would cost 62% false-refusal at only 23%
coverage. `0009`'s own conclusion: *"a retrieval-score threshold cannot
reach 95%; answer-level signals (self-refusal, NLI, or LLM answerability)
are the route to higher precision."* That route has never been built.
This doc scopes it, on dev only, same rigor as `0009`/`0011`: design
pre-registered before any step's result is seen, cumulative ladder,
noise floor reported beside every effect.

## Rung 0 — does an answer-level signal even separate these cases? (zero quota)

Before building anything, checked offline whether a signal the project
already computes for every generated answer — Tier 1 NLI faithfulness
(`decisions/0008`) — already separates false-answer `out_of_scope` cases
from everything else, using every dev-split generation run already on
disk (no new calls): T20's control + null-arm rerun, and all six of T22's
arms (`citation_forced_20b`, `free_form_120b`,
`free_form_nemotron3_nano_30b`, `free_form_gemma4_31b`, `free_form_20b_a`,
`free_form_20b_b`) — 8 runs × 12 `out_of_scope` dev questions = 96
attempts.

| | n | faithfulness (answered only) |
|---|---:|---|
| `out_of_scope`, correctly refused | 45 | — (excluded, `decisions/0008`) |
| `out_of_scope`, **wrongly answered** | 51 (50 scoreable) | mean **0.177**, median **0.000**, 68% (34/50) exactly 0.0 |
| in-scope, correctly answered (reference) | 360 | mean 0.476, median 0.500, 26.1% (94/360) exactly 0.0 |

A naive post-hoc rule — *refuse if faithfulness == 0.0* — simulated
against this same stored data: **catches 68% (34/50) of false-answer
`out_of_scope` cases, at a cost of wrongly flagging 26.1% (94/360) of
legitimately-answered in-scope questions.**

**Reading this honestly, both ways:**
- There is real, answer-level signal here, measurably stronger separation
  than the retrieval-side cross-encoder ever showed (`0009`'s AUC
  0.717–0.743 on the *retrieval* side translates, on the *answer* side, to
  a 68%-vs-26% split — not overlapping distributions, but not clean
  either). This is enough to justify building rung 1, not enough to adopt
  anything yet.
- 26.1% false-refusal on legitimately answerable questions is still a real
  cost, not a free lunch — smaller than the CE gate's 62% (`0009`), but
  not small.
- This threshold (exactly 0.0) was picked *after* looking at the numbers,
  on the full sample, with no train/dev split — the same "chosen after
  seeing the result" risk `0009`'s Task 21 exists to avoid. **This rung is
  diagnostic only: it establishes that an answer-level signal is worth
  pursuing, and is not itself proposed for adoption.**
- It inherits Tier 1's own, already-flagged validity problem (`0008`
  Finding 2, `0012`): Spearman vs human judgment failed its own
  significance floor twice. 26.1% of *correct* in-scope answers already
  score exactly 0.0 — consistent with Tier 1 under-crediting plainly
  grounded claims in ways `0008` partially fixed (v1→v3) but never fully
  resolved.
- `pilot-oos-06` scores 1.0 (perfect apparent faithfulness) in 4 of 8 arms
  despite being a false-answer `out_of_scope` case in all 8 — a concrete
  example of what "not clean" means: some fabricated-but-fluent answers to
  unanswerable questions land on passage text confidently enough that NLI
  entailment doesn't catch them either. No signal tested so far is
  expected to close 100% of this gap.

## Ladder design for rungs 1+ (pre-registered before any of them run)

Same cumulative-ladder method as `decisions/0011`: each rung compared
against the best config *so far*, on dev, effect size + CI only (dev is
selection, not inference — `decisions/0006`). **Unlike `0011`'s free
rungs 1–2, every rung here involves an LLM call** (there is no
deterministic step in this ladder), so every rung needs its own
same-session noise-floor rerun before evaluation — the metered-rung
protocol from `0010`/`0011`, applied from rung 1 onward, not just the
expensive end.

**Target metric:** `out_of_scope` false-answer rate (i.e. 1 − refusal
rate restricted to `out_of_scope`, Tier 0's `refused` field) is primary.
Reported *beside* pooled `refusal_correct`, `faithfulness`, and
`citation_accuracy`/`citation_validity` on the full dev split every
time — a rung that fixes `out_of_scope` by making the model refuse
everything is not a win, the same lesson `0009`'s coverage collapse
already taught. A rung is kept only if it improves the target metric
without a collateral drop elsewhere that isn't inside that rung's own
noise floor.

### Rung 1 — strengthened refusal instruction (prompt-only, no new component)

Cheapest possible arm: an edit to `mcrag/generate/prompting.py`'s
`SYSTEM_PROMPT`, structurally identical in kind to ablation #8's
citation-forced variant (`decisions/0010`) — a new prompt constant, zero
new code paths, still the existing `Generator` interface. Current text
only says *"If the passages do not answer the question, say so plainly"* —
soft, and doesn't ask the model to distinguish *topically adjacent but
non-answering* passages from genuinely relevant ones, which is exactly
what retrieval hands it for an `out_of_scope` question (something always
comes back at k=5; nothing is ever an empty context). Proposed
`SCOPE_STRICT_SYSTEM_PROMPT` adds an explicit instruction to check whether
the passages actually address the question's specific subject before
answering, and to refuse rather than infer, extrapolate, or answer from
partial/tangential overlap.

**Design:** three dev arms, interleaved (`run_interleaved`, question-major,
per `decisions/0008`'s interleaving requirement): `scope_strict_gemma4_31b`
(new prompt) vs `free_form_gemma4_31b_a`/`_b` (current prompt, rerun fresh
this session for the noise floor — not reusing `0010`'s older run, per
that doc's own stated rationale: same-session pairing controls for
hosted-weight drift). Frozen retrieval (`0007`), frozen model
(`gemma4:31b`, Checkpoint E). 60 dev questions × 3 arms = 180 calls.

**Comparison:** `scope_strict_gemma4_31b` vs `free_form_gemma4_31b_a`,
`out_of_scope` false-answer rate primary; pooled `refusal_correct`,
faithfulness, citation metrics secondary; noise floor from the `_b` pair.

### Rung 2 — calibrated post-hoc faithfulness override (if rung 1 doesn't close the gap alone)

Not exclusive with rung 1 — can stack on whichever prompt rung 1 leaves as
best-so-far. Reuses already-built Tier 1 scoring, zero new generation
calls beyond what rung 1 already produced: after generation, if
faithfulness on the drafted answer falls below a threshold, replace the
answer with a refusal. **Must be fit properly, unlike rung 0's diagnostic
0.0 cutoff** — same train/dev-fold discipline `0009` used for τ, an
out-of-fold coverage/false-refusal curve computed before any threshold is
chosen, not read off after the fact. This is structurally the same risk
class as the rejected CE gate (a threshold that trades coverage for
precision) — the point of doing it at the *answer* level instead of the
*retrieval* level is rung 0's evidence that the separation is better
there, not an assumption that the coverage-cost problem disappears.

### Rung 3 — dedicated LLM answerability self-check (detailed design, pre-registered 2026-09-23, not yet run)

Rung 2's calibrated fit found no middle ground on the answer-level
faithfulness signal — the triggering condition this rung was reserved for.
Full design below, fixed before any call is made.

**Mechanism.** A genuine two-step pipeline, not a post-hoc override like
rung 2: for each question, call `gemma4:31b` first with a dedicated
structured-answerability system prompt and the same retrieved passages
(frozen retrieval, `decisions/0007`, `passage_chars=None`), asking only
whether the passages verbatim address the question's specific subject —
same scope-strict criterion rung 1's prompt already states, now asked in
isolation, before any answer is drafted, rather than folded into one
combined instruction. Only if that check answers YES does a second call
run: ordinary generation with `SCOPE_STRICT_SYSTEM_PROMPT` (rung 1, the
current best-so-far — rung 3 stacks on it, not on the free-form baseline).
If the check answers NO, the question is refused without a generation
call at all — the real efficiency case rung 2's post-hoc override could
never claim, since rung 2 could only override an answer already paid for.

Proposed `ANSWERABILITY_CHECK_SYSTEM_PROMPT` (not yet added to
`mcrag/generate/prompting.py` — added only with the run script, per the
same discipline rung 1's prompt constant followed):
> "You are given reference passages and a question. Decide only whether
> the passages, verbatim, contain the specific information needed to
> answer the question -- not a related or nearby topic, the actual
> subject asked about. Respond with exactly one word on the first line,
> YES or NO, and nothing else on that line. A brief one-sentence reason
> may follow on a second line."

Same model for both calls (`gemma4:31b`) deliberately — using a different,
cheaper model for the gate call would confound rung 3's own effect with an
unregistered model-choice ablation; that is a separate question this rung
does not ask.

**Parsing discipline.** The check call's first line is parsed
case-insensitively for a leading `YES`/`NO` token. Anything else
(empty completion, neither token, both) is **not** defaulted to an
answer — it is treated as NO (refuse) and flagged
`self_check_unparseable: true` on the record, reported separately from a
clean NO. Given this whole task line exists to reduce false-answers, an
ambiguous safety-relevant signal fails closed, not open; this is a design
choice made now, before any output exists to be tempted by.

**Design:** three dev arms, interleaved, all `gemma4:31b`, frozen
retrieval, full 60-question dev split:

| Arm | Purpose |
|---|---|
| `answerability_gate_gemma4_31b` | the new two-step pipeline (this rung) |
| `scope_strict_gemma4_31b_a` | rung 1's prompt alone, rerun fresh this session — the reference (best-so-far) |
| `scope_strict_gemma4_31b_b` | identical config, second live pass — noise floor for **both** calls in the new arm, since `decisions/0008` found temperature-0 is not fully deterministic on this endpoint and rung 3 has two stochastic calls per question, not one |

**Comparison:** `answerability_gate_gemma4_31b` vs `scope_strict_gemma4_31b_a`,
`out_of_scope` false-answer rate primary; pooled `refusal_correct`,
faithfulness, citation metrics secondary, same collateral-damage check
every rung has used. New metric specific to this rung, reported not
gated: **calls actually made** (self-check calls: 60 fixed; generation
calls: however many self-checks answered YES — the real cost delta
against rung 1's fixed 60, which this rung is the first to be able to
reduce rather than only add to) and a **confusion matrix** between the
self-check's NO decisions and `scope_strict`'s own in-prompt refusals, to
see whether the dedicated call catches cases the single combined prompt
missed or is mostly redundant with it.

**Cost, stated plainly:** worst case (self-check says YES every time) is
a true doubling of calls, matching `0014`'s original placeholder estimate;
typical case is fewer, since a NO skips generation entirely — the actual
number is an empirical result of this rung, not assumed in advance.

**Go-ahead given** (2026-09-24, "okay go ahead") — run and reported below.

## Results — rung 1 (2026-09-22)

**Go-ahead given.** `mcrag/generate/prompting.py`'s `SCOPE_STRICT_SYSTEM_PROMPT`
added; `scripts/run_t22c_scope_signal.py` written (mirrors
`scripts/run_t22b_test_confirmatory.py`'s structure) and run. All 180 calls
completed cleanly — no quota pause, no quarantined records in any arm.
`runs/t22c_scope_signal_analysis.json`. Run dirs:
`runs/20260922T201857Z_d6b307f5beff` (`scope_strict_gemma4_31b`),
`runs/20260922T201857Z_3caf1dd6d3bd` (`free_form_gemma4_31b_a`),
`runs/20260922T201857Z_9204bbc586dd` (`free_form_gemma4_31b_b`).

### Primary — `out_of_scope` false-answer rate, n=12

| Arm | refused | false-answer rate |
|---|---:|---:|
| `free_form_gemma4_31b_a` (reference) | 7/12 | 0.417 |
| `free_form_gemma4_31b_b` (noise floor) | 7/12 | 0.417 (identical qids to `_a`) |
| `scope_strict_gemma4_31b` | 9/12 | **0.250** |

`scope_strict - free_form_a`, `refusal_correct` on the `out_of_scope` slice
(= 1 − false-answer rate here, since `out_of_scope` has no gold):
**+0.167 [+0.000, +0.417] (n=12)**. Two questions flip from wrongly-answered
to correctly-refused (`oos-35`, `oos-36`); three remain wrongly answered in
both arms (`oos-11`, `oos-13`, `pilot-oos-06` — the same fabrication-prone
case rung 0 flagged, scoring high apparent faithfulness in 4/8 prior arms
despite being false-answer in all of them).

**Noise floor** (`_b - _a`, out_of_scope slice): **+0.000 [+0.000, +0.000]**
— the two free-form passes refused/answered the identical five questions,
zero disagreement at n=12. The primary effect's 2-question flip sits outside
this (degenerate) empirical noise floor, even though the primary CI's own
lower bound touches exactly 0.000 — an artifact of n=12 being a small,
discrete count (a single additional flip either way moves the CI a full
notch). Read honestly: a real, reproducible-looking directional
improvement, not a result that cleanly clears zero the way `0011`'s
stopping rule was written for a smoother, larger-n metric.

### Collateral check — pooled full dev, n=60

| Metric | Δ (scope_strict − free_form_a) |
|---|---|
| refusal_correct | +0.000 [−0.067, +0.067] |
| faithfulness | +0.021 [−0.058, +0.099] (n=47) |
| citation_accuracy | +0.017 [+0.000, +0.050] (n=30) |
| citation_validity | +0.000 [+0.000, +0.000] (n=30) |
| completion_tokens | **−10.767 [−19.400, −3.283]** |
| wall_s | +0.690 [−0.444, +2.534] |

No collateral drop anywhere — pooled `refusal_correct` is exactly flat
(the stricter prompt is not refusing more broadly, only more accurately on
`out_of_scope`; `0009`'s coverage-collapse failure mode does not reproduce
here). `faithfulness`/`citation_accuracy`/`citation_validity` all sit at or
inside their own noise floor (pooled noise floor: `refusal_correct` +0.000
[+0.000,+0.000], `faithfulness` −0.004 [−0.036,+0.099], `citation_accuracy`
+0.000 [+0.000,+0.000], `citation_validity` +0.000 [+0.000,+0.000]).
`completion_tokens` drops modestly and its CI excludes zero — answers get
slightly shorter, consistent with more decisive refusals, not a cost.

### Verdict

**Rung 1 is kept.** Real, collateral-free improvement on the target
metric, small in absolute terms (2/12 questions on dev) and not the kind of
result whose CI cleanly excludes zero at this n — reported as exactly that,
not spun past what n=12 can support. It does not close the gap alone:
25% of `out_of_scope` questions on dev still get a false answer under the
strict prompt, including the one case (`pilot-oos-06`) flagged from rung 0
as fabricating fluently enough to fool faithfulness scoring too. Per this
doc's own pre-registered ladder logic, this is the expected trigger for
rung 2 (calibrated post-hoc faithfulness override, stacked on
`scope_strict_gemma4_31b` as the new best-so-far) — **not run without a
separate go-ahead.**

## Results — rung 2 (2026-09-23)

**Go-ahead given.** `scripts/run_t22c_rung2_faithfulness_override.py`
written and run — **zero new generation calls**, entirely offline over
rung 1's already-generated answers and already-computed Tier 1 scores.
Reuses `mcrag.eval.abstention`'s `cross_validate`/`choose_tau` verbatim
(signal-agnostic pure functions, decisions/0009's own anti-leakage
machinery) with `feature = tier1_faithfulness`, `label = expects_answer`,
5-fold stratified-by-slice CV, seed 42, over the 47 dev records
`scope_strict_gemma4_31b` answered (44 legit in-scope, 3 `out_of_scope`
false-answers, all three scoring exactly 0.0 faithfulness — this rung's
entire test is whether a *properly cross-validated* threshold does better
than rung 0's post-hoc 0.0 cutoff at separating those 3 from the 44).
Two floors tested, per `decisions/0009`'s own history of both a 0.95
starting floor and an 80% floor adopted post hoc.
`runs/t22c_rung2_faithfulness_override_analysis.json`.

**Important small-n caveat up front:** only 3 false-answer examples exist
in this population. Every number below is driven by where a threshold
falls relative to those 3 points (and the 13/44 legit answers that also
happen to score exactly 0.0 — rung 0's finding, reproduced here). This
rejects *this exact rung-2 formulation at n=47*, not the general idea that
answer-level thresholds could work with more data.

### floor = 95% (`mcrag.eval.abstention.FLOOR`, decisions/0009's original)

Every fold's cross-validated τ lands at **0.25** — the only feature value
above 0.0 that still exists in this coarse, few-distinct-values metric.
OOF coverage-of-answered 0.660 [0.532, 0.787], precision-among-kept
**1.000** [1.000, 1.000], false-refusal-of-legit **0.295** [0.163, 0.432]
(n=44).

Applied: `out_of_scope` false-answer rate **0.250 → 0.000** (12/12 now
correctly refused — the gap fully closes on dev). But pooled
`refusal_correct` drops **−0.167 [−0.283, −0.050]** (n=60) — roughly 10 of
60 questions flip from a correct answer to a wrong refusal. Every noise
floor measured anywhere in this project (`0008`, `0010`, `0013`, this
doc's own rung 1) sits inside ±0.12; −0.167 is outside that band. This is
the identical failure shape that sank the CE gate in `0009` (there: 62%
false-refusal for 23% coverage; here: ~30% false-refusal for closing a
12-question slice) — smaller, still real, still fails the stopping rule.

### floor = 80% (`0009`'s own post-hoc-lowered floor)

Every fold's τ lands at **0.0** — i.e. "answer iff faithfulness ≥ 0.0",
which is always true. **This floor is a no-op**: the answered population's
raw precision (44/47 = 0.936) already clears 80% without any override, so
`choose_tau`'s max-coverage rule correctly declines to cut anything.
`out_of_scope` false-answer rate unchanged at 0.250; every pooled metric
Δ is exactly +0.000.

### Verdict

**Rung 2 is not kept at either floor.** There is no calibrated operating
point between "do nothing" (80% floor) and "close the `out_of_scope` gap
completely at an unacceptable collateral cost" (95% floor) — the
faithfulness feature's coarse, heavily-tied-at-0.0 distribution gives the
threshold nowhere to land in between. This is a stronger, more precise
version of rung 0's own honest caveat ("not clean... 26.1% false-refusal
is a real cost"): properly cross-validated fitting confirms the tradeoff
is exactly as stark as the naive diagnostic suggested, not better. Best
config-so-far remains **`scope_strict_gemma4_31b` alone (rung 1)**,
un-stacked. Per the pre-registered ladder logic, rung 3 (dedicated LLM
answerability self-check) is the documented next candidate.

## Results — rung 3 (2026-09-24)

**Go-ahead confirmed.** `mcrag/generate/prompting.py`'s
`ANSWERABILITY_CHECK_SYSTEM_PROMPT` added exactly as pre-registered above;
`scripts/run_t22c_rung3_answerability_gate.py` implements the two-step
pipeline. Run dirs: `runs/20260924T000403Z_a71396ad59bd`
(`answerability_gate_gemma4_31b`), `runs/20260924T000403Z_7b06f82076c9`
(`scope_strict_gemma4_31b_a`), `runs/20260924T000403Z_149ac5161451`
(`scope_strict_gemma4_31b_b`). Full analysis:
`runs/t22c_rung3_answerability_gate_analysis.json`.

### Primary — `out_of_scope` false-answer rate, n=12

| Arm | Refused | False-answer rate |
|---|---|---|
| `answerability_gate_gemma4_31b` | 12/12 | **0.000** |
| `scope_strict_gemma4_31b_a` (reference) | 9/12 | 0.250 |
| `scope_strict_gemma4_31b_b` (noise floor) | 8/12 | 0.333 |

`answerability_gate - scope_strict_a`: `refusal_correct` **+0.250
[+0.000, +0.500]** (n=12) — the gate fully closes the gap the whole
ladder exists to close, the strongest primary effect of any rung.
`completion_tokens` **−29.333 [−34.500, −24.917]** (n=12) — cheaper on
this slice specifically, since a refused-before-generating question pays
only the self-check's tokens.

### Collateral check — pooled full dev, n=60

| Metric | rung 3 − rung 1 | noise floor |
|---|---|---|
| `refusal_correct` | **−0.217 [−0.350, −0.083]** | −0.017 [−0.050, +0.000] |
| `faithfulness` (n=29) | +0.052 [−0.034, +0.155] | −0.028 [−0.105, +0.041] |
| `citation_accuracy` (n=25) | +0.020 [+0.000, +0.060] | +0.000 [+0.000, +0.000] |
| `citation_validity` (n=25) | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| `completion_tokens` | −43.517 [−64.217, −26.867] | +1.083 [−2.817, +4.867] |
| `wall_s` | +0.249 [+0.106, +0.381] | +0.287 [+0.035, +0.608] |

`refusal_correct` drops **−0.217 [−0.350, −0.083]** pooled — clearly
outside the measured noise floor (−0.017 [−0.050, +0.000]), and larger in
magnitude than rung 2's already-rejected −0.167 [−0.283, −0.050] collateral
cost at its 95% floor. This is the same failure shape every stacked
mechanism in this ladder has hit, now at its largest scale.

### Calls actually made (new metric, this rung)

| Arm | Self-check calls | Generation calls | Total | Worst case |
|---|---|---|---|---|
| `answerability_gate_gemma4_31b` | 60 | 29 | **89** | 120 |
| `scope_strict_gemma4_31b_a` (reference) | 0 | 60 | 60 | 60 |

The gate made 89 calls against rung 1's fixed 60 (+48%, not the worst-case
+100%) — real savings relative to the worst case, but still a net
*increase* in total calls versus the adopted rung-1 config, since only 31
of the 60 self-checks answered NO.

### Confusion matrix — self-check NO/YES vs `scope_strict`'s own in-prompt refusal, n=60

| | `scope_strict` refused | `scope_strict` answered |
|---|---|---|
| self-check NO | 12 | **19** |
| self-check YES | 0 | 29 |

Diagnosis: the dedicated self-check is **strictly more conservative** than
`scope_strict`'s combined prompt (zero cases where the self-check says YES
but `scope_strict` refuses), and on **19 of 60** dev questions it refuses
where `scope_strict` correctly goes on to answer. Given only 12 of those
60 questions are `out_of_scope`, essentially all 19 of those extra refusals
land on legitimate in-scope questions — exactly the false-refusal-of-legit
failure mode rung 2 hit, but from a different mechanism (isolating the
scope question from generation removes whatever context lets the combined
prompt distinguish "tangential overlap" from "the passages do address this
with inference/synthesis required") and at a larger scale (19/60 = 31.7%
vs rung 1's own residual 3/12 = 25% `out_of_scope` gap it was trying to
close).

### Verdict

**Rung 3 is not kept.** It is the only rung in this ladder that fully
closes the `out_of_scope` gap (0/12 false-answers) — the strongest primary
effect measured — but at the worst pooled collateral cost of any rung
tried (−0.217 [−0.350, −0.083], outside every noise floor measured
anywhere in this project), confirming rung 2's finding from an entirely
different mechanism: isolating the scope question from the answer either
does nothing (rung 2's 80% floor) or overcorrects into refusing legitimate
in-scope questions at an unacceptable rate (rung 2's 95% floor; rung 3's
dedicated gate). **`scope_strict_gemma4_31b` (rung 1) alone remains the
adopted config.** Per the ladder's own stopping rule (`0011`), this was
also the most expensive rung pre-registered for this task and it lost;
no rung 4 is planned.

## What this doc does not do

Rung 0 is complete and reported above (zero quota, fully reproducible from
`runs/20260917T044122Z_c1d4b7284f0f`,
`runs/phase3c_repro_check/20260917T044751Z_74a4c2fdd4e4`, and
`runs/20260917T193056Z_*`, no script committed for that aggregation —
still worth promoting to a small `scripts/` tool if this line of work
continues). Rung 1 is complete and script-backed
(`scripts/run_t22c_scope_signal.py`) and is the **adopted config**. Rung 2
(`scripts/run_t22c_rung2_faithfulness_override.py`) and rung 3
(`scripts/run_t22c_rung3_answerability_gate.py`) are both complete,
script-backed, and **not kept** — every answer-level mechanism this ladder
tried beyond rung 1's prompt-only edit traded `out_of_scope` false-answers
for in-scope false-refusals at a cost this project's own noise floor
cannot absorb. The ladder is closed; Task 22c's residual `out_of_scope`
gap (25% of that slice, 3/12 dev questions) is accepted as a known,
documented limitation rather than further chased — the honest finding of
this whole task is that the signal genuinely separating these cases
(Tier 1 faithfulness, rung 0) is too coarse to calibrate a threshold on
(rung 2) and too context-free to isolate without collateral damage
(rung 3), not that no one tried.
