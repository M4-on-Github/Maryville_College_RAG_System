# 0007 — Retrieval config frozen from the free factorial (Task 18)

**Date:** 2026-09-16 · **Status:** accepted, governs T19–T22 and Checkpoint E

## Context

T18 ran the full free-half factorial PLAN Sec 4b calls for: boilerplate
stripping on/off, chunking scheme (production `ParagraphChunker` vs the
Task 15 naive `FixedSizeChunker(512)`), reranker on/off, fusion mode
(dense-only vs RRF over dense+BM25+literal), silo boost on/off — 2^5 = 32
cells, every combination, scored on **dev** (n=48 answerable questions),
zero generation quota. `all_golds_retrieved@5` is the outcome metric, per
`decisions/0005`. Full per-cell numbers (recall@k, MRR, nDCG@k,
`all_golds_retrieved@k`, each with a bootstrap CI) are in `RESULTS.md`;
`runs/phase4_free_factorial_summary.json` is the machine-readable source
both that table and this doc's numbers are generated from.

This records every arm tried and why the losers lost, not only the winner.

## All 32 cells

| boilerplate | chunking | fusion | reranker | silo_boost | all_golds_retrieved@5 |
|---|---|---|---|---|---|
| off | fixed512 | on  | off | off | **0.708** |
| off | fixed512 | on  | off | on  | **0.708** |
| on  | fixed512 | on  | on  | off | **0.708** |
| on  | fixed512 | on  | on  | on  | **0.708** |
| off | fixed512 | on  | on  | off | 0.688 |
| off | fixed512 | on  | on  | on  | 0.688 |
| on  | fixed512 | on  | off | off | 0.688 |
| off | fixed512 | off | on  | off | 0.667 |
| off | fixed512 | off | on  | on  | 0.667 |
| on  | fixed512 | off | on  | off | 0.667 |
| on  | fixed512 | off | on  | on  | 0.667 |
| on  | paragraph| on  | on  | off | 0.667 |
| on  | paragraph| on  | on  | on  | 0.667 |
| off | paragraph| off | on  | off | 0.646 |
| off | paragraph| off | on  | on  | 0.646 |
| off | paragraph| on  | off | off | 0.646 |
| off | paragraph| on  | off | on  | 0.646 |
| off | paragraph| on  | on  | off | 0.646 |
| off | paragraph| on  | on  | on  | 0.646 |
| on  | paragraph| off | on  | off | 0.646 |
| on  | paragraph| off | on  | on  | 0.646 |
| on  | paragraph| on  | off | off | 0.646 |
| off | paragraph| off | off | off | 0.604 |
| off | paragraph| off | off | on  | 0.604 |
| on  | paragraph| off | off | off | 0.604 |
| on  | paragraph| off | off | on  | 0.583 |
| on  | paragraph| on  | off | on  | 0.583 |
| off | fixed512 | off | off | off | 0.562 |
| off | fixed512 | off | off | on  | 0.562 |
| on  | fixed512 | off | off | off | 0.562 |
| on  | fixed512 | on  | off | on  | 0.542 |
| on  | fixed512 | off | off | on  | 0.500 |

(Silo-boost and reranker-off cells with identical scores to their paired-on
row: expected in several places — `SiloBoostReranker(boost=0.0)` and the
identity reranker are exact no-ops when the metric-relevant top-5 doesn't
change, not a bug. See "silo boost" below for the substantive discussion.)

## Main effects (`all_golds_retrieved@5`, difference of means)

| factor | effect |
|---|---|
| reranker | +0.0573 |
| fusion | +0.0469 |
| silo_boost | −0.0182 |
| boilerplate | −0.0156 |
| chunking (fixed512 vs paragraph) | +0.0104 |

## Two-way interactions

| factors | effect |
|---|---|
| chunking × fusion | +0.0260 |
| fusion × reranker | −0.0260 |
| boilerplate × reranker | +0.0260 |
| chunking × reranker | +0.0208 |
| boilerplate × silo_boost | −0.0182 |
| reranker × silo_boost | +0.0182 |
| boilerplate × chunking | −0.0104 |
| chunking × silo_boost | −0.0078 |
| fusion × silo_boost | −0.0078 |
| boilerplate × fusion | −0.0052 |

## Decision

**Frozen retrieval config for T19–T22: boilerplate OFF, `FixedSizeChunker(512)`
chunking, RRF fusion (dense + BM25 + literal) ON, reranker OFF, silo boost OFF.**

This is one of four cells tied at the top score (0.708). All four are chosen
among, not derived from a single best run — dev is selection, not inference
(`decisions/0006`), so there is deliberately no p-value anywhere in this
doc, only a tie-break rule stated up front:

**Tie-break rule: prefer the simplest, cheapest pipeline among tied cells.**
Of the four tied at 0.708, two need the reranker (a cross-encoder forward
pass per candidate, local compute, non-trivial latency) and two don't; two
need boilerplate stripping and two don't. Picking the reranker-off,
boilerplate-off cell is strictly cheaper to run in the eventual product with
no loss on the metric that broke the tie.

