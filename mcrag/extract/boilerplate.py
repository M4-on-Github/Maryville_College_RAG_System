"""Corpus-level chrome removal, after per-page extraction.

Per-page extraction gets most of the template off, but not all of it. On pages
with little main content -- an A-to-Z index, the 404 page -- there is nothing
for the extractor to prefer, so it returns the footer and calls it the article.
About one page in five here came back that way.

Left alone, those pages are worse than useless: they are near-identical to each
other, so a query that matches the footer retrieves a dozen of them at once and
crowds out the page that actually answers it.

A single page cannot tell its own boilerplate from its content. The corpus can:
a line that appears on hundreds of unrelated pages is the template, whatever it
says. So this runs as a second pass, once the whole corpus is extracted.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from mcrag.types import Document


@dataclass(frozen=True, slots=True)
class BoilerplateReport:
    """What the filter removed, so the decision can be audited.

    ``dropped`` matters most: a document that was *entirely* boilerplate is an
    extraction failure, and the manifest has to hear about it.
    """

    lines: tuple[str, ...]
    chars_removed: int
    documents_changed: int
    dropped: tuple[str, ...]


class BoilerplateFilter:
    """Removes lines that recur across unrelated pages.

    ``min_share`` is a fraction of the corpus and ``min_pages`` an absolute
    floor. Both are needed: on a 50-page rehearsal corpus a share alone is noisy,
    and on a 2,400-page corpus a count alone is meaningless.

    ``max_line_words`` keeps the filter off real prose. Template lines are short
    -- labels, link text, a copyright line. A forty-word sentence appearing on
    many pages is boilerplate of a different kind (a shared programme blurb),
    and dropping it would take real answers out of the corpus.
    """

    def __init__(
        self,
        min_share: float = 0.15,
        min_pages: int = 5,
        max_line_words: int = 25,
        min_chars: int = 200,
    ) -> None:
        self.min_share = min_share
        self.min_pages = min_pages
        self.max_line_words = max_line_words
        self.min_chars = min_chars

    def learn(self, documents: list[Document]) -> set[str]:
        """The set of lines judged to be template, from the corpus itself."""
        if not documents:
            return set()
        counts: Counter[str] = Counter()
        for doc in documents:
            # Per-document set, so a line repeated within one page counts once
            # and a long list page cannot vote its own content into the template.
            for line in {line.strip() for line in doc.text.splitlines() if line.strip()}:
                counts[line] += 1

        threshold = max(self.min_pages, int(len(documents) * self.min_share))
        return {
            line
            for line, count in counts.items()
            if count >= threshold and len(line.split()) <= self.max_line_words
        }

    def apply(
        self, documents: list[Document], lines: set[str] | None = None
    ) -> tuple[list[Document], BoilerplateReport]:
        """Strip the template lines; drop what is left of pure-chrome pages."""
        template = self.learn(documents) if lines is None else lines
        kept: list[Document] = []
        dropped: list[str] = []
        removed_chars = 0
        changed = 0

        for doc in documents:
            body = [line for line in doc.text.splitlines() if line.strip() not in template]
            text = "\n".join(body).strip()
            if len(text) < len(doc.text):
                changed += 1
                removed_chars += len(doc.text) - len(text)
            if len(text) < self.min_chars:
                # Nothing survived but the template: this page had no content of
                # its own, and saying so is more useful than indexing a footer.
                dropped.append(doc.url)
                continue
            kept.append(replace(doc, text=text) if text != doc.text else doc)

        return kept, BoilerplateReport(
            lines=tuple(sorted(template)),
            chars_removed=removed_chars,
            documents_changed=changed,
            dropped=tuple(dropped),
        )
