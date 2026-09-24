# 0015 — Conversational de-contextualization (Task 28, PLAN §4c step 5)

**Date:** 2026-09-23 · **Status:** pre-registered. Everything below the
"Results" heading was empty when this file was first committed; the pool, the
arms, the metric, the bar and the adoption rule were all fixed before a
single arm ran.

## Context: why this runs at all after decisions/0011 closed the ladder

`decisions/0011` closed ablation #6 at rung 0. Rung 1 (acronym dictionary)
scored 0.708 → 0.688 on `all_golds_retrieved@5`, −0.021 [−0.063, +0.000],
failing its pre-registered bar, and the pre-registered stopping rule said a
cheaper rung going flat is evidence against climbing higher. Rungs 3–7 —
decomposition, multi-query, **de-contextualization**, step-back, HyDE — were
never built.

Step 5 is built now, under a different warrant, and the distinction is not a
loophole:

1. **PLAN §4c calls step 5 "Mandatory for multi-turn."** It is a standing
   product requirement for a population, not an optional rung whose value the
   ladder was free to decline.
2. **decisions/0011 never measured it, and could not have.** The ladder ran on
   the pooled 60-question dev set. Of those, only 3 carry any `history` at
   all; for the other ~57 de-contextualization is a structural no-op, since
   there is no conversation to resolve a pronoun against. A pooled mean over
   60 questions in which 57 are guaranteed unchanged is arithmetically
   incapable of detecting an effect on the other 3. decisions/0011 declined to
   *spend quota* on rungs 3–7; it did not, and could not, produce evidence
   about this one.
3. decisions/0011's finding — "reformulation doesn't help this corpus at the
   frozen retrieval config" — is a claim about single-turn retrieval. The
   multi-turn slice is the population it says nothing about.

This is materially different from Task 27's refusal gate, where
`decisions/0014` had already **built and measured** the exact mechanism on the
exact population, and re-wiring it would have re-litigated a settled result.
Here there is no measurement to re-litigate. This doc makes one.

## The n problem, stated before it becomes convenient

`data/gold/gold_v1.jsonl`'s `multi_turn` slice is 15 questions, split by
`data/gold/split.lock` (seed 42, `split_hash` 044615d5…) as:

| Split | n | Availability |
|---|---:|---|
| test | 6 | **excluded.** Test was spent exactly once, at T22b (Checkpoint E confirmation). Not touched here, for any reason. |
| train | 6 | available — see below |
| dev | 3 | available |

Every one of the 15 has exactly **1 prior user turn** and exactly **1 gold
ref**, and `conjunctive` is `False` for all of them. Two consequences:

- `all_golds_retrieved@5` ≡ `recall@5` ≡ hit@5 on this slice. They are not
  three metrics here, they are one number reported three ways.
- Task 28's stated verification ("run the multi-turn dev slice through it") is
  **n = 3**. One question flipping moves the metric by 0.333. No paired
  bootstrap CI over 3 questions is informative about anything.

**Human decision, made before any arm ran:** the primary pool is the **9
dev + train multi-turn questions**; the dev-only 3 are reported as a
pre-registered secondary breakdown, not as an alternative headline to pick
between afterwards.

The justification for reading `train`, and its limit: **no model is trained
anywhere in this project.** There is no fitting step, no hyperparameter search
against train, no checkpoint selection — the `train` split has never been read
by any script in this repo. It is therefore an unused held-out pool rather
than a contaminated one, and spending it here is a one-time repurposing,
recorded in this doc so no later task can treat it as still-unused. What it is
*not* is a substitute for test: 9 questions is still small, the CI over it is
reported but is **explicitly not the decision rule** (see the bar below), and
every one of the 9 per-question outcomes is printed so the result can be read
as what it is — 9 individual retrievals — rather than as a mean pretending to
precision it does not have.

Pool and bar are fixed here, before running, specifically because choosing
between n=3 and n=9 after seeing both numbers would be exactly the post-hoc
selection decisions/0009, 0010 and 0011 exist to prevent.

## Arms

Cheapest-first, per PLAN §4c's own doctrine. All three retrieve at the frozen
config (decisions/0007: boilerplate off, `FixedSizeChunker(512)`, RRF fusion
on, retrieval reranker off, silo boost off, `k=5`, `candidate_k=20`).

| Arm | Class | Cost | What it does |
|---|---|---|---|
| 0 | `IdentityReformulator` | free | **Control = today's shipped behavior.** Retrieves on the raw follow-up, exactly as the service does now. |
| 1 | `HistoryConcatenationReformulator` | free | Prepends the prior user turn's text to the follow-up. Deliberately **not** de-contextualization: no standalone question is produced, the entity terms are merely dragged into the query string. |
| 2 | `LlmDecontextualizer` | metered, 1 short call/question | Step 5 proper: `gemma4:31b` (decisions/0010) at temperature 0 rewrites the follow-up into a standalone question. Output is one question, not an answer. |

