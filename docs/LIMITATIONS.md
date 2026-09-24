# Limitations and what actually moved the numbers

Written 2026-09-24 (Task 32). Every number here is copied from a run dir or a
`decisions/` doc, named where it appears. Nothing was re-run for this document.

The limitations come first because they bound how much any result below can be
trusted.

## The limitations

### 1. The evaluation set was written by the person who built the system

The 300 gold questions (train 120, dev 60, test 120) are **self-authored and
synthetic**, and labelled `provenance: "synthetic"` in the data
(`decisions/0004`). There is no access to real Maryville College student
queries. That means:

- The author is also the designer. Questions were written knowing what the
  corpus contains and what a retrieval system is likely to find, so they are
  likelier to be answerable and well-formed than a real student's typo-ridden,
  under-specified question. Scores are probably optimistic about live traffic,
  and by an amount this project cannot measure.
- Slices are small. On the test split the smallest are `multi_turn` (6) and
  `adversarial`/`exact_match`/`temporal` (10 each); on dev, `multi_turn` is 3.
  Per-slice differences are reported as effect size and CI only and none is
  licensed as a finding. Only the pooled test comparison in `decisions/0013`
  gets a p-value.
- **Dev is selection, not inference.** Choices were made by looking at dev, so dev
  numbers are optimistic. The one clean look is the test run below, and its
  retrieval number is lower than the dev number it was chosen on:
  `all_golds_retrieved@5` **0.583** [0.490, 0.688] (n=96) on test against 0.708
  [0.583, 0.833] (n=48) on dev, with overlapping intervals.
- The multi-turn slice is the weakest. Its 15 questions were split across train
  (6), dev (3) and test (6). T28's de-contextualization decision rests on n=9
  from train, and **train is now spent for that slice**.

### 2. The primary generation metric is unvalidated

Tier 1 faithfulness (NLI-based) is the frozen primary generation metric
(`decisions/0006`). It failed its validity check twice:

- `decisions/0008`: Spearman 0.166 [−0.158, 0.457] against human scores (25 items).
- `decisions/0012`, independent n=40 set: Spearman **0.030** [−0.248, 0.300].

Its interval covers zero both times, so it may carry little or no signal about
whether an answer is faithful. Every faithfulness number in `RESULTS.md` should
be read as a paired difference between arms, not as an absolute measure of
answer quality. **The Pareto frontier in `RESULTS.md` plots this metric.**

**Judge-human agreement (PLAN 4d).** A Tier 3 LLM judge was built and calibrated
against 50 blind human labels. It failed its pre-registered gate:
Cohen's κ = **0.146** [−0.113, 0.540] against a floor of 0.6. Raw agreement was
86%, but 45 of the 50 human labels were 2 and none were 0, so the agreement is
mostly chance (`decisions/0012`). Tier 3 was therefore **not used** for any
reported result, and the code refuses to run without a passing calibration.
Tier 2 (full human scoring) was skipped for the test pass (`decisions/0013`), so
test-set answer quality rests on Tier 0 (deterministic) and the unvalidated Tier 1.

### 3. Cloud generation is attributable, not reproducible

Retrieval is local and deterministic. Generation runs on Ollama Cloud's free
tier, so:

- **Temperature 0 is not deterministic on this endpoint.** Two identical
  `gpt-oss:20b` runs matched exactly on 6.7% of answers on dev
  (`decisions/0008`) and 15.8% on test (`decisions/0013`). Refuse/answer flipped
  on 6 of 60 questions on dev.
- Each run is *attributable*: config, split hash, corpus lock and model lock are
  stored beside its results. It is not *re-derivable*: the provider can change
  what a model name serves, and a future run may not reproduce a past number.
- Consequently every LLM-involving effect is read against a same-config rerun
  (the noise floor). On dev at n=60 a pure rerun swings `refusal_correct` across
  a 15-point interval and faithfulness across 18 points, so most single-arm
  dev differences are indistinguishable from rerunning the control
  (`decisions/0008`).
- Cost (wall time) is cloud latency with queue and cold-start noise, not a
  property of the model alone.

### 4. Abstention is tied to one model and is imperfect

