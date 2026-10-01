# 0020 — A stale count nobody computed is `unchecked`, not `0`

**Date:** 2026-10-01
**Status:** accepted
**Task:** T35 (gold-set decay), and the review of the subagent that built it

## Context

T35 pins each gold reference to the `content_hash` of the page it was read from, so a
page that changes after the gold answer was authored marks its questions **stale** and
drops them from the metrics until a human re-reads the page. The mechanism is only worth
having if the number it produces is impossible to not see. A decay detector that is easy
to leave switched off measures nothing and *looks* like it measures something, which is
worse than not having one.

The first implementation (a Haiku subagent, working to a brief that pre-set the schema,
the provenance rule, and the append-only log) got the data model right and the plumbing
wrong in one specific way, described below. This doc records the design decision that
resolved it, every arm considered, and the two other defects found in the same review.

## Decision

`mcrag.eval.retrieval_harness.run` takes `stale_qids` as a **required keyword argument
with no default**. Passing a set excludes those questions and reports the count. Passing
an explicit `None` means *"I did not check"*, and is recorded as `n_stale: "unchecked"`
in `metrics.json` and rendered `?` in RESULTS.md's `scored / stale` column.

`0` is reserved for *checked, and nothing was stale*.

## Arms considered

| arm | what it does | why it lost |
|---|---|---|
| **A. `stale_qids: set \| None = None`** (as built) | optional; omitted means no exclusion | Every existing caller keeps compiling and keeps not checking, and `summarize` reports `n_stale: "0"` for all of them. The one production caller, `scripts/run_baseline_eval.py`, did not pass it — so **no code path actually excluded anything**, while every results row claimed zero decay. The feature was inert and self-certifying. |
| **B. harness computes staleness itself** | `run` loads `corpus/chunks.jsonl` and derives the stale set | Couples scoring to a corpus path the harness otherwise knows nothing about, and makes every unit test construct a corpus to score two fake questions. Also silently picks *which* corpus is authoritative, which is the caller's decision (the baseline arm scores against a differently-chunked set). |
| **C. required keyword; `None` means explicitly unchecked** | caller must type something; both answers are recorded | **Chosen.** The check cannot be forgotten, only declined — and declining is written into the artifact. A unit test that genuinely has no corpus passes `None` or `set()` in one word. |
| **D. required, must be a set** | no escape hatch at all | Forces a corpus into tests whose subject is interval arithmetic. The honest escape hatch is more useful than the absent one, as long as taking it is on the record. |

Rendering, decided the same way: `?` over `0` for a run with no `n_stale` key (every run
recorded before pinning existed) and for `"unchecked"`. This is the rule the project
already applies to a latency stage that did not run — `null`, never `0.0`
(`docs/stream_contract.md`) — and the rule `results_table` already applies to an unknown
split (`?`) and a run that spent no quota (`--`).

## The other two defects found in the same review

1. **The verification test reported green without verifying anything.** It guarded on
   `if not gold_path.exists(): return` — four such bare `return`s, not `pytest.skip` — so
   a checkout without a corpus, or a gold set that had lost its pins, produced a passing
   test that had executed none of its assertions. This is the same failure shape as the
   CRLF-intolerant regex found in `clients/verify_chat_client.mjs` during T29's follow-up:
   a guard that silently verifies nothing is strictly worse than a missing guard, because
   it occupies the slot where a real check would go. Rewritten: missing corpus is an
   explicit `pytest.skip`, a gold set with no pins is a **hard assertion failure** (the
   committed set has pins; losing them is the regression under test), and the test now
   drives `run()` and `summarize()` end to end so that *"drops out of metrics"* is
   measured rather than asserted in a docstring.

2. **Records were rebuilt field by field.** `backfill_pins` and `reverify_pin` each
   constructed a new `GoldQuestion` by listing all eleven fields. A twelfth field added
   later would have been silently dropped by the backfill — quiet data loss in the one
   artifact T35 exists to protect. Both now use `dataclasses.replace`.

## Verification

Four mutations, each reverted after, each caught by the assertion intended to catch it:

| mutation | caught by |
|---|---|
| `summarize` reports `str(len(stale))` unconditionally | 3 tests |
| the `stale_qids` skip removed from `evaluate_question` | 2 tests |
| `results_table` renders an unchecked count as `0` | 1 test |
| `stale_qids` given a default again | 1 test |

Full suite: 760 passed. `scripts/backfill_gold_pins.py` re-run leaves
`data/gold/gold_v1.jsonl` byte-identical (`git hash-object` unchanged), and `split.lock`
still verifies against the recomputed `split_hash` — pinning touched no field the split
depends on.

## What this does not claim

The pins record what the corpus snapshot says **today**, under `origin="backfill"`. They
are not evidence that anyone re-read those pages. Only an `origin="reverified"` pin, with
its line in `data/gold/reverification_log.jsonl`, carries that claim.
