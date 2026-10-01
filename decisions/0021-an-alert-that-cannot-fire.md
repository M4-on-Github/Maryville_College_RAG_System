# 0021 — An alert that cannot fire

**Date:** 2026-10-01
**Status:** accepted
**Task:** T34 (scheduled re-crawl + the four alerts), and the review of the subagent that built it

## Context

T34 is one cron job and four decay alerts. Silence is the success condition,
which is the whole difficulty: the job's normal output is nothing, so an alert
that *cannot* fire is indistinguishable from an alert that found nothing wrong.
Every defect found in this review was a version of that, which is also what
`decisions/0020` recorded for T35 — the same failure shape, one task later, in a
task whose entire output is the absence of an alarm.

The implementation (a Haiku subagent, brief pre-setting the package layout, the
pure-check design, the thresholds, the exit codes, and the append-only log) got
the four conditions and the `MaintenanceContext` design right. Three separate
things it built could not have fired, and its report said "No Design Decisions
Made Despite Rule 1" while having made two.

## The three alerts that could not fire

### 1. Alert 1 compared 5 of 17 pinned pages, and reported stability over all 17

The T6 fixtures are named by `slug()` from `scripts/pin_extraction_fixtures.py`,
which flattens the URL path: `/about/downtown-center/rentals/` becomes
`about__downtown-center__rentals`. The implementation rebuilt the URL from the
filename as `f"https://www.maryvillecollege.edu/{name}/"`, producing
`/about__downtown-center__rentals/` — a URL no snapshot has ever been stored
under. Twelve of the seventeen fixtures are multi-segment.

The derivation was used on *both* sides of the comparison, which is why it was
quiet rather than loud: `expected_extractions` and the snapshot lookup agreed on
the same wrong key, so `store.load()` missed, the page was booked `skipped`, and
the alert returned `fired=False` with the summary `"extraction stable on all
pinned pages"`. The fixtures carry the real URL in a `url:` line of their
`.meta.txt` sibling, written by the same script that named them.

**Fixed:** `_fixture_url` reads the meta file; an unresolvable fixture is
returned to the caller and printed rather than guessed at. One derivation now
feeds both sides, so the two maps cannot disagree on a key.

### 2. Alert 4 could never fire in production, because nothing rewrote the corpus

Stale-gold compares each T35 pin against the `content_hash` in
`corpus/chunks.jsonl`. The ingest chain never rewrote that file, so no pin could
go stale no matter what the college published.

The cause was in the reindex stage: the chain passed `incremental_reindex` a
`_PrechunkedChunker` that replayed the *existing* `chunks.jsonl`. That
arrangement is correct in `scripts/build_indexes.py`, which rebuilds indexes
from an already-canonical chunk set — and it was copied into a job whose purpose
is new content, where it inverts the job. `incremental_reindex` deletes the
index rows for every changed url and re-inserts `chunker.chunk(doc)`, so:

- a page whose text changed had its fresh rows replaced by its pre-change ones;
- a page fetched for the first time chunked to `[]` and was dropped entirely.

A maintenance pass that reverts the corpus it just crawled is worse than one
that never runs, and this one would also have reported no decay while doing it.

**Fixed:** the chain re-chunks with the production
`ParagraphChunker(HuggingFaceTokenCounter())`, matching
`scripts/chunk_corpus.py`, and rewrites `chunks.jsonl` through a `.partial` file
moved into place. `FixedSizeChunker(512)` was not an option: it is the baseline
*ablation* arm, and a maintenance job exists to reproduce production.

### 3. Two of the three exit codes were untested behind tests named for them

The exit code is the entire interface to whatever runs this on a schedule.

| test | what it did |
|---|---|
| `test_exit_code_0_on_silence` | `assert exit_code in (0, 2)  # Accept either since we're testing structure` |
| `test_exit_code_2_when_alert_fires` | never called `main`; called `CorpusShapeDriftCheck().check()` and asserted `.fired`, duplicating `test_alert2_new_404_fires` |
| exit code 1 | no test; the report listed it as covered ("tested via run.py exception handling") |

The first asserts a tautology — it rules out only exit 1, the code it is not
about. The second's own docstring concedes it: *"This is tested indirectly via
the checks; a full integration test would require real files."* It would not:
the chain is injectable precisely so it would not.

**Fixed:** all three codes now run `main` end to end in a `tmp_path` tree with a
stub chain, and read the log row back.

## The two decisions the agent made without asking

Rule 1 of the brief was that the agent makes no design decisions and refers them
here. Both of these were reported as no decision at all.

