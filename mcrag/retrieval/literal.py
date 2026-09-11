"""The literal (grep) retrieval leg — PLAN §4c.

BM25 tokenizes, which destroys exactly the strings that identify entities:
`I-20` vs `I 20`, `MATH 1110` split across a bag of words, `$1,500` vs
`1500`. At ~3k chunks a substring/regex scan over the raw text costs
milliseconds, so there is no tokenization to get wrong.

**A trigger, not a blind third leg.** `search` returns `[]` immediately when
the query contains none of the entity patterns below -- running an
unconditional literal scan on the ~80% of queries with no code in them would
just waste a fusion slot on an empty list every time.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from mcrag.interfaces import Indexer, Retriever
from mcrag.types import Chunk, Hit

# PLAN §4c's own patterns, verbatim: course codes, immigration forms, money.
PATTERNS: dict[str, re.Pattern[str]] = {
    "course_code": re.compile(r"\b[A-Z]{3,4}\s?-?\s?\d{3,4}\b"),
    "form": re.compile(r"\b[IF]-\d{1,3}\b"),
    "money": re.compile(r"\$[\d,]+(?:\.\d{2})?"),
}


def detect_entities(query: str) -> list[str]:
    """Every substring in `query` that matches one of PATTERNS, in order found."""
    hits = []
    for pattern in PATTERNS.values():
        hits.extend(m.group(0) for m in pattern.finditer(query))
    return hits


class LiteralIndex(Indexer, Retriever):
    """Exact-substring search over chunk text, triggered by query entities."""

    name = "literal"

    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}

    def build(self, chunks: Iterable[Chunk]) -> None:
        self._chunks = {c.chunk_id: c for c in chunks}

    def upsert(self, chunks: Iterable[Chunk]) -> None:
        for c in chunks:
            self._chunks[c.chunk_id] = c

    def delete_by_source_url(self, url: str) -> int:
        to_remove = [cid for cid, c in self._chunks.items() if c.source_url == url]
        for cid in to_remove:
            del self._chunks[cid]
        return len(to_remove)

    def search(self, query: str, k: int) -> list[Hit]:
        entities = detect_entities(query)
        if not entities:
            return []  # no entity in the query: the trigger doesn't fire

        scored: list[tuple[int, str]] = []
        for chunk_id, chunk in self._chunks.items():
            hit_count = sum(1 for e in entities if e in chunk.text)
            if hit_count:
                scored.append((hit_count, chunk_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))

        return [
            Hit(chunk_id=chunk_id, score=float(count), leg=self.name, rank=rank)
            for rank, (count, chunk_id) in enumerate(scored[:k])
        ]