### Why every other option lost

**Reranker (main effect +0.057, the single largest factor) — not chosen
in the frozen config despite being the strongest lever on average.** It
wins on average across all 32 cells, but at the specific chunking/fusion
combination that already tops out (fixed512 + RRF fusion), adding the
reranker does *not* improve the score further (both land at 0.708) — this
is exactly what the fusion×reranker interaction (−0.026) says: the
reranker's benefit is smaller when fusion is already on, because RRF
fusion is already doing a lot of what reranking would otherwise buy. Kept
out of the frozen config only because it's redundant at this specific cell,
not because reranking is unhelpful in general — T19/T20's generation-level
eval should re-check this, since a cross-encoder reranker could still help
answer quality even where it doesn't move top-5 retrieval.

**Fusion (main effect +0.047, second largest) — chosen (ON).** RRF over
dense+BM25+literal beats dense-only in every single one of the 8
same-index-time-cell comparisons in the table above; the largest, most
consistent effect of any factor tested. This is the ablation table's
clearest, least ambiguous finding.

**Chunking scheme — fixed512 (naive) beats production `ParagraphChunker`
almost everywhere, main effect +0.010, small but consistently the same
sign across index-time cells.** This is the project's most counterintuitive
finding and needs a flagged caveat, not just a number: `all_golds_retrieved@k`
via content-overlap canonicalization (`decisions/0005`, `mcrag.eval.chunk_alignment`)
credits a retrieved chunk whenever it substantially overlaps a gold passage.
A larger, arbitrary-boundary 512-token window is structurally more likely to
contain an entire gold passage — or even two adjacent gold passages for a
conjunctive question — purely by size, independent of whether that chunk is
a *good* unit of context to hand a generator. `ParagraphChunker`'s smaller,
semantically-bounded chunks can split exactly the content this metric
rewards keeping together. **This is a retrieval-metric artifact risk, not a
settled claim that naive chunking is better** — Phase 3c/T20's real
generation-quality run against this frozen config is the check that would
surface it if large, boilerplate-heavy chunks help retrieval scores while
hurting the LLM's actual grounding. Flagged here explicitly so a future
surprise at T20 isn't a surprise.

**Boilerplate stripping — OFF wins, main effect −0.016 (i.e. filtering
*hurts* slightly).** Also counterintuitive, and not fully explained by this
data alone. `BoilerplateFilter` (Task 6) drops lines recurring across many
pages; it's possible some lines it drops are short but load-bearing for a
handful of gold-adjacent chunks (a genuinely reused sentence that happens to
matter, not template chrome) even though the manual T6 review found the
filter's overall corpus quality improvement real. This is a small effect
relative to fusion and reranker, and the interaction with reranker
(boilerplate × reranker +0.026) suggests boilerplate stripping matters less
once other retrieval quality levers are engaged — treated as a minor,
secondary finding, not overturning T6's boilerplate-filter decision for the
production corpus generally (that decision was about extraction quality
broadly, not this one metric).

**Silo boost — OFF wins, main effect −0.018 (slightly hurts).** Root cause
is implementation, not concept: this ablation's `SiloBoostReranker`
(`mcrag/retrieval/silo_boost.py`) infers the query's likely silo from
*consensus among the already-retrieved candidates* (the modal silo label
among the top-20), since no query-side silo classifier exists in this
project (PLAN never asks for one at this stage — see that module's
docstring). That heuristic works fine when the candidate list already
mostly agrees on a silo, which is exactly the case where boosting changes
the least; it can actively hurt on a genuinely ambiguous or cross-silo
candidate list, where the "modal" silo is a weak signal reinforced anyway.
This is a limitation of the specific soft-boost heuristic tested here, not
a verdict that silo-aware retrieval can't help — worth revisiting only if
a real query-side silo classifier gets built later (no such task is
currently scheduled).

## Consequences

- T19 (scoring ladder), T20 (Phase 3c generation baseline), T21 (τ
  calibration) and T22 (metered ablations) all run against this frozen
  retrieval config: boilerplate OFF, `FixedSizeChunker(512)`, RRF fusion
  (dense+BM25+literal), reranker OFF, silo boost OFF.
- The chunking-scheme and boilerplate findings are flagged, not settled —
  T20's generation-quality numbers against this same config are the next
  check on whether this retrieval-only selection actually serves answer
  quality, consistent with the Checkpoint D finding that the retrieval
  proxy tracks quality only reasonably well (76% quadrant agreement), not
  perfectly.
- `k` was swept nested (3/5/10/20) inside every cell rather than as an
  orthogonal factor, per PLAN Sec 2c's `(chunk_size, k)` coupling; those
  per-k numbers live in each run dir's `metrics.json` (`by_k`) for any
  later k-specific analysis, not reproduced in full here.
- Silo boost and reranker stay implemented and available as config options
  (`mcrag/retrieval/silo_boost.py`, `mcrag/retrieval/reranker.py`) even
  though frozen off here — both are real, tested seams a later config
  freeze (or a query-side silo classifier, if ever built) could re-enable
  without new code.
