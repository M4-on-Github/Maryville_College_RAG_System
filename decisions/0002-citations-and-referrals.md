# 0002 — Citations and referrals are two different links

**Date:** 2026-09-10 · **Status:** accepted, extends `PLAN.md` §4d and Task 8

## Context

`PLAN.md` already requires every answer to cite its sources, and already
requires a refusal to name the office that owns the question. What it does not
have is a link the user is meant to *go to*, as distinct from the page the
answer was *derived from*.

Those look like the same thing and are not. Decision 0001 makes the difference
concrete: the catalog's degree-requirement pages are robots-disallowed, so we
will never hold a chunk of one, and every requirements question is a refusal.
A refusal that names the registrar is better than "I don't know." A refusal that
names the registrar *and hands over the catalog URL* is better still, and
nothing in the corpus design prevents it. The URL is public, it is in the
site's own sitemap, and handing it to a person is not crawling it.

## Decision

**An answer carries two kinds of link, and they never merge.**

| | Citation | Referral |
|---|---|---|
| Answers | "where did this claim come from" | "where should I go next" |
| Must be in the corpus | **yes**, a retrieved chunk's source URL | **no** |
| May point at a robots-disallowed page | never | yes |
| May be quoted from | yes, that is the point | **never** |
| Source | retrieval, per query | curated table, per silo |
| Graded as | citation accuracy, citation validity | referral correctness |

**1. Citations stay exactly as specified.** A factual claim without a supporting
retrieved chunk is still ungrounded, and still scores 1 rather than 2. Nothing
here loosens that.

**2. Referrals come from a curated table, not from the model.** The
contact-routing table Task 8 produces at discovery step 3 gains a destination
column: per silo, the office, its contact address, and the one page a person
should land on. Small, hand-checked, and reviewable in a sitting. A model asked
to invent a helpful URL invents a plausible one, which is the same hallucination
failure as an invented deadline and harder to spot.

**3. A referral is never evidence.** The generator may not read, quote, or
paraphrase a referral target. For a disallowed page we hold no text at all, so
there is nothing to quote; the rule is written down anyway so that it still
holds on the day a referral points somewhere we did crawl.

**4. Referrals attach to three outcomes, not just refusals.**
   - *Answered*: cite the sources, then offer the destination page for depth.
   - *Partially answered*: say which part is unsupported, refer for that part.
   - *Refused*: name the office, its contact, and the destination page.

The requirements case is the third: "I can't confirm the requirements for the
biology major. The catalog is at `/academics/catalog/` and the Registrar's
Office is the office that owns this."

**5. This is a product feature, not a new ablation arm.** It is deterministic
and costs no quota to evaluate, so it is measured at Tier 0 alongside citation
accuracy. Making it an arm would spend the metered budget on a table lookup.

## Consequences

- **Task 8 grows a column.** The routing table becomes silo → office → contact →
  destination URL. Still a byproduct of discovery, still not follow-on work.
- **The gold schema grows a field.** A question's gold record gains an expected
  referral where one applies, so refusal correctness splits in two: did it
  refuse when it should, *and* did it route to the right place. Task 12.
- **One new Tier 0 metric: referral correctness.** Free, deterministic, reported
  with an interval and an n like everything else.
- **A new maintenance check.** Referral URLs are hand-written and therefore rot
  silently. Phase 7 adds a HEAD check over the table. It is a table of tens of
  URLs, so this is cheap.
- **The limitation stays a limitation.** This does not recover degree
  requirements. It makes the gap land as a useful redirection instead of a dead
  end, which is the most the robots exclusion allows.
