"""Task 25's `GET /health`: reports which frozen index build and corpus
snapshot this process is actually serving -- not just "the process is up,"
which tells an operator nothing about whether a stale index survived a bad
deploy.

`index_build_id` hashes the exact frozen chunk file every retrieval leg is
built from (`mcrag.retrieval.frozen_pipeline.build_indexes` reads
`CHUNKS_PATH`) -- this, not a version number nobody remembers to bump by
hand, is what actually determines what a request is served against.
`corpus_hash` reuses `snapshot_hash` from `indexes/corpus.lock`, the same
hash Task 10's incremental reindex (`mcrag.index_pipeline.write_lock`) uses
to decide whether the corpus changed at all -- one hash, not two competing
ones.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from mcrag.retrieval.frozen_pipeline import CHUNKS_PATH

CORPUS_LOCK_PATH = Path("indexes/corpus.lock")


@dataclass(frozen=True)
class HealthInfo:
    status: str
    index_build_id: str
    corpus_hash: str


def _index_build_id(chunks_path: Path) -> str:
    if not chunks_path.exists():
        return "unknown"
    digest = hashlib.sha256()
    with chunks_path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:16]


def _corpus_hash(lock_path: Path) -> str:
    if not lock_path.exists():
        return "unknown"
    return json.loads(lock_path.read_text(encoding="utf-8")).get("snapshot_hash", "unknown")


_cached: HealthInfo | None = None


def get_health_info(*, chunks_path: Path = CHUNKS_PATH, lock_path: Path = CORPUS_LOCK_PATH) -> HealthInfo:
    """Cached process-wide, like `answer.get_default_pipeline` -- these files
    don't change without a redeploy, so hashing the whole chunk file on
    every `/health` poll would be pure waste. `reset_cache` below exists so
    a test can pass its own paths without the first caller's result
    sticking for the rest of the process."""
    global _cached
    if _cached is None:
        _cached = HealthInfo(
            status="ok",
            index_build_id=_index_build_id(chunks_path),
            corpus_hash=_corpus_hash(lock_path),
        )
    return _cached


def reset_cache() -> None:
    """Test-only."""
    global _cached
    _cached = None
