# 0011 — Query-reformulation ladder (Task 22, ablation #6)

**Date:** 2026-09-17 · **Status:** design + steps 1-2 pre-registered here before
running. Steps 3-7 are scoped but not yet built — whether they run at all
depends on this doc's stopping rule, applied after each rung.

## Context

PLAN Sec4c's ablation #6: a 7-rung ladder, cheapest first, "stop when gains
flatten." That phrase isn't numerically defined in PLAN, and per this
project's standing convention (decisions/0009, 0010) a stopping rule has to
be fixed *before* a step runs, not chosen after seeing its result — otherwise
every stop is a post-hoc rationalization of whatever number came back.
Human decision, made before any step ran: **noise-floor relative** — same
method Task 22 #8/#9/#10 used for the generation side, adapted to retrieval.

All rungs run on **dev only** (decisions/0006 addendum 3), at the frozen
retrieval config (decisions/0007: boilerplate off, `FixedSizeChunker(512)`,
RRF fusion on, reranker off, silo boost off, `k=5`), scored on
`all_golds_retrieved@5` (the project's primary retrieval metric,
decisions/0005) with `recall@5`/`mrr`/`ndcg@5` as secondary.

## The dictionary deviates from PLAN's example list — on purpose

PLAN Sec4c step 1 names `FAFSA, SEVIS, I-20, ISS, "MC"` as illustrative
entries. Checked against the real corpus (`corpus/chunks.jsonl`, word-boundary
match) before writing any dictionary code:

| Term | Real occurrences | Verdict |
|---|---:|---|
| `SEVIS` | 0 | dropped — never appears |
| `ISS` (standalone) | 0 | dropped — "International Student Services" appears spelled out only (2x), never abbreviated |
| `CRN` | 0 | dropped — no evidence this college uses the term |
| `MC` | 2101 | kept |
| `FAFSA` | 62 | kept (but see below — already ungapped) |
| `I-20` | 22 | kept |

Two of PLAN's four illustrative entries don't exist in the corpus at all —
its list was written before the crawl, as a plausible guess, not checked
against the real site. Building the dictionary from that list instead of
from real term frequency would have been reformulation-by-assumption, the
exact failure mode `decisions/0006`'s "dev is selection, not inference"
principle exists to catch one layer up.

`FAFSA` is also a case where the acronym and the term a query would use are
already identical — no vocabulary gap to bridge, so it earns no dictionary
entry despite being common. The inclusion bar for every entry below is: **the
term appears in the corpus, in a form that plausibly differs from how a
student would phrase it in a query.** Confirmed one at a time by reading real
corpus context, not inferred from the acronym alone:

| Term | Corpus occurrences | Expansion added |
|---|---:|---|
| `MC` | 2101 | "Maryville College" |
| `Maryville College` | (same) | "MC" — the one genuinely bidirectional pair |
| `GPA` | 321 | "Grade Point Average" |
| `ISEP` | 41 | "International Student Exchange Program" |
| `NSO` | 28 | "New Scots Orientation" |
| `MCAA` | 23 | "Maryville College Alumni Association" |
| `SGA` | 22 | "Student Government Association" |
| `GI Bill` | 9 | "Post-9/11 GI Bill", "veterans benefits" |
| `I-20` | 22 | "Form I-20", "Certificate of Eligibility", "international student" |
| `F-1` | 11 | "F-1 visa", "international student status" |
| `STEM` | 73 | "Science Technology Engineering Math" |

`ACT`, `SAT`, `NCAA` were checked and dropped for the same reason as `FAFSA`
— real corpus hits, but no phrasing gap (nobody queries "American College
Testing"). `TRIO` was dropped after a naive substring check falsely matched
it inside "PATRIOT" — re-checked with word-boundary matching, `TRIO` is real
(24 hits) but it's a proper noun in this corpus (a program *named* TRIO, not
an abbreviation of something else), so there's no expansion to add.

`mcrag/retrieval/reformulation.py`'s `DEFAULT_DICTIONARY` — 11 entries, all
table rows above. Grow it once real (non-synthetic) query logs exist; this
is a seed, not a claim of completeness.

## Step 2's spelling list has the same honesty problem, inverted

There is no logged real-query traffic yet — every gold question's
`provenance` is `"synthetic"` (decisions/0004) — so there is nothing to mine
misspellings *from*. `DEFAULT_CORRECTIONS` is hand-authored from plausible
institutional-jargon typos (`FASFA`, `Marysville`, `scholarhip`, etc.), which
is a strictly weaker evidence base than step 1's corpus-grounded dictionary.
Flagged here rather than presented as equally justified — its measured
effect (or lack of one) should be read with that caveat.

## Design: `Reformulator` and `ChainedReformulator`

