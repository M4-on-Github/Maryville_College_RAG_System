"""Main-content extraction: RawPage in, Document out, chrome gone.

Every page on this site carries the same several hundred words of navigation,
utility links and footer. Left in, that boilerplate is the single most common
substring in the corpus, so it dominates BM25 term statistics and pulls dense
vectors toward a meaningless centroid: every chunk looks a bit like every query.
Removing it is the highest-leverage thing done to the text.

Extraction is also the stage that fails *silently*. A site reskin does not throw
an exception; it returns HTTP 200 and an empty string, and the index quietly
shrinks. So this module treats a short or empty extraction as a reportable
outcome rather than a value to pass along.
"""

from __future__ import annotations

import html as html_module
import json
import re
from datetime import datetime, timezone

import trafilatura
from trafilatura.settings import use_config

from mcrag.interfaces import Extractor
from mcrag.types import Document, RawPage

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_JSONLD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.I | re.S)

# Site-wide suffix on every <title>. Kept out of the document title so two pages
# do not look similar to a retriever purely because they share a school name.
_TITLE_SUFFIX = re.compile(r"\s*[\|\-–—]\s*Maryville College\s*$", re.I)


def _text_of(html_fragment: str) -> str:
    """Tags out, entities decoded, whitespace collapsed.

    Entity decoding matters more than it looks: this CMS writes curly
    apostrophes as ``&#8217;``, so a title left un-decoded reads
    "Aaliya Bowman &#8217;25" in every citation the user sees.
    """
    stripped = _TAGS.sub(" ", html_fragment)
    return re.sub(r"\s+", " ", html_module.unescape(stripped)).strip()


class TrafilaturaExtractor(Extractor):
    """The default extractor.

    ``min_chars`` is a floor, not a filter of thin pages. A real page on this
    site that extracts to under ~200 characters is almost always an extraction
    failure rather than a genuinely two-sentence page, and the two have to be
    told apart because only one of them is a bug.
    """

    def __init__(
        self,
        min_chars: int = 200,
        include_tables: bool = True,
        include_links: bool = False,
        favor_recall: bool = True,
    ) -> None:
        self.min_chars = min_chars
        self.include_tables = include_tables
        self.include_links = include_links
        self.favor_recall = favor_recall
        # Built once and reused: trafilatura's config load is not free, and an
        # extractor is constructed once per run but called thousands of times.
        self._config = use_config()
        self._config.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")

    def extract(self, page: RawPage) -> Document | None:
        text = trafilatura.extract(
            page.html,
            include_comments=False,
            include_tables=self.include_tables,
            include_links=self.include_links,
            favor_recall=self.favor_recall,
            no_fallback=False,
            config=self._config,
        )
        if not text or len(text.strip()) < self.min_chars:
            return None

        return Document(
            url=page.url,
            title=self.title_of(page.html) or page.url,
            text=text.strip(),
            content_hash=page.content_hash,
            fetched_at=page.fetched_at or datetime.now(timezone.utc),
            breadcrumb=self.breadcrumb_of(page.html),
        )

    # ---- metadata --------------------------------------------------------

    @staticmethod
    def title_of(html: str) -> str:
        """The page's single ``<h1>``, else ``<title>`` minus the site suffix.

        A lone ``<h1>`` is what the page calls itself and is the better title.
        *Several* ``<h1>``s means a marketing layout rather than a document, and
        picking the first one gives the homepage the title "Unexpected" -- so in
        that case the ``<title>`` wins, suffix stripped.
        """
        headings = [_text_of(h) for h in _H1.findall(html)]
        headings = [h for h in headings if h]
        if len(headings) == 1:
            return headings[0]
        title = _TITLE.search(html)
        if not title:
            return headings[0] if headings else ""
        cleaned = _TITLE_SUFFIX.sub("", _text_of(title.group(1))).strip()
        return cleaned or (headings[0] if headings else "")

    @staticmethod
    def breadcrumb_of(html: str) -> tuple[str, ...]:
        """The site's stated hierarchy, read from its JSON-LD ``BreadcrumbList``.

        The site publishes no visible breadcrumb markup, but its SEO plugin
        emits one as structured data on nearly every page. That is a better
        source than scraping a nav element: it is the hierarchy the site itself
        asserts, already ordered and labelled, and Task 8 checks the silo
        mapping against it rather than against paths guessed from URLs.
        """
        for block in _JSONLD.findall(html):
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                continue
            nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
            for node in nodes if isinstance(nodes, list) else []:
                if not isinstance(node, dict) or node.get("@type") != "BreadcrumbList":
                    continue
                items = sorted(
                    node.get("itemListElement", []), key=lambda e: e.get("position", 0)
                )
                # Unescaped: the plugin double-encodes, so a label arrives as
                # "Partner &#038; Connect". Task 8 maps silos off these labels,
                # and a silo named after an entity reference is a silo nothing
                # matches.
                crumbs = tuple(
                    html_module.unescape(str(e["name"])).strip() for e in items if e.get("name")
                )
                if crumbs:
                    return crumbs
        return ()
