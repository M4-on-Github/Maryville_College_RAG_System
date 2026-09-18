# 0010 — Metered ablations #8, #9, #10 (Task 22)

**Date:** 2026-09-17 · **Status:** run complete, results recorded. Config selection for Checkpoint E is a separate, still-open decision — this doc reports findings, it does not freeze a config.

## Context

Task 22 runs the dev-split half of PLAN's metered ablations (`decisions/0006`
addendum 3: dev only, selection not inference — the 120-question test split
is reserved for Task 22b, after Checkpoint E). This doc covers #8
(citation-forced vs free-form prompting), #9 (Task 21's abstention gate vs
always-answer), and #10 (generation model comparison). #6 (query
reformulation) is scoped separately.

Two human decisions set the shape of this doc before it was written:
1. **#10 is a real model comparison, not "heavy vs one lighter model."**
   Checked against Ollama Cloud's live `/v1/models` list (2026-09-17): four
   real, available tags — `gpt-oss:20b` (current baseline), `gpt-oss:120b`,
   `gemma4:31b`, `nemotron-3-nano:30b`. (`nemotron-3-super`/`-ultra` exist
   too; out of scope for now, per the reviewer.)
2. **#8's citation format: numbered `[N]` markers**, keyed to the same
   passage numbering `build_user_prompt` already stamps on every passage —
   not a bare-URL requirement or a structured answer object. Graded by
   `mcrag.eval.tier0_scoring.score_citation_markers` (fraction of factual
   sentences carrying a valid marker).

## Design

### One interleaved sweep, six arms

