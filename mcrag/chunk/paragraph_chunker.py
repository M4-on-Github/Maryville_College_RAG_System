"""Document -> Chunk, packed by paragraph, capped by real embedder tokens.

**Why paragraphs, not headings.** Task 9 was written expecting the corpus text
to carry H2/H3 markers. It does not: `TrafilaturaExtractor` calls
`trafilatura.extract` with the default plain-text output, which discards
heading tags entirely, and a measurement across the rehearsal corpus found
that even a markdown-formatted re-extraction surfaces at most one or two real
headings per page -- most of the site's templates use bold text and paragraph
breaks, not semantic headings, for visual structure. Switching the extractor
to markdown output to chase that would touch every committed fixture and the
boilerplate filter's learned template for a signal that is present on a
minority of pages and would inject `**`/`##` characters into the retrieval
text on all of them.

So the chunker respects the finest boundary the corpus actually offers: the
paragraph break the extractor already preserves as `\\n`. When the extractor
is later changed to keep headings, `_paragraphs` is the only method that needs
to learn to also split (and remember) heading lines -- everything downstream
of it is boundary-agnostic.

**Why the hard cap is enforced with the real tokenizer.** `max_tokens` is a
soft packing target; `hard_limit` is `bge-base-en-v1.5`'s actual truncation
point, and the acceptance criterion is that no chunk can silently lose text at
index time. A single paragraph longer than the hard limit -- the Department
Directory, at 32k characters and effectively no internal breaks, is the
known case -- is split on token boundaries as a last resort, because no
higher-level structure exists to split it on instead.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

from mcrag.interfaces import Chunker
from mcrag.types import Chunk, Document

_PARA_BREAK = re.compile(r"\n\s*\n|\n")


class TokenCounter(Protocol):
    """Anything that counts tokens the way the embedder will."""

    def count(self, text: str) -> int: ...


class ParagraphChunker(Chunker):
    """Packs paragraphs up to `max_tokens`, respects a hard token ceiling.

    `max_tokens` and `overlap_ratio` are config, not constants, so the §2c
    chunk-size sweep is a config change: no branch in this class knows it is
    being swept.
    """

    def __init__(
        self,
        token_counter: TokenCounter,
        *,
        max_tokens: int = 400,
        overlap_ratio: float = 0.15,
        hard_limit: int = 512,
        min_tokens: int = 8,
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if not 0.0 <= overlap_ratio < 1.0:
            raise ValueError("overlap_ratio must be in [0, 1)")
        if hard_limit < max_tokens:
            raise ValueError("hard_limit cannot be smaller than max_tokens")
        self._tokens = token_counter
        self.max_tokens = max_tokens
        self.overlap_ratio = overlap_ratio
        self.hard_limit = hard_limit
        self.min_tokens = min_tokens

    def chunk(self, doc: Document) -> list[Chunk]:
        paragraphs = self._paragraphs(doc.text)
        packed = self._pack(paragraphs)

        chunks: list[Chunk] = []
        for index, text in enumerate(packed):
            count = self._tokens.count(text)
            if count > self.hard_limit:
                raise AssertionError(
                    f"{doc.url}: chunk {index} is {count} tokens, "
                    f"over the embedder's {self.hard_limit}-token limit"
                )
            if count < self.min_tokens and len(packed) > 1:
                continue
            chunks.append(
                Chunk(
                    chunk_id=self._chunk_id(doc.url, index),
                    source_url=doc.url,
                    title=doc.title,
                    text=text,
                    heading_path=(doc.title,),
                    breadcrumb=doc.breadcrumb,
                    silo=doc.silo,
                    content_hash=doc.content_hash,
                    crawled_at=doc.fetched_at,
                    token_count=count,
                    catalog_year=doc.catalog_year,
                )
            )
        return chunks

    # ---- boundaries ------------------------------------------------------

    def _paragraphs(self, text: str) -> list[str]:
        parts = [p.strip() for p in _PARA_BREAK.split(text)]
        return [p for p in parts if p]

    def _pack(self, paragraphs: list[str]) -> list[str]:
        """Greedy packing with trailing-paragraph overlap between chunks.

        A paragraph that alone exceeds `hard_limit` is split on whitespace into
        token-sized pieces first -- the only case that reaches that branch is a
        page with no real paragraph structure at all (a long directory listing).
        """
        pieces: list[str] = []
        for para in paragraphs:
            pieces.extend(self._split_oversized(para))
        if not pieces:
            return []

        # Token counts are recomputed on the joined text at each step rather
        # than tracked as a running sum of per-piece counts: a counter's
        # per-call overhead (a chat-template or CLS/SEP cost) is paid once per
        # string, not once per piece, so a sum of individual counts drifts
        # from the real count of the joined text -- and drifting the wrong
        # way here means a chunk that silently exceeds the hard limit.
        chunks: list[str] = []
        current: list[str] = []
        for piece in pieces:
            candidate = [*current, piece]
            if current and self._tokens.count(" ".join(candidate)) > self.max_tokens:
                chunks.append(" ".join(current))
                carried = self._carry_overlap(current)
                candidate = [*carried, piece]
                if self._tokens.count(" ".join(candidate)) > self.max_tokens:
                    # The carried overlap plus this piece alone already blows
                    # the target -- drop the overlap rather than the budget.
                    candidate = [piece]
            current = candidate
        chunks.append(" ".join(current))
        return chunks

    def _carry_overlap(self, pieces: list[str]) -> list[str]:
        """Trailing pieces worth ~`overlap_ratio` of the budget, kept for the next chunk.

        Overlap is whole-piece: a paragraph is never split just to make room
        for a partial overlap. When the trailing paragraph alone is close to
        the chunk budget, carrying it leaves no room for the next piece and
        the caller drops the overlap for that boundary rather than exceed
        `max_tokens`. On real prose, most paragraphs are well under the
        400-token target and this rarely bites; it is a known soft spot on
        pages built from a few very long paragraphs.
        """
        if self.overlap_ratio <= 0:
            return []
        target = self.max_tokens * self.overlap_ratio
        carried: list[str] = []
        for piece in reversed(pieces):
            candidate = [piece, *carried]
            if carried and self._tokens.count(" ".join(candidate)) > target:
                break
            carried = candidate
        return carried

    def _split_oversized(self, paragraph: str) -> list[str]:
        if self._tokens.count(paragraph) <= self.hard_limit:
            return [paragraph]
        words = paragraph.split()
        pieces: list[str] = []
        current: list[str] = []
        for word in words:
            current.append(word)
            if self._tokens.count(" ".join(current)) >= self.max_tokens:
                pieces.append(" ".join(current))
                current = []
        if current:
            pieces.append(" ".join(current))
        return pieces

    @staticmethod
    def _chunk_id(url: str, index: int) -> str:
        # Stable across re-runs of the same doc: incremental reindex (Task 11)
        # diffs by this id, so it must not depend on wall-clock or process state.
        digest = hashlib.sha256(f"{url}#{index}".encode("utf-8")).hexdigest()[:16]
        return f"{digest}-{index}"
