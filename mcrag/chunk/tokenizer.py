"""Counting tokens the way the embedder will, not the way the LLM will.

`mcrag.generate.tokens.TokenEstimator` is deliberately a cheap chars-per-token
guess, biased to over-count, because it exists to make a pre-flight decision
before a metered call. The chunker's 512-token ceiling is a different problem:
it is a hard limit enforced by a specific tokenizer (`bge-base-en-v1.5`'s,
which is BERT-style WordPiece), and "close enough" is not good enough -- an
estimate that is off by ten tokens either truncates silently at index time or
throws away room the chunker could have used.

Loading the real tokenizer is I/O (a HuggingFace cache read, occasionally a
download), so it happens lazily on first use rather than in `__init__` --
same discipline as `OllamaCloudGenerator.resolve_api_key`. A config can be
built and the constructor can run in a test that never counts a single token.
"""

from __future__ import annotations

from functools import cached_property

DEFAULT_MODEL = "BAAI/bge-base-en-v1.5"


class HuggingFaceTokenCounter:
    """Exact token counts from a HuggingFace tokenizer, loaded on first call."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self._model = model

    @cached_property
    def _tokenizer(self):
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(self._model)

    def count(self, text: str) -> int:
        # add_special_tokens=True: the CLS/SEP pair the embedder actually pays
        # for is exactly what the 512 ceiling is measured against.
        return len(self._tokenizer(text, add_special_tokens=True)["input_ids"])


class FakeTokenCounter:
    """A deterministic stand-in for tests: N words -> N+2 tokens.

    The +2 mirrors the CLS/SEP overhead so a test asserting the hard-limit
    boundary behaves the same shape as the real tokenizer, without downloading
    one.
    """

    def count(self, text: str) -> int:
        return len(text.split()) + 2 if text else 2
