"""Shared chunk-building helper for retrieval-leg tests."""

from __future__ import annotations

from datetime import datetime, timezone

from mcrag.types import Chunk


def make_chunk(chunk_id: str, text: str, source_url: str = "https://example.edu/a/") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source_url=source_url,
        title="Title",
        text=text,
        heading_path=(),
        breadcrumb=(),
        silo=(),
        content_hash="h",
        crawled_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
        token_count=len(text.split()),
    )
