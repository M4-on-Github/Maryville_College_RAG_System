"""Document -> Chunk, naive fixed-token windows. The Phase 3a control condition.

PLAN's naive baseline is deliberately dumb: "fixed 512-tok chunks... no
literal leg, no rerank, no rewriting" is the config a lazy first pass would
ship, and `ParagraphChunker` (Task 9) is the thing later ablations measure
against it. No paragraph awareness, no overlap, no packing heuristics --
just cut the text into `chunk_tokens`-sized windows, word by word, checked
against the real embedder tokenizer so no chunk silently exceeds the hard
limit either.
"""

from __future__ import annotations

import hashlib

from mcrag.chunk.paragraph_chunker import TokenCounter
from mcrag.interfaces import Chunker
from mcrag.types import Chunk, Document


class FixedSizeChunker(Chunker):
    """Splits `doc.text` into non-overlapping ~`chunk_tokens`-token windows."""

    def __init__(self, token_counter: TokenCounter, *, chunk_tokens: int = 512) -> None:
        if chunk_tokens <= 0:
            raise ValueError("chunk_tokens must be positive")
        self._tokens = token_counter
        self.chunk_tokens = chunk_tokens

    def chunk(self, doc: Document) -> list[Chunk]:
        words = doc.text.split()
        if not words:
            return []

        windows = self._pack(words)
        chunks: list[Chunk] = []
        for index, text in enumerate(windows):
            count = self._tokens.count(text)
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

    def _pack(self, words: list[str]) -> list[str]:
        windows: list[str] = []
        current: list[str] = []
        for word in words:
            candidate = [*current, word]
            if current and self._tokens.count(" ".join(candidate)) > self.chunk_tokens:
                windows.append(" ".join(current))
                current = [word]
            else:
                current = candidate
        if current:
            windows.append(" ".join(current))
        return windows

    @staticmethod
    def _chunk_id(url: str, index: int) -> str:
        # Same scheme as ParagraphChunker's, and deliberately distinct in value
        # from it (the "#" + index digest differs only because this chunker's
        # windows differ) -- the two chunkers' outputs must never collide in
        # one index, since Task 15 builds a wholly separate baseline index.
        digest = hashlib.sha256(f"fixed:{url}#{index}".encode("utf-8")).hexdigest()[:16]
        return f"{digest}-{index}"
