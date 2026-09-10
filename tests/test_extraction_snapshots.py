"""Extraction regression tests against pinned real pages.

Seventeen pages spanning every silo are committed as raw HTML plus the text the
extractor produced from them. Re-extraction has to reproduce that text exactly.

The point is to notice a change we did not intend. A trafilatura upgrade or a
site reskin can quietly halve the text on one silo while every fetch still
returns 200 and every other test still passes; nothing but a pinned comparison
catches that.

If a fixture fails, read the diff before regenerating it. Regenerating to make
the suite green converts a regression test into a very slow way of confirming a
file matches itself.
"""

from __future__ import annotations

import gzip
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mcrag.extract.boilerplate import BoilerplateFilter
from mcrag.extract.trafilatura_extractor import TrafilaturaExtractor
from mcrag.types import RawPage

FIXTURES = Path(__file__).parent / "fixtures" / "extraction"
CASES = sorted(p.stem.replace(".html", "") for p in FIXTURES.glob("*.html.gz"))

# Nav and footer text present on every page. If any of this survives extraction,
# the chrome removal has stopped working.
CHROME = [
    "Consumer Info",
    "Title IX",
    "All information Maryville College",
    "Apply Now",
    "Request Info",
]

# The subset that legitimately survives per-page extraction on thin pages.
FOOTER_LEAKS = {"Consumer Info", "Title IX", "All information Maryville College"}


def load(name: str) -> tuple[str, str]:
    html = gzip.decompress((FIXTURES / f"{name}.html.gz").read_bytes()).decode("utf-8")
    expected = (FIXTURES / f"{name}.expected.txt").read_text(encoding="utf-8").rstrip("\n")
    return html, expected


def page(name: str, html: str) -> RawPage:
    return RawPage(
        url=f"https://www.maryvillecollege.edu/{name}/",
        http_status=200,
        content_hash="",
        fetched_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
        html=html,
    )


def test_fixtures_are_present():
    """A deleted fixture directory must fail loudly, not silently pass."""
    assert len(CASES) >= 15, f"expected the pinned silo fixtures, found {CASES}"


@pytest.mark.parametrize("name", CASES)
def test_extraction_matches_pinned_snapshot(name):
    html, expected = load(name)
    doc = TrafilaturaExtractor().extract(page(name, html))
    assert doc is not None, f"{name} now extracts to nothing"
    assert doc.text == expected


@pytest.mark.parametrize("name", CASES)
def test_no_chrome_survives_extraction(name):
    html, _ = load(name)
    doc = TrafilaturaExtractor().extract(page(name, html))
    leaked = [c for c in CHROME if c in doc.text]
    # The footer's legal links do leak on thin pages, and removing those is the
    # corpus-level filter's job rather than this one's. The header call-to-action
    # buttons are pure navigation and must never survive per-page extraction.
    assert set(leaked) <= FOOTER_LEAKS, f"{name} leaked nav chrome: {leaked}"


@pytest.mark.parametrize("name", CASES)
def test_titles_are_clean(name):
    html, _ = load(name)
    title = TrafilaturaExtractor.title_of(html)
    assert title
    assert "&#" not in title and "&amp;" not in title, "HTML entities left undecoded"
    assert not title.endswith("- Maryville College"), "site suffix left on the title"


def test_breadcrumbs_are_read_from_structured_data():
    html, _ = load("academics__programs-of-study__accounting")
    crumbs = TrafilaturaExtractor.breadcrumb_of(html)
    assert crumbs, "the JSON-LD BreadcrumbList is no longer being parsed"
    # The site's own crumb, not one we invented from the URL path: it starts at
    # "Programs of Study" and calls the leaf "Accounting Minor", neither of
    # which the path /academics/programs-of-study/accounting/ would have given.
    assert crumbs[0] == "Programs of Study"
    assert crumbs[-1] == "Accounting Minor"


def test_top_level_page_has_no_breadcrumb():
    html, _ = load("about")
    assert TrafilaturaExtractor.breadcrumb_of(html) == ()


# ---- the corpus-level filter -------------------------------------------


def _corpus():
    extractor = TrafilaturaExtractor()
    docs = []
    for name in CASES:
        html, _ = load(name)
        doc = extractor.extract(page(name, html))
        if doc:
            docs.append(doc)
    return docs


def test_filter_learns_the_site_footer():
    lines = BoilerplateFilter(min_pages=2, min_share=0.1).learn(_corpus())
    assert any("All information Maryville College" in line for line in lines)
    assert any("Title IX" in line for line in lines)


def test_filter_leaves_real_prose_alone():
    docs = _corpus()
    kept, report = BoilerplateFilter(min_pages=2, min_share=0.1).apply(docs)
    about = next(d for d in kept if d.url.endswith("/about/"))
    assert "nationally-ranked institution" in about.text
    assert report.chars_removed > 0


def test_filter_will_not_eat_long_sentences():
    """A long line shared by several pages is content, not template."""
    from dataclasses import replace

    sentence = " ".join(f"word{i}" for i in range(40))
    base = _corpus()[0]
    shared = [
        replace(base, url=f"https://www.maryvillecollege.edu/p{i}/", text=sentence)
        for i in range(5)
    ]
    filt = BoilerplateFilter(min_pages=2, min_share=0.1, max_line_words=25)
    assert sentence not in filt.learn(shared)


def test_pure_chrome_page_is_dropped_not_indexed():
    """A page whose whole extraction is the footer must not become a document."""
    from dataclasses import replace

    docs = _corpus()
    filt = BoilerplateFilter(min_pages=2, min_share=0.1)
    template = filt.learn(docs)
    assert template, "no template lines learned; the rest of this test is vacuous"

    chrome_only = replace(
        docs[0],
        url="https://www.maryvillecollege.edu/chrome/",
        text="\n".join(sorted(template)),
    )
    kept, report = filt.apply([*docs, chrome_only])
    assert "https://www.maryvillecollege.edu/chrome/" in report.dropped
    assert all(d.url != "https://www.maryvillecollege.edu/chrome/" for d in kept)