Everything in this doc's live pass is dev-split-only, at the frozen
retrieval config (`decisions/0007`), through `mcrag.eval.ablation_runner.run_interleaved`
(question-major order; `model.lock` re-checked per record via the new
per-arm `expected_model` dict, since #10 deliberately mixes models):

| Arm | Model | Prompt | Purpose |
|---|---|---|---|
| `free_form_20b_a` | gpt-oss:20b | free-form (Task 20's) | #8/#9/#10's shared reference |
| `free_form_20b_b` | gpt-oss:20b | free-form, identical config to `_a` | **noise floor**, this session |
| `citation_forced_20b` | gpt-oss:20b | citation-forced (`[N]` markers) | #8 |
| `free_form_120b` | gpt-oss:120b | free-form | #10 |
| `free_form_gemma4_31b` | gemma4:31b | free-form | #10 |
| `free_form_nemotron3_nano_30b` | nemotron-3-nano:30b | free-form | #10 |

`free_form_20b_a` is run fresh this session rather than reusing Task 20's
older control, so every comparison in this doc is paired against data from
the *same* session, same `model.lock`, same rerun conditions — not against a
different day's run. `free_form_20b_b` is a second, independent pass of the
identical config, generated fresh (never through a cache — `decisions/0008`:
a cached rerun is identical by construction and would hide the exact
variance being measured) — its difference from `_a` is this sweep's own
noise floor, reported beside every effect below, not borrowed from Task 20's.

All six arms answer the full 60-question dev split — out-of-scope questions
included, since refusal behavior is part of what's being measured.
`quota_errors` pauses the sweep cleanly on a real wall; resuming continues
the same interleaved queue, not a restart.

### #8 — Citation-forced vs free-form

**Comparison:** `citation_forced_20b` vs `free_form_20b_a`.
**Outcomes** (paired bootstrap, effect + CI, no p-value — dev is selection):
- `citation_marker_compliance` (new metric; `free_form_20b_a` is expected
  near zero, since its answers occasionally emit a different bracket style,
  `【N】`, that `score_citation_markers`'s `\[(\d+)\]` pattern does not match —
  a real, if incidental, zero rather than a broken check)
- Tier 0 `citation_accuracy`/`citation_validity` — does forcing citations
  change whether the *cited* sources are actually correct, not just present
- Tier 1 faithfulness (answered questions only, unvalidated, per `decisions/0008`)
- `refusal_rate`, `refusal_correct`

### #9 — Task 21's gate vs always-answer

**Not a new arm.** PLAN Sec 4a #3: "generate once for the queries passing
the loosest τ and reuse those outputs at every threshold" — the gate's
answered-subset needs no new generation, since it is the *same* prompt,
model, and config as `free_form_20b_a` for every question it doesn't refuse.
Derived, zero quota, from two things already on disk after the live pass:
- `free_form_20b_a`'s per-question answers and Tier 0/1 scores (this doc's own).
- The frozen gate (`decisions/0009`): raw cross-encoder MaxP score ≥ 4.96 →
  answer; else refuse. Scores for the 60 dev questions are already stored,
  per question, in Task 21's run (`runs/20260917T133042Z_340a8f03a310`).

**Construction:** for each dev question, `gate` = `free_form_20b_a`'s record
if the gate says answer, else a synthetic refusal (no generation, `answer`
omitted, `tier0.refused = True`). `always_answer` = `free_form_20b_a` as-is.
**Outcomes** (paired bootstrap, effect + CI): coverage, precision, and
false-refusal rate in Task 21's own terms (`should_answer` =
`all_golds_retrieved@5 == 1.0`, not Tier 0's coarser `expects_answer`, so
this is directly comparable to `decisions/0009`'s numbers); plus
`refusal_correct` (Tier 0's `expects_answer` definition, for continuity with
#8/#10's other rows) and faithfulness on the answered subset.
**Labelled in-sample**, per `decisions/0009`: τ was fitted on train+dev,
dev included.

### #10 — Generation model comparison

**Comparisons:** each of `free_form_120b`, `free_form_gemma4_31b`,
`free_form_nemotron3_nano_30b` vs `free_form_20b_a`.
**Outcomes** (paired bootstrap, effect + CI, per comparison): faithfulness,
`refusal_rate`, `refusal_correct`, citation accuracy/validity, and — per
PLAN Sec 4b — reasoning-token share and wall-clock cost, since Task 20 found
83% of `gpt-oss:20b`'s output is hidden reasoning and a model swap is
expected to change that ratio.
**Reported by slice, not only pooled**, per PLAN Sec 4a #10's own
prediction: "expect the abstention and cross-silo slices, not the
single-silo factual slice, to separate them." The pooled number is
secondary to the by-slice breakdown here.
**Retrieval is not re-measured per model** — it is frozen and
model-independent; each arm's `all_golds_retrieved@5` is logged once as a
sanity check (expected 0.708, matching every prior task) and not treated as
a per-arm finding.

### What governs every comparison in this doc

- **Dev is selection, not inference** (`decisions/0006`): every number above
  is an effect size with a bootstrap CI, never a p-value.
- **The noise floor is reported beside every effect** (`free_form_20b_b` vs
  `free_form_20b_a`, this session's own): an effect whose interval overlaps
  the noise floor's is not distinguished from rerunning the same config.
- **Faithfulness stays unvalidated and answered-only**, `refusal_rate`
  reported beside it (`decisions/0008`).
- **`model.lock` drift is checked per record**, per arm's own expected
  model (`run_interleaved`'s `expected_model` dict, Task 22's own fix — a
  single global expected model would have wrongly flagged every #10 arm as
  drifted). A quarantined record is kept on disk, excluded from aggregates,
  logged in the summary.

## Results

*Pending — to be added below this line, without editing anything above.*

*Added 2026-09-17, after the run. Nothing above was edited.*

Run: 6 interleaved arms (`runs/20260917T193056Z_*`), 360 generation calls,
22.6 min total wall-clock (well under the Task 3 budget). Interleaving held:
question-major order, confirmed live from the growing record counts, no two
consecutive calls sharing a config. One quota-class failure (a `ReadTimeout`
on `gemma4:31b`, 180s default too tight for a model `docs/quota-calibration.md`
never calibrated) paused the sweep cleanly at 21/22 questions; fixed by
widening `quota_errors` to catch `requests.exceptions.RequestException` and
raising `timeout_s` to 300s, then resumed with zero duplicate calls. Zero
records quarantined — no model drift detected across the whole sweep.
Full analysis: `runs/t22_metered_ablations_analysis.json`.

### A bug caught before it reached this doc

The first computed version of #9's `gate_minus_always_answer` had the wrong
sign: `paired_bootstrap_comparison(a, b)` returns `b - a`, and the helper
passed `(gate, always)` while labelling the result "gate minus always" —
silently computing `always - gate` instead. Caught by a plain sanity check
(the printed diff's sign didn't match the two point estimates it was
supposedly the difference of), fixed in `scripts/run_t22_metered_ablations.py`,
and the analysis recomputed from the already-stored records — no
re-generation, no quota spent on the fix. The numbers below are post-fix.

### Noise floor (this session)

| Metric | free_form_20b_b − free_form_20b_a |
|---|---|
| refusal_correct | −0.017 [−0.083, +0.050] |
| faithfulness | +0.022 [−0.043, +0.089] |
| wall_s | +1.48 [−0.12, +4.07] |
| completion_tokens | +13.2 [−7.5, +35.1] |

Every interval covers zero, as it should for two runs of the identical
config. This is the band every effect below is read against.

### #8 — citation-forced vs free-form

| Metric | citation_forced − free_form |
|---|---|
| marker compliance | **0.527 [0.429, 0.624]** (free-form: undefined — no `[N]` markers at all) |
| refusal_correct | −0.083 [−0.183, +0.017] |
| faithfulness | −0.013 [−0.102, +0.077] |
| wall_s | **−0.78 [−1.32, −0.26]** |
| completion_tokens | **−56 [−100, −16]** |
| reasoning_char_share | **+0.097 [+0.070, +0.124]** |

**Forcing citations partially works and changes nothing else measured.**
Even under an explicit, worked-example instruction, `gpt-oss:20b` complies
on barely half its citable sentences — not a broken check (`n_invalid_markers`
is 0 across all 60 answers; every marker it does emit is valid), a real
instruction-following ceiling on this model at temperature 0. Tier 0
citation_accuracy/citation_validity could not be paired at all: the forced
arm mostly stopped emitting bare URLs (the free-form metric), and its
bracket markers are a different signal the URL-based check cannot see. No
faithfulness or refusal-correctness effect outside the noise floor. The one
robust effect is operational: citation-forced answers are shorter and
faster, with a *larger* share of reasoning relative to visible text — the
instruction seems to compress the answer more than it compresses the
reasoning behind it.

### #9 — Task 21's gate vs always-answer

| | coverage | precision (T21's `should_answer`) | refusal_correct (Tier 0's `expects_answer`) | faithfulness (answered) |
|---|---|---|---|---|
| always_answer | 1.000 | 0.567 | 0.867 | 0.497 |
| gate (τ=4.96) | 0.267 | 0.938 [0.789, 1.000] | 0.467 | 0.591 |
| **gate − always_answer** | | | **−0.400 [−0.550, −0.233]** | |

Coverage (0.267, 16/60) and precision (0.938) match `decisions/0009`'s dev
in-sample numbers exactly — the two independently-built scripts agree,
which is itself a useful cross-check.

**The gate looks far worse on Tier 0's `refusal_correct` and far better on
its own `should_answer` precision, and both are correct — they are
different questions.** `expects_answer` (Tier 0) is `bool(question.gold)`:
any question with a gold ref "should" be answered. `should_answer` (Task 21)
is stricter: *only if every gold passage was actually retrieved.* The gate
refuses plenty of questions that have gold refs but incomplete retrieval —
Tier 0 counts every one of those as a wrong refusal, while Task 21 counts
each as the gate doing exactly its job (declining to answer on evidence it
doesn't have). This is the gap `decisions/0009`'s Finding 5 already named
for the adversarial slice; #9 shows it is not confined to that slice. The
−0.400 is real and large, but it is not evidence the gate is failing;
`decisions/0009` is the more trustworthy read of what the gate does, and it
already recorded that the gate misses its own 80% precision floor out of
fold (0.786) — this run's 0.938 is the in-sample number the same doc warned
would look optimistic.

### #10 — model comparison (pooled; by-slice is underpowered, see below)

| Model vs gpt-oss:20b | faithfulness | reasoning_char_share | wall_s | completion_tokens |
|---|---|---|---|---|
| gpt-oss:120b | **−0.182 [−0.307, −0.064]** | **−0.086 [−0.124, −0.048]** | **−3.95 [−4.56, −3.39]** | **−120 [−162, −80]** |
| gemma4:31b | −0.033 [−0.151, +0.081] | **−0.731 [−0.762, −0.701]** | **−4.42 [−5.08, −3.79]** | **−301 [−348, −256]** |
| nemotron-3-nano:30b | **−0.116 [−0.219, −0.014]** | −0.001 [−0.032, +0.029] | **−2.57 [−3.23, −1.88]** | +36 [−6, +79] |

(Bold = interval excludes zero *and* clears the noise floor's magnitude.)

**gemma4:31b is the standout finding.** Its faithfulness is statistically
indistinguishable from `gpt-oss:20b` (interval comfortably inside the noise
floor), while its reasoning-channel share collapses by 73 points — it is
architecturally not a heavy chain-of-thought model on this endpoint, the way
`gpt-oss` is — and it is both the fastest arm and by far the cheapest in
tokens. On this dev split, gemma4:31b delivers the same measured quality for
a fraction of the cost. That is a real, statistically supported result, not
a hunch — and directly actionable for Checkpoint E.

**Both `gpt-oss:120b` and `nemotron-3-nano:30b` score *lower* faithfulness
than the smaller `gpt-oss:20b` baseline**, robustly. Neither is a claim that
bigger is worse in general — faithfulness is `decisions/0008`'s unvalidated
metric, reported here only as a paired difference, per that doc's own rule.
It is a real, reproducible-within-this-session difference in how these
models' answers are phrased against the NLI checker, worth a note for
whoever revisits model choice, not a verdict on model quality.

**120b being faster than 20b is real and explained, not a measurement
artifact.** It also produces far fewer completion tokens and a smaller
reasoning share — a larger model reasoning more concisely, not a serving
anomaly (nothing in `docs/quota-calibration.md`'s cost model can separate
provider-side infrastructure differences from this, so the mechanism is not
fully attributable, but the token/time correlation within this run is internally consistent).

**The by-slice breakdown (full table: `runs/t22_metered_ablations_analysis.json`)
neither confirms nor refutes PLAN Sec 4a #10's prediction** that abstention
and cross-silo slices, not single-silo, would separate the models. Every
per-slice cell here is n=3 to n=16, giving wide CIs that mostly cover zero
regardless of slice — including cells with large point estimates (e.g.
`gpt-oss:120b` on `temporal`, −0.500 faithfulness at n=5). Reported as
exploratory, not as a slice-level finding: at dev-split-divided-by-seven-slices
sample sizes, no per-slice comparison here clears its own noise bar.
