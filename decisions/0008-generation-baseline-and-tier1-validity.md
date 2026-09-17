# 0008 — Phase 3c generation baseline, Tier 1 validity, and the rerun noise floor (Task 20)

**Date:** 2026-09-17 · **Status:** accepted — three decisions resolved by the human reviewer the same day (see **Resolution**, end of doc). Findings 1–5 are left as found; the control numbers in the Resolution supersede the table under "The control condition".

## Context

Task 20 runs the naive prompt (no forced citations, no abstention threshold)
over the full dev split (60 questions, 48 answerable) against the retrieval
config `decisions/0007` froze, scored with Task 19's ladder. It is the control
for ablations #6, #8, #9, #10, and the first real use of Task 19's scorers.
Using them for real surfaced three problems the unit tests had not, and one in
the driver itself. All are recorded here, including what was tried and
rejected, per the project's "log everything, not just the winner" rule.

Findings 1–5 come from the first pair of runs: `runs/20260917T032746Z_77e78976ead3`
and its null arm `runs/phase3c_repro_check/20260917T033952Z_b0ea088f0788` (120
generation calls). **Both are superseded.** The control of record is the re-run
in the Resolution, `runs/20260917T044122Z_c1d4b7284f0f`.

## Finding 1 — Task 19's Tier 1 scorer, as shipped, carried zero information

**v1 (commit `bf29473`)** joined all five retrieved chunks into one NLI premise.
DeBERTa's pair limit is 512 tokens; the joined premise measured **1,495–2,487
tokens**, so the tokenizer silently dropped ~70–80% of the context. Validated
against Task 16's hand-scored answers, v1 gave **every one of 20 answers exactly
0.000**. The baseline's first reported faithfulness, 0.013, measured the
truncation, not the answers.

Why the tests missed it: the fake model returned canned per-row logits and read
unbounded premises, so it could not see which premise a claim was checked
against, or that the real model can't read past 512 tokens. The tests now use a
fake that reads each pair *and* truncates like the real model; the regression
test was confirmed to fail on v1 (0.0) and pass on the fix (1.0).

**v2** windowed each chunk into ≤1,000-char overlapping premises and counted a
claim supported if any window entails it. Zero truncated pairs on real data
(counted via the real tokenizer, not assumed). Faithfulness: 0.243.

**v2 still under-credited plainly grounded claims.** Inspecting unsupported
claims showed two text artifacts, both removed in **v3**:

- *Unicode punctuation.* The model writes `per‑year` (U+2011) and narrow
  no-break spaces the corpus mostly doesn't; the tokenizer treats them as
  different strings. Fixed with NFKC + ASCII punctuation mapping.
- *Attribution wrappers.* `According to the Fine Arts page, "<verbatim quote>"`
  scored 0.00 entailment — the attribution is unverifiable against a passage.
  **This one would have corrupted a pre-registered comparison:** ablation #8
  (citation-forced prompt) produces more attribution by design, so it would
  have looked *less* grounded precisely for attributing. Wrappers are stripped.

**Refusals were also averaged in as fully unfaithful.** "The passages don't
mention X" is never entailed by the passages, so every refusal scored ~0
(10–11 of 60 answers). PLAN's rubric already scores refusals separately (R);
faithfulness is now computed over answered questions only, with `refusal_rate`
reported alongside it. Left in, an arm that refuses more would look less
grounded for it.

Every correction was made offline from stored answers and chunk ids — no
re-generation. Every prior value is kept per record
(`tier1_faithfulness_v1_truncated`, `tier1_faithfulness__2-windowed-max`).

| Scorer | Baseline faithfulness |
|---|---|
| v1 joined premise (shipped in Task 19) | 0.013 |
| v2 windowed | 0.243 |
| v2 + refusals excluded | 0.291 |
| **v3 windowed + normalized + refusals excluded** | **0.400 [0.307, 0.493] (n=50)** |

Rejected, and why: re-tuning the entailment threshold (argmax vs a probability
cutoff) was *not* done. Unlike the fixes above, it has no justification that
doesn't depend on which number it produces.

## Finding 2 — v3 does NOT pass the validation criterion set in advance

Criterion, fixed before the numbers were computed: Tier 1 is fit to remain the
primary generation metric only if (a) mean faithfulness rises monotonically
across hand scores 0→1→2, and (b) the Spearman correlation's 95% bootstrap CI
excludes zero. Against Task 16's 25 hand-scored answers (4 refusals excluded,
1 undefined; `scripts/validate_faithfulness.py`, `runs/faithfulness_validation.json`):

| Scorer | mean @ hand 0 | mean @ hand 1 | mean @ hand 2 | Spearman | Passes |
|---|---|---|---|---|---|
| v1 | — (n=0) | 0.000 (n=2) | 0.000 (n=18) | undefined (constant) | **no** |
| v3 | — (n=0) | 0.167 (n=2) | 0.390 (n=18) | 0.166 [−0.158, 0.457] | **no** |