- The refusal behavior was tuned for one model, `gemma4:31b`, and one scope
  prompt (`scope_strict`). It was not validated on any other model.
- The retrieval-score gate (`decisions/0009`) **does not meet its own floor**:
  80% precision was a post-hoc lowering from the pre-registered 95%, and it
  reaches 0.786 [0.655, 0.905] out of fold. Out of fold it answers about a
  quarter of questions and refuses about 62% of answerable ones. Its only clean
  estimate would come from test, and **the test pass never ran the gate**, so
  that estimate does not exist.
- On dev, 25% of `out_of_scope` questions (3 of 12) still receive a confident
  answer under the adopted prompt (`decisions/0014`). Three stronger mechanisms
  each fixed that at a worse cost elsewhere and were rejected (see below).
  n=12 is far too small to bound the true rate.
- `refusal_correct` treats any question with a gold reference as one that should
  be answered, so it counts a correct refusal on incompletely-retrieved evidence
  as an error. Read alongside the retrieval-side precision, not alone.

### 5. Coverage is a third of what was considered

Of 5,479 URLs considered, **1,847 (33.7%) were fetched** and 3,421 excluded
(policy 1,879, `robots_disallow` 1,146, `extraction_empty` 396), with 211 failed
(`docs/coverage.md`, counted from `corpus/manifest.jsonl`). A question whose
answer lives on an excluded page cannot be answered, by construction. Both
the gold set and the results are conditional on this crawl; the corpus is a
September 2026 snapshot and the college's site changes.

### 6. What was never checked live

These are recorded as open in `tasks/plan.md` and not claimed anywhere:

- The "sources arrive at least 1s before the first token" timing claim
  (Checkpoint F). Ordering is a tested design property; the timing number needs a
  live `gemma4:31b` call.
- A live run of the three fixed prompt-injection attempts against the real model.
- A live `curl -N POST /ask` and a real-browser open of the reference client.
- The setup steps for rebuilding `corpus/` and `indexes/` on a fresh machine.
  The clean-clone check covered install and tests only.

## What actually moved the numbers

Everything that was tried is here, including what did nothing or made things
worse. Effects are on dev unless marked test.

### Retrieval (free, 32-cell factorial, `decisions/0007`)

Metric: `all_golds_retrieved@5`, dev n=48. The naive control (3a, dense only,
fixed chunks) scored **0.562**. The frozen config scored **0.708**, a gain of
about 0.146 that is real in size but inferred from n=48, so its CI is wide.

| Factor | Main effect | Verdict |
|---|---:|---|
| Reranker | +0.057 | Helped alone, but adds nothing once fusion is on; **left out of the frozen config** |
| Fusion (dense + BM25 + literal, RRF) | +0.047 | **Kept.** The strongest lever |
| Chunking (fixed 512 vs paragraph) | +0.010 | Fixed-512 kept; the difference is small |
| Boilerplate stripping | −0.016 | Off. Slightly negative on average |
| Silo boost | −0.018 | Off. Neutral to harmful; in some cells it cut the score from 0.688 to 0.542 |

The frozen config is fusion on, reranker off, silo boost off, fixed-512 chunks,
boilerplate off. Several cells tie at 0.708, so the choice among ties was a
judgment call recorded in `decisions/0007`, not a finding.

### Query reformulation (`decisions/0011`)

An acronym dictionary made retrieval slightly **worse**: −0.021 [−0.063, +0.000].
The pre-registered stopping rule ended the ladder there. Rung 2 (dictionary plus spelling normalizer) was never run, and the costlier
rungs (decomposition, multi-query, step-back, HyDE) were never built, because a
cheaper rung had already failed. Reformulation does not help on
single-turn questions here. The one exception is follow-up turns (below).

### De-contextualizing follow-up questions (`decisions/0015`, train, n=9)

| Arm | Result |
|---|---|
| Arm 0, no rewrite | control; slice 2/9 answerable at k=5 |
| Arm 1, concatenate history (free) | large point estimate but **lost** on the zero-regression rule: it dropped one question (mt-03) by diluting the query |
| Arm 2, LLM rewrite (adopted) | 4 improved, 0 regressed; slice goes 2/9 to 6/9 |

