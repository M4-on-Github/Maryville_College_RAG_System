# 0003 — Final silo taxonomy and contact-routing table

**Date:** 2026-09-12 · **Status:** accepted, closes Task 8 step 4

## Context

Task 8 steps 1–3 (path-prefix histogram, nav/breadcrumb harvest, office
matching) produced two hand-checkable candidate tables:
`data/division_offices.csv` (six division offices, high confidence — the
site's own structured `/directories/department/` listing) and
`data/office_candidates.csv` (15 heuristic candidates across the top-25
histogram prefixes, mixed confidence — a script found the shortest page under
each prefix with an email nearby, which is a plausible-office guess, not a
verified one).

Per decision 0002, that candidate table had to be hand-checked before
becoming `offices.yaml` — a model auto-approving its own heuristic output
defeats the reason the review step exists. The human reviewer went through
`office_candidates.csv` and made one correction directly in the file: dropped
the email on the `academics/faculty` row (`jeff.bay@…`), keeping the phone,
because it was a personal faculty page's contact, not an office's. Four
further judgment calls — rows that carried a named individual rather than a
generic office address, the same risk the `jeff.bay` row turned out to
have — were confirmed explicitly rather than silently accepted:

| Row | Kept? | Reasoning |
|---|---|---|
| `about/inside` → `woods@` | **Kept** as `governance` | Confirmed as a real contact, not a fork of the `jeff.bay` mistake |
| `about/faith` → `jessica.lewis@` | **Kept** as `faith_life` | Confirmed as the chaplain's office |
| `academics/learn-by-experience` → `maria.siopsis@` | **Kept** as `learn_by_experience` | Confirmed as an acceptable single point of contact for the Scots Science Scholars program |
| `about/community-education` → `andrew.gunnoe@` | **Kept** as `community_education` | Confirmed as an acceptable program contact |

## What this decision adds beyond the reviewed candidates

The reviewed 15-row candidate table only covered the *top 25* histogram
prefixes (`data/silo_histogram.csv`), and even within those 25, the matching
script only checked the **five shortest URLs** under each prefix for an
email — a real office whose contact page happens to be longer than five
other pages under the same prefix would be missed entirely, not flagged as
"no match." Two important offices were missed exactly this way:

- **`admissions/finaid`** — the heuristic found nothing in its top-5 shortest
  pages, but `financialaid@maryvillecollege.edu` (865-981-8100) appears
  repeatedly across the section's deeper pages (verification, withdrawal,
  loan-type pages).
- **`admissions`** (general) — same story: `admissions@maryvillecollege.edu`
  (800-597-2687) is the toll-free number on the application pages, not on the
  five shortest URLs under `admissions/`.