**v3 fails.** It points the right way (hand-2 answers score higher than
hand-1), but the correlation's CI includes zero, and monotonicity can't be
established because no hand-0 answer survives the refusal exclusion. That is
partly the validation set's fault — 20 twos, 3 ones, 2 zeros can expose a
broken metric but has almost no power to confirm a working one — and it is
reported as a failure regardless, not reinterpreted as a pass.

Also: answers a human judged *fully correct and grounded* average only 0.390.
**The absolute value is biased low.** "40% of claims are grounded" is not a
valid reading of this baseline; at most, paired differences between arms are
interpretable, and even that is unvalidated.

## Finding 3 — temperature 0 is not deterministic on this endpoint

The verification step, "reproducible across two runs at temperature 0,"
**fails at the text level.** Two identical runs (the superseded pair above;
`runs/phase3c_reproducibility.json` now holds the re-run's report, and these
numbers regenerate via `compare_reproducibility` on the superseded run dirs):

| Measure | Value |
|---|---|
| Exact answer text match | 0.050 [0.000, 0.117] (3 of 60) |
| Same refuse/answer decision | 0.917 [0.850, 0.983] (5 of 60 flip) |
| Same cites-a-URL behavior | 0.800 [0.700, 0.900] (12 of 60 flip) |
| run2 − run1, refusal_correct | −0.017 [−0.083, +0.050] |
| run2 − run1, faithfulness | +0.025 [−0.066, +0.118] (n=46) |

Aggregates are consistent (both intervals cover zero), but per-question
*decisions* flip, not just wording. The second run is therefore the project's
first measured **noise floor**: on dev, a pure rerun moves faithfulness by up to
~±9 points and refusal-correctness by ~±7. Any T22 arm difference inside that
band is indistinguishable from rerunning the control.

Two consequences:

- **Task 17's generation cache hides this.** A cached rerun is identical by
  construction. Resumability is still correct to cache; reproducibility
  checks must never go through the cache. (Task 20 does not use it.)
- **Interleaving by question (PLAN Sec 4) fixes drift, not this.** It spreads
  hosted-weight drift across arms, but per-call nondeterminism is independent
  per question. It adds discordant pairs to every McNemar comparison, which
  costs power at T22.

## Finding 4 — the multi-turn slice was never given its history