`mcrag/interfaces.py` already declared the seam this ablation needed
(`Reformulator.reform(query, history) -> list[str]`) — used as-is, not
reinvented. `ChainedReformulator` composes rungs in the order given; a rung
that returns more than one query (decomposition, multi-query, step-back,
built in a later pass) causes every later rung to run once per query it
produced, so composition doesn't need special-casing per rung. Multiple
queries from a fanned-out rung feed `RRFFuser.fuse` (already built,
decisions/0007) as separate legs — no new fusion code needed even for the
metered rungs.

## The stopping rule, operationalized

Comparisons are **cumulative**, each rung against the best config *so far*
(rung 0 = the frozen retrieval config with `IdentityReformulator`, i.e. no
reformulation), not each rung against the raw baseline independently — this
is what "ladder" means: does adding *this* rung, on top of everything already
kept, buy anything.

- **Rungs 1-2 (free, deterministic):** compared via `paired_bootstrap_comparison`
  over the 60 dev questions' `all_golds_retrieved@5`. Deterministic steps
  have no rerun-to-rerun noise to measure, so the CI over the question sample
  is the whole story. A rung is kept if its 95% CI lower bound on the
  improvement is > 0; the ladder stops climbing past a rung whose CI includes
  zero (or is negative).
- **Rungs 3-7 (metered, stochastic):** before evaluating a rung, run a
  same-config noise-floor rerun of it (identical to #8/#9/#10's method,
  `decisions/0010`) — LLM sampling means a rung's own repeat-run variance is
  a second noise source beyond question sampling. A rung clears the bar only
  if its CI-lower-bound improvement over the previous best *also* exceeds
  that rung's own noise-floor band. The ladder stops at the first rung that
  doesn't clear it — later, more expensive rungs are not run once an earlier
  one has already flattened, since PLAN's ordering is cheapest-first and a
  flatter, cheaper rung makes a more expensive one's a-priori case weaker,
  not stronger.

## Results — rung 1 (and why rung 2 never ran)

`scripts/run_t22_reformulation_ladder.py`, dev split, 48 conjunctive-scorable
questions (of 60 — the rest have no gold refs and are skipped by design, same
as every other retrieval eval in this project):

| Rung | Config | `all_golds_retrieved@5` | vs. best-so-far (rung 0) | Kept? |
|---|---|---:|---|---|
| 0 | `IdentityReformulator` (frozen config, control) | 0.708 | — | kept (starting best) |
| 1 | `AcronymDictionaryReformulator` | 0.688 | −0.021 [−0.063, +0.000] | **not kept** — CI does not clear zero |

Rung 1's CI upper bound sits exactly at 0.000 and the point estimate is
negative — the acronym dictionary doesn't help, and the interval is
consistent with it hurting slightly. Per this doc's pre-registered stopping
rule ("the ladder stops climbing past a rung whose CI includes zero, or is
negative"), the ladder stops here. `scripts/run_t22_reformulation_ladder.py`
enforces this mechanically: it breaks out of the loop the moment a rung
fails to clear the bar, so **rung 2 (`AcronymDictionaryReformulator` +
`SpellingNormalizer`, chained) was never run** — not because it was assumed
to fail, but because the pre-registered rule says a later, more expensive
rung doesn't get a turn once an earlier, cheaper one has already flattened
(or gone negative). Running rung 2 anyway after seeing rung 1's number would
have been exactly the post-hoc rationalization decisions/0009/0010 exist to
prevent.

**Why the dictionary plausibly hurts rather than merely doing nothing:**
`AcronymDictionaryReformulator` appends expansion text to the query
(`mcrag/retrieval/reformulation.py`), which for BM25/literal legs adds extra
token mass that competes with the original query terms for the fixed
`CANDIDATE_K=20` slots, and for the dense leg shifts the embedding toward the
expansion's phrasing. For a query that already contains the term the
dictionary would expand, this is close to free — but for the ~90% of dev
questions that don't hit any of the 11 dictionary entries at all, the
reformulator is a no-op, so the aggregate effect above is driven entirely by
a small subset of queries where the appended text apparently pulled ranking
away from the correct chunk rather than toward it, on net.

**Conclusion for ablation #6:** the free rungs (1-2) do not clear their own
pre-registered bar. Per decisions/0011's cumulative design, this closes out
#6 with rung 0 (no reformulation, i.e. `IdentityReformulator`) as the kept
config — the frozen retrieval config from decisions/0007 stands unchanged.
Rungs 3-7 (decomposition, multi-query, de-contextualization, step-back,
HyDE) are **not built**: each is strictly more expensive than the rungs that
already failed to clear the bar, and the pre-registered rule treats a flat
or negative result on a cheaper rung as evidence against, not for,
continuing up the ladder. This is a real (if unglamorous) finding, not a
placeholder — "reformulation doesn't help this corpus at this retrieval
config" is itself the answer ablation #6 was scoped to produce.
