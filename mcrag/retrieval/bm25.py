"""The BM25 retrieval leg — bag-of-words over chunk text.

`rank_bm25` builds one flat scorer over whatever corpus it's given and has no
incremental-update API, so `upsert`/`delete_by_source_url` mutate the chunk
dict and rebuild the scorer. At ~3k chunks this is still milliseconds; it is
not the seam that needs true incrementality (that's the dense index's
embedding cache, which is the expensive part).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from rank_bm25 import BM25Okapi

from mcrag.interfaces import Indexer, Retriever
from mcrag.types import Chunk, Hit

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25Index(Indexer, Retriever):
    """Okapi BM25 over chunk text, rebuilt on every mutation."""

    name = "bm25"

    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}
        self._bm25: BM25Okapi | None = None
        self._ids: list[str] = []

    def _rebuild(self) -> None:
        self._ids = list(self._chunks)
        corpus = [tokenize(self._chunks[cid].text) for cid in self._ids]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def build(self, chunks: Iterable[Chunk]) -> None:
        self._chunks = {c.chunk_id: c for c in chunks}
        self._rebuild()

    def upsert(self, chunks: Iterable[Chunk]) -> None:
        for c in chunks:
            self._chunks[c.chunk_id] = c
        self._rebuild()

    def delete_by_source_url(self, url: str) -> int:
        to_remove = [cid for cid, c in self._chunks.items() if c.source_url == url]
        for cid in to_remove:
            del self._chunks[cid]
        self._rebuild()
        return len(to_remove)

    def search(self, query: str, k: int) -> list[Hit]:
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(zip(self._ids, scores), key=lambda pair: -pair[1])
        return [
            Hit(chunk_id=chunk_id, score=float(score), leg=self.name, rank=rank)
            for rank, (chunk_id, score) in enumerate(ranked[:k])
            if score > 0
        ]
