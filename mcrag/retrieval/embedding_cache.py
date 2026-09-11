"""Embeddings cached on `(model_name, chunk_text_hash)` — T11's acceptance
criterion that a rebuild over unchanged chunks re-embeds nothing.

Embedding is the expensive step (a model forward pass per chunk); everything
else in the dense index (writing to LanceDB) is cheap. The cache is keyed on
content, not `chunk_id`, so a chunk that moves (re-chunked boundary, but same
text) still hits the cache, and a chunk whose text actually changed always
misses it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mcrag.interfaces import Embedder


def _key(model_name: str, text: str) -> str:
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{model_name}:{text_hash}"


class EmbeddingCache:
    """A flat JSONL cache file: one `{"key": ..., "vector": [...]}` per line."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._store: dict[str, list[float]] = {}
        if path.exists():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        row = json.loads(line)
                        self._store[row["key"]] = row["vector"]

    def get_many(self, model_name: str, texts: list[str]) -> list[list[float] | None]:
        return [self._store.get(_key(model_name, t)) for t in texts]

    def put_many(self, model_name: str, texts: list[str], vectors: list[list[float]]) -> None:
        new_rows = []
        for text, vector in zip(texts, vectors):
            key = _key(model_name, text)
            if key not in self._store:
                self._store[key] = vector
                new_rows.append({"key": key, "vector": vector})
        if not new_rows:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            for row in new_rows:
                f.write(json.dumps(row) + "\n")

    def __len__(self) -> int:
        return len(self._store)


def embed_with_cache(embedder: Embedder, model_name: str, texts: list[str], cache: EmbeddingCache) -> list[list[float]]:
    """Embed `texts`, computing only the ones the cache doesn't already have."""
    cached = cache.get_many(model_name, texts)
    missing_idx = [i for i, v in enumerate(cached) if v is None]
    if missing_idx:
        fresh = embedder.embed([texts[i] for i in missing_idx])
        cache.put_many(model_name, [texts[i] for i in missing_idx], fresh)
        for i, vector in zip(missing_idx, fresh):
            cached[i] = vector
    return cached  # type: ignore[return-value]
