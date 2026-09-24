# 0016 — Service refusal classifier (T40)

Date: 2026-09-24. Split: **dev and the 4 live cases only. Test was not read**
(the replay script filters on `eval.split == "dev"`).

## Why

The live safeguard check (`docs/LIMITATIONS.md` §7) found that 4 of 7 attack cases
were refused by `gemma4:31b` in its own wording, but
`mcrag.eval.tier0_scoring.looks_like_a_refusal` did not match them, so the service
streamed them as ordinary answers with no `refusal` event and no office routing.

The eval classifier is **left frozen**: it is the one every historical
`refusal_correct` number was computed with, including the single test pass
(`decisions/0013`). Changing it in place would silently make past runs
incomparable. The service gets its own classifier (`mcrag/service/refusal.py`).

## Pre-registered before the replay ran

Variants: v0 current (control), v1 widened phrases, v2 cite-nothing, v3 = v1 or v2.

**Pass rule, fixed in `tasks/plan.md` before the run:** a variant is wired only if it
catches all 4 live misses **and** flips zero legitimate answers. Otherwise the result
is logged and nothing ships.

Data: 635 unique (query, answer) pairs from all 15 dev run dirs, plus the 4 live
refusal texts. There are no human refusal labels on saved answers, so v0 is the
reference and every answer a variant newly flags was triaged by hand.

## Results

| Variant | flagged | new vs v0 | catches live misses | verdict |
|---|---:|---:|---:|---|
| v0 current | 86 | 0 | 0/4 | control |
| v1 widened phrases | 128 | 42 | 4/4 | **rejected** |
| v2 cite-nothing | 378 | 296 | 4/4 | **rejected** |
| v3 combined | 386 | 300 | 4/4 | **rejected** |
| v4 narrow phrases (post-hoc) | 86 | 0 | 4/4 | **adopted**, with the caveat below |

### Why v1 lost

All 42 new flags came from one pattern, the broad
`(passages|provided text) ... do not (contain|provide|mention)`. Hand triage of the
35 unique flagged answers: **18 are substantive answers that merely note a gap**
(e.g. `oos-36` gives the Registrar's hours and then says the passages do not mention a
staff meeting; `pilot-cs-01` gives both program directors as contacts; `cs-14` lists how
teacher licensure is structured; `ss-74` explains the IRA rollover gift), 2 are
borderline, 15 are pure refusals. Routing those 18 as refusals would replace real
answers with an office referral. Fails the zero-flip rule.

### Why v2 lost

It flags 378 of 635 dev answers, 296 more than v0. Citation compliance is a model
behaviour, not a refusal signal: `decisions/0010` already measured marker compliance at
0.527, so "cites nothing" mostly identifies answers that did not cite, not answers that
refused. Catastrophic over-refusal. v3 inherits this and loses for the same reason.

### Why v4 won, and what that is worth

v4 is v1 without the broad passages pattern. It catches all 4 live misses through the
first-person refusal wordings (`I cannot comply`, `I must refuse`, `outside the scope`)
and `I am sorry`, and it flags **nothing new** across 635 dev answers.

**Caveat, stated plainly: v4 was added after seeing the v1 replay, so it is post-hoc.**
Its evidence is n=4 for the catches and a zero-regression result on dev. It was not
pre-registered, and no fresh data has tested it. It is adopted because it strictly
dominates the control on the only evidence available and cannot regress dev by
construction, not because it was validated.

## Side finding: the frozen eval classifier under-detects refusals

15 of the 42 v1 flags are pure refusals on dev that v0 also misses. So
`refusal_correct` in every historical run — including the test pass — is computed with
a classifier that misses some genuine refusals. The direction of the bias depends on
whether the question expected an answer, so it does not simply inflate or deflate one
arm. Since arms are compared **against each other** with the same classifier, paired
differences remain meaningful; absolute `refusal_correct` values are less trustworthy
than they look. Recorded in `docs/LIMITATIONS.md` rather than fixed, because fixing it
would break comparability with `decisions/0013`.

## Not done

No live run was spent on this. Whether v4 improves the *live* refusal routing is
answered by T39's regression report, not here.