All three dev `multi_turn` questions depend on a prior turn ("Does *she* need a
certain GPA…"), and the driver never passes `GoldQuestion.history` to retrieval
or to the prompt. The model answered a question whose subject it never saw.
**The multi_turn slice numbers in this baseline (faithfulness 0.111, n=3) are
not a multi-turn measurement.** This also bears on T22: ablation #6 step 5
(de-contextualization) needs a control that shows the model the history, or
it measures "history vs no history" rather than "rewriting vs not."

## Finding 5 — `refusal_correct` is coarse on the adversarial slice

`expects_answer = bool(gold)` is wrong for false-premise questions, where gold
refs exist but pushing back is correct (Task 16 hand-scored such refusals 2).
Reported per slice so the pooled 0.867 doesn't hide it.

## The control condition (valid parts)

Retrieval reproduces T18's frozen cell exactly (`all_golds_retrieved@5` 0.708),
confirming the config was wired correctly.

| Metric (dev) | Value |
|---|---|
| refusal_rate | 0.167 [0.083, 0.267] (n=60) |
| refusal_correct | 0.867 [0.783, 0.950] (n=60) |
| — out_of_scope only | **0.583 [0.333, 0.833] (n=12)** — answers 5/12 it should refuse; the gap #9 targets |
| citation_accuracy (when a URL is cited) | 0.600 [0.400, 0.800] (n=20) |
| citation_validity | 0.950 [0.850, 1.000] (n=20) |
| exact_match_presence | 0.600 [0.200, 1.000] (n=5) |
| faithfulness v3, answered only | 0.400 [0.307, 0.493] (n=50) — biased low, unvalidated |
| all_golds_retrieved@5 | 0.708 [0.583, 0.833] (n=48) |

The stored answers are the control; every score above is re-derivable offline,
so a later scorer fix re-scores this run rather than re-spending quota.

## Decisions pending (the user's)

1. **Task 20's verification step.** Text-level reproducibility is not achievable
   on this endpoint. *Recommendation:* amend it to metric-level reproducibility
   (null-arm intervals cover zero), and require every T22 comparison to report
   the measured noise floor beside its effect.
2. **The primary generation metric** (`decisions/0006` froze Tier 1). It fails
   its own validation, though on an underpowered set. *Recommendation:* before
   T22 spends the test split, hand-score a stratified ~40 of Task 20's existing
   dev answers, with the pipeline proposing each label for accept/correct (PLAN
   Sec 4d's fast workflow). That one labeled set re-runs this validation with
   real power *and* is the Tier 3 κ calibration set, so it settles both open
   questions at once. Revising the primary metric is still legitimate now,
   because no Phase 4 generation comparison has been seen; it stops being
   legitimate once one has.
3. **Multi-turn history in the control.** *Recommendation:* the control passes
   prior user turns to the prompt (what any chat UI does) but not to retrieval
   (rewriting is #6's job), with assistant turns generated live as
   `GoldQuestion`'s docstring already specifies.

## Resolution — 2026-09-17

### The human reviewer's decisions

1. **Verification step → metric-level reproducibility** (recommendation taken).
   Two runs of the control must agree at the metric level (every run2−run1
   interval covers zero), and that null-arm interval becomes a noise floor
   T22 reports beside every effect. Written into `tasks/plan.md` (T20, T22).
2. **Tier 1 faithfulness stays primary, with a caveat** (recommendation *not*
   taken; the extra hand-scoring round was declined). It is interpreted only
   as a paired arm difference, labelled unvalidated, and computed over
   answered questions with `refusal_rate` beside it. Recorded as a dated
   addendum to `decisions/0006` rather than an edit to the locked text. The
   Tier 3 κ calibration set, which the declined round would also have
   produced, is still unbuilt: a Tier 3 judge remains unusable until one exists.
3. **Multi-turn: history to the prompt, not to retrieval** (recommendation
   taken). Prior user turns are answered live and passed as chat messages.
   Retrieval sees only the current turn. `OllamaCloudGenerator.generate`
   gained a `history` argument; the context guard counts it, and
   `system`-role turns are rejected.

### Finding 6 — the prompt hid a third of what retrieval found

Found while implementing decision 3. `build_user_prompt` cut every passage to
1,400 characters, a default that predates the frozen 512-token chunks (median
2,355 chars). Measured on the control: **37.1% of retrieved text** never
reached the model, and **4 of 45 retrieved gold passages (8.9%)** were
invisible after the cut. On those questions retrieval scored a hit that
generation could not use. This is the same silent-truncation failure as
Finding 1, one layer up. The control now sends passages whole
(`passage_chars=None`); the context guard, not a character cut, handles real
overflow (largest control prompt: ~4,573 of 7,104 tokens). The 1,400 default
stays for the whole-document callers it was written for, and T24 now requires
whole passages.

This bears on `decisions/0007`'s flagged caveat, that fixed-512 chunks may win
retrieval metrics by size alone. Until this fix, that size advantage never
reached the generator. Task 16's quadrant analysis also ran under the cut.

### The re-run

Decisions 3 and Finding 6 change how the control behaves, so it was re-run
under a new config hash rather than patched into the old run dirs, which would
have mixed two code versions in one run. The earlier runs are kept, marked
**SUPERSEDED** in their `notes.md`.

Canonical control: **`runs/20260917T044122Z_c1d4b7284f0f`**. Null arm:
`runs/phase3c_repro_check/20260917T044751Z_74a4c2fdd4e4`. Quota: 126 generation
calls (two dev passes plus live prior turns).

| Metric (dev) | Control | Null arm (rerun) |
|---|---|---|
| refusal_rate | 0.150 [0.067, 0.250] (n=60) | 0.183 [0.083, 0.283] |
| refusal_correct | 0.850 [0.750, 0.933] (n=60) | 0.783 [0.683, 0.883] |
| — out_of_scope only | **0.500 [0.250, 0.750] (n=12)** — answers 6 of 12 it should refuse; the #9 gap | |
| — multi_turn only | 0.667 (n=3); faithfulness 0.000 (n=2). The model now understands the follow-up; retrieval on the bare follow-up misses. The #6 step-5 gap | |
| citation_accuracy (when a URL is cited) | 0.729 [0.562, 0.875] (n=24) | 0.604 [0.417, 0.792] |
| citation_validity | 0.958 [0.875, 1.000] (n=24) | 0.917 [0.792, 1.000] |
| exact_match_presence | 0.600 [0.200, 1.000] (n=5) | 0.600 |
| faithfulness v3 (answered only; **unvalidated, paired differences only**) | 0.435 [0.329, 0.540] (n=50) | 0.487 [0.378, 0.600] |
| all_golds_retrieved@5 | 0.708 [0.583, 0.833] (n=48) | 0.708 |

Tier 1 truncated pairs: 0 in both runs. Differences from the superseded control
(e.g. citation accuracy 0.600 → 0.729) sit inside the noise floor below and are
**not** attributed to the fixes.

### Amended verification result, and the noise floor T22 must report

| Measure | Value |
|---|---|
| Exact answer text match | 0.067 [0.017, 0.133] (4 of 60) |
| Same refuse/answer decision | 0.900 [0.817, 0.967] (6 of 60 flip) |
| Same cites-a-URL behavior | 0.767 [0.650, 0.867] (14 of 60 flip) |
| **run2 − run1, refusal_correct** | **−0.067 [−0.150, 0.000]** |
| **run2 − run1, faithfulness** | **+0.037 [−0.054, +0.127]** (n=47) |

**Passes, at the boundary.** Both intervals cover zero, but refusal_correct's
upper end is exactly 0.0: its six discordant questions split 5 against the
rerun and 1 for it. Four of the six are **cross_silo**, the slice the
project's thesis rests on and apparently where the model's refuse/answer
decision is least stable. At n=60 on dev, a pure rerun of the control swings
refusal_correct across a 15-point interval and faithfulness across 18 points.
Plausible single-arm effects are smaller than that, so on dev, most T22
differences are expected to read as indistinguishable from rerun noise. That
is a statement about power, recorded now, before any arm result exists to
explain away.