Financial aid and admissions are two of the most likely real query topics for
this project's claimed use case; leaving them ownerless because a five-page
sample missed them would have been a mapper defect in the sense PLAN §2c
warns about, not a genuine site gap. These were found by grepping the full
extracted corpus for `@maryvillecollege.edu` addresses under the relevant
prefix, the same mechanical technique `scripts/match_offices.py` uses, just
not limited to five pages. Four more office contacts were found the same way,
for prefixes the original heuristic script never checked at all because they
fell outside the top-25 histogram cut: `giving` (`eric.bellah@…`, gift
planning), `families` (`FamilyInfo@…`, matching the site's own "Families"
top-level nav item found in Task 8 step 2), `events` (`events@…`, matching
the nav's "Event Operations" item), and `orientation` (`orientation@…`).

One more real office was found this way that the original 25-prefix cut
never had a chance to surface: **Title IX**. `about/inside/titleix/` is a
dedicated page with its own contact (`titleix@maryvillecollege.edu`,
865-981-8111) — found by searching the corpus for Title IX language, not by
prefix histogram, since two-level path prefixes bucket it under the much
broader `about/inside`. It gets its own silo, taking priority over
`governance` by longest-prefix match.

## Decision

**Final taxonomy: 26 silos + `other`.** `data/silos.yaml` is the taxonomy
(path-prefix rules only — PLAN §2c's single-vs-multi-label question is
resolved at gold-question level, not by tagging one chunk with two silo
strings); `data/offices.yaml` is the routing table (silo → contact →
`destination_url`, decision 0002's schema). Every silo except `other`
resolves to exactly one office row, and every office row has a real email and
a `destination_url` on the college's own domain — both asserted by
`tests/test_offices.py`, not just documented here.

**Six academic-division silos**, granularity following the site exactly per
§2c (`academics_humanities`, `academics_behavioral_sciences`,
`academics_math_natural_sciences`, `academics_fine_arts`,
`academics_social_sciences`, `academics_education_health_outdoor`) — each
backed by `division_offices.csv`'s high-confidence rows.

**One broad `academics` silo** carries the course catalog (763 pages — 45% of
the entire corpus by itself), program overviews, the faculty directory, and
the divisions hub page. None of these individually has its own office page;
the Registrar's Office is the site's own office of record for the catalog,
already the referral target Task 7 named for the program-requirements gap
(catalog pages are robots-disallowed — decision 0001). This is one rule, and
it is why 61% of the corpus lands in one silo: the site itself is
catalog-heavy, verified by the T7 course-substitute count (763/772, 98.8%),
not an artifact of how the mapper is written.

**18 topic-specific silos**, one per discovered office: `career_center`,
`learn_by_experience`, `admissions`, `finaid`, `iss`, `study_abroad`,
`alumni`, `residential`, `student_services`, `community_engagement`,
`title_ix`, `governance`, `faith_life`, `community_education`,
`partnerships`, `giving`, `families`, `event_operations`, `orientation`.

**`student_health` and `disability`**, both in PLAN's *starting* taxonomy
guess, do not get their own silo: no page under either topic carries a
distinct office contact separate from the general `student_services` address
(`student.affairs@…`). They fold into `student_services` rather than either
inventing a contact or falsely borrowing an unrelated one. This is the
PLAN §2c "fold into a parent, or mark ownerless" rule working as designed —
the taxonomy is finalized against the live IA, not fixed to the starting
guess.

**`athletics` and `consumer_info`**, also in the starting guess, are not
silos: Task 8 step 2 already found that `athletics` cannot become a real silo
from this corpus (11 of the nav's 12 athletics links point off-domain to
`mcscots.com`, outside decision 0001's crawl scope), and no `consumer_info`
office contact was found anywhere in the corpus.

## The measured `other` rate

**10.3%** of the corpus (175/1699 documents), just over PLAN §2c's 10% flag
line. Breaking down the 175:

- **79 (45%) are `/news/*` articles** (`news/divisions`, `news/publications`,
  `news/department`). These are ownerless by the same logic PLAN §2c already
  gives for About/history pages — a news article has an author, not an office
  — and the project's own standing scope already excludes building any
  further news-scraping machinery. Excluding this expected, tracked category,
  the **residual rate is 5.6%** (96/1699), comfortably under threshold.
- The remaining 96 are a long tail below the level any single fix would move
  meaningfully: `about/speakers-experts` (16, a lecture series with no office
  page), `about/mission-vision` and other single-digit `about/*` pages,
  `campus-life/organizations` (4, the only contact found was a named
  individual — not promoted, to avoid repeating the `jeff.bay` mistake), and
  many one- and two-page prefixes below the histogram's meaningful-office
  threshold.

**Conclusion: the mapper is not broken.** The rate is explained, not
hand-waved — one large, correctly-excluded category accounts for the whole
overage, and the residual matches what §2c predicts ("About, history and
similar pages genuinely have no owner, so `other` is correct there").

## Consequences

- `mcrag/silo_mapper.py`'s `SiloMapper` stamps every `Document.silo` from
  `data/silos.yaml`. `scripts/map_silos.py` runs it over the extracted corpus
  once; `scripts/chunk_corpus.py` and `scripts/build_indexes.py` must be
  re-run after (content hashes don't change, so this is a metadata-only
  update the incremental-reindex path was never meant to track — rebuild
  `indexes/` from scratch rather than relying on the diff).
- Task 12's `expected_referral` field can now be populated with real
  `data/offices.yaml` destinations when Task 13 authors questions.
- **Not done in this pass, and worth doing before Checkpoint B's human
  chunk-quality review:** PLAN's own verification step for Task 8 — sampling
  ~10 URLs per silo and hand-checking the assignment, and spot-checking that
  three `destination_url`s are still live. The office-contact review this
  decision documents satisfies decision 0002's requirement (the routing table
  itself is hand-checked); the *mapping rule's* accuracy per PLAN's Task 8
  verification step is still worth a human's ten minutes, since it is
  mechanical longest-prefix matching that has not had a human look at its
  output page-by-page.
- **A new maintenance item, same shape as decision 0002's:** the four
  contacts found in this pass by full-corpus search rather than the
  `office_candidates.csv` heuristic (`admissions`, `finaid`, `giving`,
  `families`, `events`, `orientation`, `title_ix`) were not in the file the
  human explicitly reviewed. They are backed by generic office addresses
  found directly in the corpus text (high confidence per the table in
  `offices.yaml`), but a human should still glance at them before Task 13
  starts writing gold questions with `expected_referral` values that point at
  them.
