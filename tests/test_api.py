"""Task 25 verification: the FastAPI shell over `answer()`, exercised with
`fastapi.testclient.TestClient` (no real server process, no real network) --
the same duck-typed fakes `tests/test_service.py` already defines
(`FakeGenerator`, `FakeLeg`, `FakeEmbedder`, `_chunk`, `_pipeline`), reused
here rather than redefined, so the two test files can't quietly drift into
different doubles for the same interfaces.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from mcrag.service import health as health_module
from mcrag.service.api import _stream, create_app
from mcrag.service.config import Settings
from tests.test_service import FakeGenerator, _chunk, _pipeline

TOKEN = "test-token-123"


def _app(pipeline=None, *, token: str | None = TOKEN, cors_origins: list[str] | None = None):
    settings = Settings(api_token=token, cors_origins=cors_origins or [])
    return create_app(settings=settings, pipeline=pipeline or _pipeline(FakeGenerator()))


# ---- auth --------------------------------------------------------------


def test_ask_without_a_token_is_rejected():
    client = TestClient(_app())
    resp = client.post("/ask", json={"question": "What is the deposit?"})
    assert resp.status_code == 401


def test_ask_with_the_wrong_token_is_rejected():
    client = TestClient(_app())
    resp = client.post(
        "/ask", json={"question": "What is the deposit?"}, headers={"x-api-key": "not-it"}
    )
    assert resp.status_code == 401


def test_no_configured_token_rejects_every_request():
    """Fails closed: an unconfigured deployment serves nobody, not everybody."""
    client = TestClient(_app(token=None))
    resp = client.post(
        "/ask", json={"question": "What is the deposit?"}, headers={"x-api-key": "anything"}
    )
    assert resp.status_code == 401


def test_ask_with_the_right_token_streams_events():
    client = TestClient(_app())
    with client.stream(
        "POST", "/ask", json={"question": "What is the deposit?"}, headers={"x-api-key": TOKEN}
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "event: sources" in body
    assert "event: token" in body
    assert "event: citation" in body
    assert "event: done" in body
    # contract order preserved end to end through the SSE transport
    assert body.index("event: sources") < body.index("event: token") < body.index("event: done")


def test_a_model_refusal_streams_as_a_refusal_event_not_tokens():
    generator = FakeGenerator(default="I cannot find any information about that in the passages.")
    client = TestClient(_app(pipeline=_pipeline(generator)))
    with client.stream(
        "POST", "/ask", json={"question": "What is the deposit?"}, headers={"x-api-key": TOKEN}
    ) as resp:
        body = "".join(resp.iter_text())
    assert "event: refusal" in body
    assert "event: token" not in body


# ---- CORS ----------------------------------------------------------------


def test_cors_allows_a_configured_origin():
    client = TestClient(_app(cors_origins=["https://example.edu"]))
    resp = client.options(
        "/ask",
        headers={
            "origin": "https://example.edu",
            "access-control-request-method": "POST",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "https://example.edu"


def test_cors_rejects_an_unlisted_origin():
    client = TestClient(_app(cors_origins=["https://example.edu"]))
    resp = client.options(
        "/ask",
        headers={
            "origin": "https://not-allowed.example",
            "access-control-request-method": "POST",
        },
    )
    assert "access-control-allow-origin" not in resp.headers


# ---- health ----------------------------------------------------------------


def test_health_reports_index_build_id_and_corpus_hash(tmp_path):
    health_module.reset_cache()
    chunks = tmp_path / "chunks.jsonl"
    chunks.write_text('{"a": 1}\n', encoding="utf-8")
    lock = tmp_path / "corpus.lock"
    lock.write_text('{"snapshot_hash": "deadbeef"}', encoding="utf-8")
    try:
        info = health_module.get_health_info(chunks_path=chunks, lock_path=lock)
        assert info.status == "ok"
        assert info.corpus_hash == "deadbeef"
        assert len(info.index_build_id) == 16
    finally:
        health_module.reset_cache()

    client = TestClient(_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert "index_build_id" in payload and "corpus_hash" in payload and payload["status"] == "ok"


def test_health_requires_no_token():
    client = TestClient(_app())
    resp = client.get("/health")
    assert resp.status_code == 200


# ---- disconnect cancels the upstream generation call -----------------------


class _FakeRequest:
    """`_stream` only ever calls `await request.is_disconnected()` -- a real
    `starlette.Request`'s version of that depends on ASGI-transport-level
    disconnect signaling that `TestClient`'s in-memory transport does not
    reproduce deterministically (it can race ahead of a client that stops
    reading). Driving `_stream` directly against this fake pins the actual
    cancellation logic instead of a timing-sensitive integration path."""

    def __init__(self, disconnect_after: int) -> None:
        self._calls = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._calls += 1
        return self._calls > self._disconnect_after


def test_disconnect_before_the_second_pull_never_starts_the_model_call():
    """The realistic case this criterion protects against: a client leaves
    while `sources` (the first pull) would otherwise be the signal to start
    the model call (triggered by the second pull). Disconnecting between the
    two must mean `FakeGenerator.generate` is never invoked at all."""
    generator = FakeGenerator()
    pipeline = _pipeline(generator)
    request = _FakeRequest(disconnect_after=1)  # one pull (sources) allowed, then "gone"

    async def run():
        return [chunk async for chunk in _stream(request, "What is the deposit?", [], pipeline)]

    chunks = asyncio.run(run())
    assert len(chunks) == 1
    assert "event: sources" in chunks[0]
    assert generator.calls == [], "the model call must not have been made after the disconnect"


def test_no_disconnect_streams_every_event_through_to_done():
    generator = FakeGenerator()
    pipeline = _pipeline(generator)
    request = _FakeRequest(disconnect_after=999)

    async def run():
        return [chunk async for chunk in _stream(request, "What is the deposit?", [], pipeline)]

    chunks = asyncio.run(run())
    assert any("event: sources" in c for c in chunks)
    assert any("event: done" in c for c in chunks)
    assert generator.calls, "the model call should have run when nothing disconnected"
