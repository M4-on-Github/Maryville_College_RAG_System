"""The reranker query-time factor (PLAN §Phase 4, ablation #4): on or off.

`IdentityReranker` is the 'off' arm per `mcrag/interfaces.py`'s own
convention. `CrossEncoderReranker` is the 'on' arm: a local, free,
quota-free cross-encoder rescoring of the fused candidate list -- it costs
wall-clock, not budget, so it belongs in the free half of Phase 4 (T18)
alongside fusion and silo boost.

Reranking needs `hit.chunk` populated (chunk text to score against the
query); a `Hit` with no `chunk` is left in place rather than dropped, so a
caller that forgot to attach chunks gets a silent no-op, not a crash mid-sweep.
"""

from __future__ import annotations

from dataclasses import replace

from mcrag.interfaces import Reranker
from mcrag.types import Hit

DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class IdentityReranker(Reranker):
    """The 'off' arm: truncate to k, change nothing else."""

    def rerank(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        return list(hits[:k])


class CrossEncoderReranker(Reranker):
    """Rescores candidates with a local `sentence_transformers.CrossEncoder`.

    The model loads lazily, on first `rerank` call, not at construction --
    so building a config matrix that *includes* this arm never pays the load
    cost for arms that don't reach it, and importing this module never
    triggers a model download.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        scorable = [h for h in hits if h.chunk is not None]
        unscorable = [h for h in hits if h.chunk is None]
        if not scorable:
            return list(hits[:k])

        model = self._load()
        scores = model.predict([(query, h.chunk.text) for h in scorable])
        rescored = [h.with_score(float(s), leg=h.leg) for h, s in zip(scorable, scores)]
        rescored.sort(key=lambda h: -h.score)

        ordered = rescored + unscorable  # unscorable hits keep their place at the tail
        return [replace(h, rank=rank) for rank, h in enumerate(ordered)][:k]
