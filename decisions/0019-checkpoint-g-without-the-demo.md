# 0019 — Checkpoint G closed without the recorded demo (T33)

**Date:** 2026-09-30 · **Status:** decided and applied. **Decided by:** the project owner,
explicitly ("close checkpoint G without the demo"). Not a silent tick — this doc exists
because the gate's acceptance criteria are being **amended**, and an amended gate that
leaves no record is indistinguishable from a gate that was quietly lowered.

## What the gate said

```
### ✅ Checkpoint G — shipped
- [ ] `RESULTS.md` generated, limitations written, demo recorded
- [ ] Ablation table is the centerpiece, not the demo
```

## What it says now

Criterion 1 drops **"demo recorded"** and keeps `RESULTS.md` and the limitations writeup.
Criterion 2 is unchanged. T33 stays **open and unticked** in `tasks/plan.md` and
`tasks/todo.md`; nothing about it is marked done, and no demo is claimed anywhere.

## Why this is defensible on the gate's own terms

The gate's second criterion already states the ordering: **"Ablation table is the
centerpiece, not the demo."** The demo was scoped as supporting material for an artifact
that carries the result on its own. Criterion 1 required the demo anyway, which puts the
checkpoint in the position of being blocked by the item its own next line calls
secondary. Dropping it resolves that, and does not promote the demo's absence into a
claim that it was unnecessary.

## Why it is being dropped rather than done

Two reasons, both recorded rather than smoothed over:

1. **No recording capability in the working environment.** The assistant doing the work
   cannot capture video, and the Chrome extension was not connected in the sessions where
   this came up. T33 is a human task, not a deferred automation task.
2. **A substantive blocker that predates the scheduling question.** T33 requires a
   cross-silo question demonstrated end to end, and the `TAU` gate refuses heavily — no
   cross-silo dev question has been found that passes it. So even with a camera, the
   middle third of T33's first acceptance criterion has nothing to film today. That is a
   finding about the gate's over-refusal, already logged as an open item in
   `docs/LIMITATIONS.md` §7, and it is the real reason T33 is hard.

Point 2 matters more than point 1: if T33 is ever picked up, the gate over-refusal has to
be addressed first, or the demo will show a refusal where a cross-silo answer was meant
to be.

## What is verified, as of this close

Checked today, not inherited from an earlier session:

- `RESULTS.md` **regenerated** by `scripts/generate_results.py`. It was **stale** — it
  predated the T41 and T41b runs — and now carries all six of those run rows in the main
  table and in the Pareto section. Found while verifying the gate rather than assumed.
- `RESULTS.md` and `results_pareto.svg` are **byte-identical on a second regeneration**,
  which is the determinism property T30 claims.
- The ablation table is the first and largest thing in the file, ahead of every other
  section: criterion 2 holds by inspection.
- `docs/LIMITATIONS.md` is written and current to T41b, including the layer table, the
  measured layer-5 blind spot, both rejected labelling attempts, and the
  `decisions/0010` pooling deviation.
- Full suite: 734 passed.

## What this close does **not** claim

- **No end-to-end walkthrough visible to a human has ever been recorded.** The stream
  contract was exercised at zero generation quota against `serve_reference_client_demo.py`
  and under a stubbed DOM (T29), and the injection suite ran live (T39), but the reference
  client has never been driven in a real browser against live `gemma4:31b`. That gap was
  already stated in T29's result and stays stated.
- **Sources-render-before-answer has not been shown on camera.** It is measured — T42
  reports the ordering with timings, and corrects the earlier "at least 1 s" claim down to
  a median 0.950 s — but a measurement is not the demonstration T33 asked for.
- Closing Checkpoint G says the portfolio artifacts are done. It does not say the project
  has a demo.

## Consequence

Phase 6 is closed. Phase 7 (T34-T36, Checkpoint H) is the only substantive work left, and
by standing rule it does not start without its own go-ahead. T33 remains available to
reopen; if it is, this doc is the record of what closing without it did and did not mean.
