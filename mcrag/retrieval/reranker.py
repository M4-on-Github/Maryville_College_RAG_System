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

            model = CrossEncoder(self.model_name)
            # score_pairs promises raw logits. A sigmoid here would compress the
            # top of the scale, exactly where margins between strong candidates live.
            if type(getattr(model, "activation_fn", None)).__name__ != "Identity":
                raise ValueError(f"{self.model_name}: expected raw logits (Identity activation)")
            self._model = model
        return self._model

    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Raw relevance logits for (query, passage) pairs, without reordering
        anything: the cross-encoder as a confidence signal (Task 21's abstention
        gate) rather than a ranker."""
        if not pairs:
            return []
        return [float(s) for s in self._load().predict(pairs)]

    def count_truncated(self, pairs: list[tuple[str, str]]) -> int:
        """Pairs longer than the model reads. Anything past the limit is dropped
        silently, so this is counted rather than assumed away."""
        tokenizer = getattr(self._load(), "tokenizer", None)
        limit = getattr(tokenizer, "model_max_length", None)
        if tokenizer is None or not limit:
            return 0
        return sum(1 for q, p in pairs if len(tokenizer(q, p)["input_ids"]) > limit)

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
