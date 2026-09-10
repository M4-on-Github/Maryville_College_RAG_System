"""The real tokenizer path: loaded lazily, counted against the actual ceiling.

Downloads/reads the HuggingFace cache for `bge-base-en-v1.5`. If that model is
not available on this machine, these are the only tests in the suite allowed
to skip -- everything else about the chunker is exercised through
`FakeTokenCounter` precisely so the rest of the suite never needs network or
disk access to a model cache.
"""

from __future__ import annotations

import pytest

from mcrag.chunk.tokenizer import HuggingFaceTokenCounter

pytest.importorskip("transformers")


@pytest.fixture(scope="module")
def counter():
    c = HuggingFaceTokenCounter()
    try:
        c.count("warm the cache")
    except OSError as exc:
        pytest.skip(f"bge-base-en-v1.5 not available locally: {exc}")
    return c


def test_construction_does_no_io():
    """No network or disk read happens until `.count` is actually called."""
    HuggingFaceTokenCounter()  # must not raise even with no cache/network


def test_short_text_counts_a_handful_of_tokens(counter):
    assert 2 < counter.count("hello world") < 10


def test_empty_text_still_carries_special_tokens(counter):
    assert counter.count("") > 0


def test_longer_text_counts_more_tokens_than_shorter_text(counter):
    assert counter.count("word " * 100) > counter.count("word " * 10)
