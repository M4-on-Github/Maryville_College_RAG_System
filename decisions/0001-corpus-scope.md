# 0001 — Corpus scope, and what the live site actually looks like

**Date:** 2026-09-10 · **Status:** accepted, supersedes the corpus assumptions in `PLAN.md` §1

## Context

`PLAN.md` was written before anything was fetched. It assumed:

- two in-scope WordPress sitemaps, roughly 800–900 pages
- a separate **SmartCatalogIQ** host, with no sitemap, needing a nav-tree crawler (Task 7)
- news as the one large exclusion, at roughly 850 posts

Enumerating `wp-sitemap.xml` on 2026-09-10 found something different.

## What is actually there

**29 sitemaps, 5,514 URLs.** The catalog is not a separate host at all: it is
three WordPress custom post types on `www.maryvillecollege.edu`.

| Sitemap | URLs | Disposition |
|---|---|---|
| `posts-page` | 964 | **in scope** — the core corpus |
| `posts-academic_course` | 772 | **in scope** — full course records, code/title/credits/description |
| `posts-staff` | 344 | **in scope** — the office and contact source for silo discovery |
| `posts-student_study` | 184 | **in scope** — undergraduate research and senior studies |
| `posts-academic_programs` | 77 | **in scope** — programs of study |
| `taxonomies-divisions` | 74 | **in scope** — the site's own division taxonomy |
| `taxonomies-department` | 42 | **in scope** — the site's own department taxonomy |
| `posts-smart_catalog_course` | 851 | **robots-disallowed** |
| `posts-smart_catalog_block` | 157 | **robots-disallowed** |
| `posts-smart_catalog_prog` | 138 | **robots-disallowed** |
| `posts-post` (news) | 845 | **policy-excluded** — stale-date hallucination risk |
| `posts-tribe_events` | 490 | **policy-excluded** — dated events, same risk as news |
| `posts-tribe_venue` | 227 | **policy-excluded** — venue stubs, near-zero text |
| everything else | ~349 | mixed; galleries, products, tags, sessions |

In-scope total is roughly **2,450 URLs**, about three times the planned figure.

## Decisions

**1. There is no SmartCatalogIQ nav-tree crawl. Task 7 changes shape.**
`catalog.maryvillecollege.edu` does not resolve. The catalog lives at
`/academics/catalog/…` as a WordPress post type, and the sitemap already
enumerates it, so no nav-tree discovery is needed. What Task 7 becomes is a
robots problem, not a crawling problem — see below.

**2. The catalog's own pages are robots-disallowed, and we honor that.**
All three `smart_catalog_*` types match a `Disallow` rule. That is 1,146 URLs,
and they are the ones carrying degree requirements. This is the single largest
gap in the corpus and it must be reported as one.

**3. The gap is mostly, but not wholly, covered.** `/academics/course/…` (772
URLs) is allowed and carries the same course data the disallowed
`smart_catalog_course` pages carry. Course-level questions are therefore
answerable. **Program-level degree requirements are not**: `smart_catalog_prog`
is the requirements view and it is disallowed, with `academic_programs` (77
URLs) giving program overviews rather than requirement lists. Expect
"what courses do I need for a biology major" to be a refusal, and say so in the
limitations rather than discovering it during evaluation.

**4. Events and venues join news as policy exclusions.** Same failure mode as
news: dated content that a model will happily present as current. 717 URLs.

**5. The site publishes its own taxonomy and we use it.** `taxonomies-divisions`
(74) and `taxonomies-department` (42) are the institution's own answer to "what
are the silos," which beats a path-prefix histogram as a starting point. This
strengthens Task 8 step 1 rather than replacing it: the histogram still says
which of those divisions have enough pages to matter.

**6. Sitemap URLs redirect and the manifest records both.** `/faculty/dcrain/`
resolves to `/academics/faculty/dcrain/`. The manifest stores the requested URL
and the final URL, and deduplicates on the final one. Without that, the same
page enters the corpus twice under two names.

## Consequences

- `PLAN.md` §1 corpus-size figures are wrong and are superseded here.
- Task 4's verification criterion ("800–900 pages") is replaced by
  reconciliation against the sitemap total, which is the check that actually
  means something.
- Task 7 becomes "catalog coverage assessment": establish what the robots
  exclusion costs, confirm the course-level substitute, and write the gap up.
- A new risk enters the register: the highest-value question type for a
  prospective student, degree requirements, sits behind the robots exclusion.