Arm 1 exists so arm 2 has to beat the *free* thing that captures much of the
same signal, not merely beat the raw follow-up. A metered mechanism that only
matches free concatenation has not earned its cost.

`LlmDecontextualizer` falls back to the raw query on an empty reply, a
multi-line reply, a reply over 300 characters, or any generator exception, and
records why in `last_error`. Fallbacks are counted and reported: an arm that
silently degraded to arm 0 on half its questions would otherwise look like a
null effect rather than a broken mechanism.

## Metric and bar

- **Primary metric:** `all_golds_retrieved@5` (decisions/0005), on the 9
  dev+train multi-turn questions. Identical to `recall@5` here, as noted.
- **Secondary:** the dev-only 3, reported separately; `mrr` and `ndcg@5` for
  rank position, which can move even when hit@5 does not.
- **Comparisons:** paired by `qid`, `paired_bootstrap_comparison` (`b − a`),
  each arm against **arm 0**, not cumulatively. The ladder-style cumulative
  comparison in decisions/0011 existed because rungs composed; arms 1 and 2
  here are alternative mechanisms for the same job, so each is measured
  against the control and against each other.
- **Noise floor for arm 2:** one full same-config rerun of arm 2 (identical
  method to decisions/0010 and ablation #8/#9/#10), since it involves an LLM.
  Temperature 0 makes drift unlikely but not impossible, and this project's
  standing convention is that a noise-floor rerun is reported *beside* every
  LLM-involving effect rather than assumed away.

**The bar, and it is deliberately not a CI:** at n=9 a bootstrap CI's lower
bound is not a meaningful decision rule — it is nearly guaranteed to include
zero for any effect this slice can show, which would make "CI clears zero"
a rule that rejects every arm regardless of its merit. So the pre-registered
bar is stated in questions, which is the unit the evidence actually has:

- An arm is **adopted as the service default** only if it improves at least
  **3 of the 9** questions and regresses **none**, and, for arm 2, its
  improvement also exceeds its own noise-floor band.
- An arm that improves some and regresses others is **not adopted**, and the
  per-question table is reported so the trade is visible rather than netted
  out.
- If arms 1 and 2 both clear the bar, the **free arm wins** — arm 2 must
  strictly exceed arm 1 to justify a metered call per follow-up turn.
- If no arm clears it, the service default stays `reformulator=None` (arm 0)
  and that is reported as the finding. A null result here is publishable in
  exactly the sense decisions/0011's null result was: it says the mechanism
  PLAN calls mandatory does not measurably help *this* corpus at *this*
  retrieval config, on the evidence available.

The CI is still computed and printed for all comparisons. It is context, not
the gate, and this doc says so in advance so that a wide interval cannot later
be presented as either vindication or refutation.

## What is being decided, and what is not

**Decided here:** whether `mcrag.service.answer.AnswerPipeline.reformulator`
ships as `None` (arm 0) or as one of the two step-5 rungs.

**Not decided here, and flagged rather than buried:**

- **τ's calibration does not cover follow-ups.** The Task 27 threshold gate
  (τ = 4.96, decisions/0009) now scores against the *rewritten* query, on the
  reasoning that a bare follow-up under-specifies the information need and
  would score low against passages that answer it fine. τ was calibrated on
  standalone dev questions, which contain no under-specified follow-ups at
  all, so neither choice is validated by evidence — the rewrite is simply the
  closer match to the distribution τ was fitted on. Re-calibrating τ for
  multi-turn traffic is out of T28's scope and unbudgeted here.
- **Generation quality is not measured.** This ablation is retrieval-only.
  Whether a rewrite changes the *answer* the student reads is a generation
  question on a 9-question slice with no faithfulness budget attached; the
  service deliberately generates on the original question text, so the
  intended blast radius is retrieval alone.
- **One prior turn is all the data has.** Every multi-turn gold question
  carries exactly one prior turn. Nothing here measures how either arm
  behaves at turn 4 of a real conversation, and
  `HistoryConcatenationReformulator`'s `max_turns` cap is left at `None`
  (no cap) because no value for it can be measured on this slice.

## Results

`scripts/run_t28_decontextualization.py`, run 2026-09-23. Free arms first,
then the metered arm under explicit human authorization. Pool: the 9
dev+train `multi_turn` questions, `split_hash` 044615d5…; the 6 test
questions were not read.

| Arm | Config | `all_golds_retrieved@5` (n=9) | vs. arm 0 | Improved | Regressed | Bar |
|---|---|---:|---|---|---|---|
| 0 | `IdentityReformulator` (control, shipped today) | 0.222 | — | — | — | control |
| 1 | `HistoryConcatenationReformulator` (free) | 0.556 | +0.333 [−0.111, +0.778] | 4 | 1 | **fails** |
| 2 | `LlmDecontextualizer` (metered) | **0.667** | **+0.444 [+0.111, +0.778]** | 4 | 0 | **clears** |

Secondary metrics, same pool:

| Arm | `mrr` | `ndcg@5` | dev-only n=3 |
|---|---:|---:|---:|
| 0 | 0.167 | 0.181 | 0.333 |
| 1 | 0.481 | 0.500 | 0.667 |
| 2 | 0.454 | 0.507 | 0.667 |

**Noise floor (arm 2):** +0.0000 [+0.0000, +0.0000]. The rerun reproduced all
9 rewrites **byte-identically** — `temperature=0` on `gemma4:31b` was fully
deterministic on this input, so arm 2's +0.444 sits entirely outside its own
noise band. Zero fallbacks: all 9 rewrites were well-formed single questions,
none tripped the empty/too-long/multi-line guards.

### Why arm 1 lost

Arm 1 is not a bad arm — +0.333 is a large point estimate and it wins 4 of the
same 4 questions arm 2 does (mt-08, mt-12, mt-13, mt-15). It fails the
pre-registered bar on the zero-regression clause, on **mt-03**:

> history: "Does MC have a counseling center students can go to?"
> follow-up: "What am I supposed to do if I need help at 2 in the morning?"

Arm 0 retrieves the gold chunk at rank 2 from the bare follow-up. Arm 1
concatenates the two turns and **loses it entirely** — the doubled token mass
competes for the fixed `CANDIDATE_K=20` slots and shifts the dense leg's
embedding toward an average of two questions, which is exactly the dilution
mechanism `decisions/0011` diagnosed for the acronym rung. Arm 2 keeps it
(rank 4, so degraded but retrieved) because it produces *one* question rather
than two glued together: "What am I supposed to do if I need help from the MC
counseling center at 2 in the morning?"

That single question is the whole of arm 2's margin over arm 1: the head-to-head
is +0.111 [+0.000, +0.333], improved 1 (mt-03), regressed 0. So the metered
arm's advantage is narrow and rests on one question — stated plainly rather
than presented as a decisive win.

`mrr` is the one number where arm 1 edges arm 2 (0.481 vs 0.454), and the
reason is the same mt-03: arm 1 loses that question outright, which removes it
from arm 1's mean rather than scoring it, while arm 2 carries it at rank 4 and
takes the low reciprocal. `ndcg@5` (0.500 vs 0.507) and the primary metric both
favor arm 2. A metric that rewards dropping a hard question is the wrong
tie-breaker, which is why the primary metric was fixed in advance.

### What stayed broken in every arm

mt-02, mt-07 and mt-11 miss at k=5 under **all three** arms, and arm 2's
rewrites for them are good ones by inspection:

| qid | arm 2's rewrite |
|---|---|
| mt-02 | "Do I have to have a meal plan if I end up commuting from home next year instead of living in the residence halls?" |
| mt-07 | "Does a high school junior need a certain GPA or test score to qualify to take college classes at MC early?" |
| mt-11 | "What if I just want to talk to one of my child's professors at MC about how they're doing?" |

These are not de-contextualization failures. Each is a well-formed standalone
question whose answer the frozen retrieval config does not surface in its top 5
— a retrieval or corpus-coverage limit that step 5 was never able to fix.
Reporting them here keeps the ceiling honest: arm 2 takes the slice from 2/9
to 6/9, not to 9/9.

### Decision

**Arm 2 (`LlmDecontextualizer`) is adopted as the service default.** It clears
the pre-registered bar (4 improved, 0 regressed, ≥3 required), its improvement
exceeds its own noise floor (which is exactly zero), and it strictly exceeds
the free arm, which the tie-break rule required before a metered call per
follow-up could be justified. `mcrag.service.answer.get_default_pipeline`
therefore configures it, at `gemma4:31b`, `temperature=0`, `max_tokens=128` —
the same configuration measured here, not a re-tuned one.

Cost shape of that adoption: **single-turn traffic is unaffected**, since both
step-5 arms return the query unchanged when `history` is empty and
`LlmDecontextualizer` makes no call at all in that case. A follow-up turn costs
one additional short completion (a question, not an answer), reported in
`latency_ms.reform` on the wire so it cannot hide inside `e2e`.

Honest limits on this decision, restated so the table above is not read as
stronger than it is: n=9, the margin over the free arm is one question, the
bar was counts rather than a CI because at this n a CI cannot carry a
decision, and `train` has now been spent — no later task may treat it as
unused. The CI on arm 2's improvement does clear zero (+0.111 lower bound),
which was not required and is not what the adoption rests on.
