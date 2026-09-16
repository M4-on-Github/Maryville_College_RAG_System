"""Reconciles gold refs against a candidate index whose chunking differs.

The 300 gold questions' `gold` refs are `chunk_id` strings into ONE fixed
chunk set (`corpus/chunks.jsonl`, `ParagraphChunker`). Any candidate index
built with a *different* chunker -- the Phase 3a naive baseline's
`FixedSizeChunker`, and every future Phase 4 chunk-size sweep -- produces
different boundaries and therefore different `chunk_id`s for what is
substantially the same underlying text. Exact-`chunk_id` matching
(`retrieval_metrics.py`) would then score every such config at a flat zero
regardless of retrieval quality: not a finding, a bug.

This module does not change what "a hit" means -- a hit is still exact-id
membership, checked by the same metric functions. It relabels a retrieved id
to the gold id it demonstrably covers *before* those functions ever see it,
so a chunker swap is measured on retrieval quality, not chunk-boundary luck.
"""

from __future__ import annotations

from collections.abc import Iterable

from mcrag.types import Chunk

DEFAULT_OVERLAP_THRESHOLD = 0.5


def _normalize(text: str) -> str:
    return " ".join(text.split())


def chunks_overlap(text_a: str, text_b: str, threshold: float = DEFAULT_OVERLAP_THRESHOLD) -> bool:
    """True if the two chunk texts substantially cover the same passage.

    Fast path: one fully contains the other (the common case when a wider
    fixed-size window swallows a whole narrower paragraph-chunk). Fallback:
    word-set overlap ratio, relative to the *shorter* chunk -- a short gold
    chunk mostly contained in a longer retrieved window should count as
    found even though the retrieved window carries extra unrelated text.

    A gold answer that straddles a naive chunker's boundary and lands in
    neither adjacent window legitimately fails this check -- that is the
    naive chunker's real cost, not something to paper over.
    """
    a, b = _normalize(text_a), _normalize(text_b)
    if not a or not b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if shorter in longer:
        return True
    a_words, b_words = set(a.split()), set(b.split())
    if not a_words or not b_words:
        return False
    overlap = len(a_words & b_words) / min(len(a_words), len(b_words))
    return overlap >= threshold


def canonicalize_retrieved(
    retrieved_ids: Iterable[str],
    retrieved_lookup: dict[str, Chunk],
    gold_ids: Iterable[str],
    gold_lookup: dict[str, Chunk],
    threshold: float = DEFAULT_OVERLAP_THRESHOLD,
) -> list[str]:
    """Relabel each retrieved id to the gold id it content-matches, if any.

    An id that is already an exact gold-id match, or that matches no gold
    chunk at all, passes through unchanged -- this is a pure extension of
    exact matching, not a replacement for it, so a retriever run against the
    SAME chunking the gold set was authored against behaves identically to
    calling the metric functions directly.

    Each gold id is claimed at most once, by its best (highest) rank. Two
    overlapping fixed-size windows commonly both cover one gold paragraph --
    without this, both would relabel to the same gold id and the metric
    functions (which count each `retrieved` position independently) would
    score that single passage as found *twice*, at two ranks; `ndcg_at_k`
    would then sum DCG contributions past what `idcg` normalizes for and
    report a score above 1.0. A later duplicate is left as its original id
    (unmatched) rather than reclaimed by a different gold id, since it is the
    same physical passage the first occurrence already credited, not a
    second, independent hit on something else.
    """
    gold_id_set = set(gold_ids)
    claimed: set[str] = set()
    canon: list[str] = []
    for rid in retrieved_ids:
        if rid in gold_id_set and rid not in claimed:
            claimed.add(rid)
            canon.append(rid)
            continue
        r_chunk = retrieved_lookup.get(rid) if rid not in gold_id_set else None
        matched: str | None = None
        if r_chunk is not None:
            for gid in gold_id_set - claimed:
                g_chunk = gold_lookup.get(gid)
                if g_chunk is None or g_chunk.source_url != r_chunk.source_url:
                    continue
                if chunks_overlap(r_chunk.text, g_chunk.text, threshold):
                    matched = gid
                    break
        if matched is not None:
            claimed.add(matched)
            canon.append(matched)
        else:
            canon.append(rid)
    return canon