Arm 2's edge over arm 1 rests on **one question**. Three questions (mt-02,
mt-07, mt-11) stayed unretrieved under every arm even with good rewrites, so the
remaining gap is retrieval or corpus coverage, not rewriting.

### Generation choices (dev, n=60, `decisions/0010`)

| Comparison | Result |
|---|---|
| Force citations vs free-form (`gpt-oss:20b`) | Model complied on only about half of citable sentences (marker compliance 0.527); no measurable faithfulness or refusal change; answers shorter and faster |
| Retrieval-score gate vs always answer | `refusal_correct` −0.400 [−0.550, −0.233], because the gate refuses many questions that have gold references but incomplete retrieval. `decisions/0010` argues this is a metric mismatch, not a gate failure; dev precision 0.938 is in-sample and optimistic |
| `gpt-oss:120b` vs `gpt-oss:20b` | Faithfulness lower (−0.182 [−0.307, −0.064]) and faster |
| `nemotron-3-nano:30b` vs `gpt-oss:20b` | Faithfulness lower (−0.116 [−0.219, −0.014]) |
| **`gemma4:31b` vs `gpt-oss:20b`** | Faithfulness indistinguishable (−0.033 [−0.151, +0.081]), **4.4 s faster and 301 fewer tokens per answer**. Adopted |

The lower-faithfulness results for the larger models are differences against an
unvalidated metric, not a claim that bigger models are worse.

### The out-of-scope ladder (`decisions/0014`, dev)

| Rung | What it did | Outcome |
|---|---|---|
| 1. Stricter refusal prompt | 2 of 12 out-of-scope questions fixed, no collateral | **Kept** (small, CI not clear of zero at n=12) |
| 2. Post-hoc faithfulness override | No usable threshold; feature is heavily tied at 0 | Rejected |
| 3. Separate LLM answerability check | Fixed the target (0 of 12 false answers) | **Rejected**: −0.217 [−0.350, −0.083] on the pooled in-scope set |

The signal that separates these cases is too coarse to threshold and too
context-free to isolate without refusing real questions. The residual 25% gap
stays as a documented limitation.

### The one test-split pass (`decisions/0013`, n=120 questions per arm)

Frozen `gemma4:31b` against baseline `gpt-oss:20b`, with a second identical
`gpt-oss:20b` pass as the noise floor. Retrieval scores are bit-identical
across arms, as expected.

| Metric | Difference | 95% CI |
|---|---:|---|
| `refusal_correct` | −0.017 | [−0.083, +0.050] (McNemar p = 0.81) |
| Faithfulness | −0.053 | [−0.139, +0.030] |
| Wall time (s) | **−5.503** | [−6.134, −4.921] |
| Completion tokens | **−297.8** | [−332.2, −265.0] |

No accuracy or faithfulness difference is distinguishable from noise. The cost
and latency win is 5 to 25 times larger than the noise floor. That is the
confirmed result: **the model swap was a cost and latency improvement at no
measurable quality cost, not a quality improvement.**

## Test-split access log

Reproduced verbatim from `notes.md`. This is the only access to the test split
in the project. The calibration and T28 scripts filter test out at load (`decisions/0009`, and an assertion in `scripts/run_t28_decontextualization.py`).

> # Test-split access log
>
> Per the standing rule, every access of the 120-question test split is logged here, at the moment the first question is actually sent to a generator, not before.
>
> ## 2026-09-22T15:10:47+00:00 -- test-split access
>
> Task 22b (decisions/0013): 120 test questions x 3 arms (t22b_baseline_20b_a, t22b_baseline_20b_b, t22b_frozen_gemma4_31b). Frozen config: decisions/0007 retrieval, decisions/0011 no reformulation, decisions/0010 generation model gemma4:31b vs Task 20 baseline gpt-oss:20b. split.lock hash: 044615d51d4d074a0954f89e8e47a3afc4d20c021f460d8b77b65c41350c911d.

Only three run directories under `runs/` have `split: test`, and all three are
that entry's arms: `20260922T151047Z_18b214bce36b`, `_4185e547c9ee` and
`_9a6295b654ee`.
