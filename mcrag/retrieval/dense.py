"""The dense retrieval leg — LanceDB over `Embedder` vectors, embedding-cached.

`upsert`/`delete_by_source_url` operate on the LanceDB table directly rather
than round-tripping through `build`, so an incremental reindex (T10) never
re-embeds or re-writes chunks that didn't change.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import lancedb

from mcrag.interfaces import Embedder, Indexer, Retriever
from mcrag.retrieval.embedding_cache import EmbeddingCache, embed_with_cache
from mcrag.types import Chunk, Hit

_TABLE = "chunks"


class DenseIndex(Indexer, Retriever):
    """LanceDB dense index. Rows are joinable back to metadata by `chunk_id`."""

    name = "dense"

    def __init__(
        self,
        db_path: Path,
        embedder: Embedder,
        cache: EmbeddingCache,
        model_name: str,
    ) -> None:
        self._db = lancedb.connect(str(db_path))
        self._embedder = embedder
        self._cache = cache
        self._model_name = model_name
        self._table = None
        if _TABLE in self._db.table_names():
            self._table = self._db.open_table(_TABLE)

    def _rows_for(self, chunks: list[Chunk]) -> list[dict]:
        vectors = embed_with_cache(
            self._embedder, self._model_name, [c.text for c in chunks], self._cache
        )
        return [
            {
                "chunk_id": c.chunk_id,
                "vector": vector,
                "source_url": c.source_url,
                "title": c.title,
                "text": c.text,
            }
            for c, vector in zip(chunks, vectors)
        ]

    def build(self, chunks: Iterable[Chunk]) -> None:
        rows = self._rows_for(list(chunks))
        self._table = self._db.create_table(_TABLE, data=rows, mode="overwrite")

    def upsert(self, chunks: Iterable[Chunk]) -> None:
        chunks = list(chunks)
        if not chunks:
            return
        if self._table is None:
            self.build(chunks)
            return
        ids = [c.chunk_id for c in chunks]
        id_list = ", ".join(f"'{cid}'" for cid in ids)
        self._table.delete(f"chunk_id IN ({id_list})")
        self._table.add(self._rows_for(chunks))

    def delete_by_source_url(self, url: str) -> int:
        if self._table is None:
            return 0
        before = self._table.count_rows()
        escaped = url.replace("'", "''")
        self._table.delete(f"source_url = '{escaped}'")
        return before - self._table.count_rows()

    def search(self, query: str, k: int) -> list[Hit]:
        if self._table is None:
            return []
        vector = self._embedder.embed([query])[0]
        rows = self._table.search(vector).limit(k).to_list()
        return [
            Hit(chunk_id=row["chunk_id"], score=1.0 - row["_distance"], leg=self.name, rank=rank)
            for rank, row in enumerate(rows)
        ]