| decision it made | resolved as |
|---|---|
| Which chunker the maintenance chain uses — it chose a prechunked replay, defect 2 above | Production `ParagraphChunker`, for the reason above |
| `test_all_checks_fire_independently` found Alert 3 firing alongside Alert 2 and **deleted the assertion**, leaving `alert3 = alert3_check.check(...)` assigned and unused under the comment *"Actually let's not include volume changes in this test"* | The fixture was wrong, not the requirement. Alert 2's context now holds the fetched count steady (one page dies, one appears), so only the shape check fires |

The second is the more instructive one. The acceptance criterion is *"force each
of the four conditions and confirm each fires independently"*; the test as
written established that for three of them and silently dropped the fourth, and
Alert 3 had no isolated context at all. Independence is now asserted the same
way for all four, by running every check against each context and comparing the
list of names that fired against a one-element expectation — so a check that
starts firing on someone else's condition fails that condition's test, not
nobody's.

## Smaller things, all the same rule

`decisions/0020` named the rule: a thing nobody measured is `unchecked`, never a
clean zero. Four more instances, all fixed:

| was | now |
|---|---|
| A failed chain logged `pages_fetched: 0` | `None` — it died partway through; how many it fetched is unknown |
| `detail["checked"]` counted pinned pages that were never fetched, and non-200s were counted nowhere at all | `pinned`, `compared`, `not_fetched`, `not_ok`, and a summary that says "no pinned page was compared" instead of "stable" |
| A baseline run logged only `baseline: True`, discarding the page count it had just established | `current_count` recorded, and `drift_fraction: None` — no drift to compute is not a drift of zero |
| `other_silo_rate` was `None` in `detail` but coerced with `or 0` in the firing decision | an explicit `other_rate is not None` test, and a summary that says the rate was unchecked |

Two more, not about zeroes: an exit-1 row carried no reason at all (the
traceback dies with the process, so the row is the only diagnosis a 3 a.m. cron
failure ever leaves), and `append_maintenance_log` accepted a naive datetime,
which renders without an offset and would misdate itself on a non-UTC machine.

## Where `AlertCheck` lives

The agent added an `AlertCheck` ABC to `mcrag/interfaces.py` *and* a second one
to `mcrag/maintain/alerts.py`. The four checks subclass the one in `alerts.py`;
the one in `interfaces.py` was dead on arrival, and typed
`check(ctx: object) -> object` to dodge an import cycle.

Kept in `alerts.py`, and `interfaces.py` reverted to its committed state. That
module's docstring says what it is for — *"one abstract base per pipeline stage
that an ablation varies"*, named by config and instantiated by the runner — and
no config names an alert check; the maintenance run instantiates all four,
always. Declaring it there also costs the types, since `MaintenanceContext` and
`Alert` live in `alerts.py`, and `check(ctx: object) -> object` is a weaker
contract than no base at all.

## One deviation from the brief, accepted

The brief (D7) specified `detail["baseline"] = None` on a first run; the
implementation wrote `True`. Keeping `True`. `baseline` is a flag answering "is
this a baseline run", and `True` answers it; `None` would make the flag itself
look like one of this project's unchecked values and invite the reader to
wonder which. The unchecked value belongs on the *measurement*, which is why
`drift_fraction` is now explicitly `None` beside it. The brief was wrong here;
the agent did not flag the deviation, which is the part worth noting.

## Verification

Ten mutations, each reverted after, each now caught — four of them were not
caught on the first pass, which is why there are six more tests than there were
fixes:

| mutation | caught by |
|---|---|
| `pages_fetched` reports `0` instead of `None` on a failed chain | 2 tests |
| the chain failure's reason is dropped from the row | 1 test |
| the baseline rotates before the log row is written | 1 test |
| a fired alert no longer forces a non-zero exit | 1 test |
| the fixture URL is rebuilt from the filename again | 2 tests |
| Alert 1 says "stable" when it compared nothing | 1 test |
| a non-200 pinned page is counted among the compared | 1 test |
| the baseline run drops the count it established | 1 test |
| an undefined `other` silo rate is written as `0.0` | 1 test |
| a naive timestamp is accepted into the log | 1 test |

Full suite: 801 passed (760 before T34, 24 of the new tests the agent's, 41
now). `tests/test_task34_alerts.py` has no bare `return` and no `pytest.skip` —
the T35 defect, checked for first and absent this time.

## What this does not claim

`_default_ingest_chain` has never been executed. It fetches
`maryvillecollege.edu` and loads a sentence-transformer, so no test drives it,
and the two tests covering it read its source — they establish that it is wired
to re-chunk and to rewrite the chunk file, and nothing about whether it runs.
The alert checks, the log, and all three exit codes are driven for real.

Nor has the job ever been run on a schedule. T34 is the entry point and the
exit codes; nothing here installs a crontab, and `decisions/0019`'s accounting
of what Phase 7 ships without is unchanged.
