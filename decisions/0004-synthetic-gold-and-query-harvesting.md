# 0004 — Synthetic gold set now, real-query harvesting designed for later

**Date:** 2026-09-13 · **Status:** accepted, governs Task 13

## Context

Task 13 authors ~300 gold questions, and PLAN.md already discloses the honest
version of what that means for this project: *"self-authored eval set;
author-is-designer blind spots"* is a named limitation in Phase 6, not
something Phase 2 was ever going to avoid. There is no access to real
Maryville College student queries (a standing project constraint), and PLAN
explicitly scopes public deployment as a *possible later upscale*, not a
Phase 5 goal — so there is no live traffic to harvest a real query set from
even if the project wanted to.

The alternative to pretending otherwise is to name the gap and design the fix
for the day it becomes possible, rather than either (a) shipping a
self-authored set with no way to tell later how much of its performance was
"the system is good" versus "the questions were written to be answerable," or
(b) blocking Task 13 on a deployment phase that isn't happening yet.

## Decision

**1. v1 of the gold set is synthetic, and is labeled as such in the data,
not just in prose.** `GoldQuestion` gains a `provenance` field
(`"synthetic"` | `"real"`, default `"synthetic"`), validated by
`mcrag.eval.gold.validate`. Every question Task 13 authors gets
`provenance: "synthetic"`. This is not cosmetic: once (if) a `"real"`
question ever exists, every eval report can break results out by provenance
instead of silently averaging a system's performance on questions it was
never tested against.

**2. Synthetic questions are drafted from the corpus, never from
imagination.** Every gold ref must be a real `chunk_id` that exists in
`corpus/chunks.jsonl` and actually supports the question's claim — the same
discipline as decision 0002's "a referral is never evidence," applied to gold
authoring: a question is not entered into the set until its refs are checked
against real chunk text, not asserted.

**3. Real-query harvesting is designed now, built later — when there is
traffic to harvest.** If this project ever reaches Phase 5+ deployment (even
an internal alpha, not necessarily the public-upscale checklist), the design
is:
   - The service layer's `answer(question, history) -> events` callable
     (PLAN Phase 5) is the single place a query is logged — never the UI,
     never a third-party analytics service. One local, append-only JSONL.
   - **A logged query is never auto-promoted into the gold set.** A human
     reviews it, corrects the phrasing/refs if needed, assigns a slice, and
     only then does it enter `data/gold/` with `provenance: "real"` — the
     same hand-check discipline decision 0002 required for the office table,
     for the same reason: an unreviewed automatic promotion is exactly how a
     bad label enters the one dataset every later comparison depends on.
   - No query text, email, or other identifying content is ever sent to an
     external service as part of this logging — it stays on the machine
     that ran the query, consistent with the project's standing FERPA-clean
     posture (public pages only, no student records) even though a free-text
     question is not itself a student record.
   - This item is **not built in this pass.** There is no Phase 5 service
     layer yet (Task 13 sits in Phase 2; the service layer is Phase 5), so
     there is nothing to log from. Building the logger now would be
     speculative generality against a callable that doesn't exist.

## Consequences

- `mcrag/types.py`'s `GoldQuestion.provenance` and
  `mcrag/eval/gold.py`'s `PROVENANCE_VALUES`/`validate()` check, both tested
  in `tests/test_gold.py`.
- Task 13's authored set will be 100% `provenance: "synthetic"` — expected,
  not a defect to fix before shipping.
- **Phase 6's limitations section** (already required by PLAN) should point
  at this decision by name rather than restate the caveat from scratch: the
  self-authored-set limitation is real, disclosed, and has a designed (if not
  yet built) mitigation path.
- When Phase 5's service layer is eventually built, its task should reference
  this decision's logging design rather than re-deriving it.
