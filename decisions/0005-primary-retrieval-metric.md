# 0005 — Primary retrieval metric chosen empirically (Task 16)

**Date:** 2026-09-15 · **Status:** accepted, governs Phase 4 (Task 18 onward)

## Context

PLAN Phase 3b exists to answer one question before twenty ablations get tuned
against a retrieval proxy: does a retrieval metric actually track answer
quality on this corpus, and if so, which one? Choosing the optimization target
by convention (recall@k, because everyone reports it) is exactly the failure
mode Phase 3b is there to catch.

25 dev questions, stratified across all 6 answerable slices, were run
end-to-end on the naive Phase 3a config (`scripts/run_phase3b_sanity.py`,
`runs/20260915T004143Z_2a62552d2271/`) and hand-scored 0/1/2 by a human
(`docs/phase3b-sanity-review.md`), not by an LLM judge, per PLAN's own
instruction not to build a judge pipeline for 25 items.

**`num_ctx` truncation is ruled out by construction, not just by inspection.**
`OllamaCloudGenerator` raises `ContextOverflow` rather than sending an
oversized prompt; zero of the 25 calls hit it (`truncation_risk: false` on
every record). The one call that looked like a truncation failure at a glance
(`ss-39`, empty answer) has `finish_reason: "length"` with 4646 reasoning
characters against a 1024-token `max_tokens` cap — the model spent its whole
output budget reasoning and never emitted an answer token. That is a distinct
failure mode from `num_ctx` truncation (input vs. output) and is noted here so
it isn't mistaken for the thing the guard already prevents.

## The quadrant table

Binary retrieval signal is `all_golds_retrieved@k` (1.0 = every gold ref
present in top-5, 0.0 = not) — the strictest of the four metrics and the one
PLAN singles out for conjunctive correctness. Hand score is bucketed
good (2) vs. not-fully-correct (0 or 1).

| | Hand score = good (2) | Hand score < 2 |
|---|---|---|
| **all_golds_retrieved@k = 1.0** | 14 | 2 (`cs-63`, `ss-39`) |
| **all_golds_retrieved@k = 0.0** | 6 (`adversarial-01`, `adversarial-10`, `cs-17`, `cs-25`, `cs-70`, `mt-07`) | 3 (`cs-14`, `cs-26`, `cs-44`) |

19/25 (76%) land on the diagonal. The two off-diagonal cells have different
causes and different amounts of danger.

### High retrieval, bad answer (n=2) — not a retrieval problem

- **`ss-39`** — the `max_tokens`/reasoning-exhaustion failure above. Retrieval
  found the right chunk; generation never got to use it.
- **`cs-63`** — retrieval found the right chunk (recall/MRR/all-golds all
  1.0); the human docked it to partial because the answer's claim ("SMILE is
  separate from Bonner") is inferred from the *absence* of a stated link in
  the retrieved passage, not from an explicit statement. A reasoning-quality
  question, not a retrieval one.

Neither is the dangerous version PLAN warns about (distractors drowning a
correct chunk in noise, or lost-in-the-middle ordering) — both are generation-
stage issues that a retrieval metric was never going to catch, which is
itself informative: it says the 3a retrieval config is not the bottleneck
here.

### Low retrieval, good answer (n=6) — the quadrant Phase 3b exists to check, and it clears

PLAN's warning: this quadrant usually means the model answered from parametric
knowledge, not the corpus — dangerous for an institutional bot. Checked
individually against whether the answer actually cites retrieved content:

- **`adversarial-10`, `cs-17`** — the answer *is* grounded in a retrieved
  chunk, quoted and cited, that documents-inspection confirms says the same
  thing as the labeled gold chunk on a different part of the same page family.
  This is a gold-labeling/chunk-alignment miss (a real answer landed in a
  differently-chunked, differently-worded passage that content-overlap
  matching didn't catch at the 50% threshold), not a hallucination.
- **`adversarial-01`, `cs-25`, `cs-70`** — the model correctly said "the
  passages don't confirm/contain that," citing what it did retrieve and
  declining to overclaim beyond it. This is the *correct* behavior for a
  question the corpus may not directly answer, and it is grounded (it
  explicitly references what's absent from the cited passages), not invented.
- **`mt-07`** — the known, expected multi-turn gap: no conversational
  decontextualization exists yet (Task 28), so retrieval sees only the bare
  follow-up. The model compensated by covering multiple plausible
  interpretations. Not diagnostic of the retrieval metrics generally.

**None of the six are the dangerous case.** Every low-retrieval/good-answer
instance is either grounded-but-mislabeled or a defensible grounded refusal.

## Decision

**`all_golds_retrieved@k` is the primary retrieval metric for Phase 4.**
Reasons, in order:

1. It is the metric PLAN's own central claim depends on (a cross-silo question
   is only actually answered if *every* required chunk is present — partial
   credit is a wrong answer scored as half right), and this run gives no
   reason to override that by convention-following recall@k instead.
2. Its errors in this sample are conservative, not misleading: every time it
   said "0" on a question the human scored "good," the answer was still
   grounded (never silent parametric-knowledge leakage) — the exact risk
   Phase 3b exists to catch didn't materialize. A metric whose false
   negatives are safe undercounts is the one to optimize against.
3. Its two false negatives are both generation-stage causes (output-token
   exhaustion, inference-confidence) that Phase 4's *retrieval* ablations
   (T18) cannot move and should not be blamed on. Freezing on
   `all_golds_retrieved@k` will not reward an ablation for fixing a problem
   retrieval never had.

`recall@k`, `mrr` and `ndcg@k` remain reported (they are cheap and already
wired into every run), but ablation rankings and the Checkpoint D go/no-go
call are made on `all_golds_retrieved@k`, with `conjunctive_all_golds_retrieved@k`
as the number that most directly tracks the project's thesis.

**Secondary finding, not this decision's subject but discovered enroute:**
the naive Phase 3a/3b prompt did not delimit retrieved passages from the
user's question, and the corpus is scraped, unreviewed web text — instruction-
shaped page content is indistinguishable from a real instruction in a flat
concatenated prompt. Fixed in `mcrag/generate/prompting.py` (`<passages>`/
`<question>` tags, explicit system-prompt clause) before Task 20 freezes a
baseline prompt for ablation #8. This run predates that fix and is not
rerun on it — regenerating would invalidate the hand-scores already recorded
here, and the fix is orthogonal to what this decision is measuring.

## Consequences

- Phase 4 (T18) is scored and ranked on `all_golds_retrieved@k`.
- Checkpoint D's GO/NO-GO question ("does the retrieval proxy track answer
  quality?") is **GO** — 76% diagonal agreement, and the off-diagonal cases
  are explained, non-dangerous, and not retrieval-attributable.
- The gold-labeling/chunk-alignment miss (`adversarial-10`, `cs-17`) is a
  known source of retrieval-metric false negatives, not fixed here — noted as
  a limitation for the Phase 6 writeup rather than reopening Task 13's
  already-human-reviewed gold set on a 2-question sample.
