"""The stream contract (Task 23, PLAN Phase 5) -- one source of truth for the
events `answer()` (Task 24) yields and a client consumes over Server-Sent
Events. Every model here has a matching entry in `docs/stream_contract.md`;
`tests/test_stream_contract.py` parses that doc's JSON examples and asserts
they round-trip through these exact models. `extra="forbid"` on every model
is what makes that check real: a field added here and not documented, or
documented and not added here, fails validation immediately rather than
drifting apart silently.

Versioned `v1`. The version travels in `DoneEvent.schema_version`, not as a
transport-level detail -- a client checks it once the whole stream is in
hand, the same place it reads every other per-request summary field.

This is a different, higher-level concept than `mcrag.types.Event`, which is
one generation call's own private streaming primitive (see
`mcrag/generate/ollama_cloud.py` and the note at the bottom of
`docs/stream_contract.md`). Task 24 is the seam that translates the latter
into the former; nothing upstream of it needs to import this module.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "v1"


class _StrictModel(BaseModel):
    """`extra="forbid"` on every wire event -- see module docstring."""

    model_config = ConfigDict(extra="forbid")


class SourceChunk(_StrictModel):
    """One retrieved chunk, as a client needs it to render the trust surface
    before generation has produced a single token (`sources` is emitted at
    rerank time, before the first generation token is even requested)."""

    title: str
    url: str
    silo: list[str]
    heading_path: list[str]
    rerank_score: float | None = None  # None while the reranker stage is off (decisions/0007)
    last_verified: str  # ISO 8601 date; Chunk.crawled_at
    stale: bool  # Task 26: last_verified older than a configurable threshold (mcrag.service.answer)


class SourcesEvent(_StrictModel):
    """`rewritten_query` exists because silent rewriting is undebuggable
    (Task 28): when de-contextualization turns a follow-up into a standalone
    question, the text retrieval actually ran on is *not* the text the client
    sent, and a client staring at surprising sources has no way to tell which
    of the two produced them. `None` means no rewrite happened -- a
    single-turn request, or a rewriter that declined -- so the client's own
    question is the query, and a client that ignores this field entirely
    still reads a valid v1 stream."""

    chunks: list[SourceChunk]
    rewritten_query: str | None = None


class TokenEvent(_StrictModel):
    text: str


class CitationEvent(_StrictModel):
    """`claim_span` is a `[start, end)` character-offset pair into the answer
    text assembled so far from `token` events -- a client never re-parses
    prose to find what a citation covers."""

    claim_span: tuple[int, int]
    source_url: str
    chunk_id: str


class RefusalEvent(_StrictModel):
    """`reason` names which refusal pathway fired (PLAN §4e's any-signal-wins
    precedence) -- reuses `per_query.jsonl`'s existing `refusal_source`
    vocabulary (PLAN §5), not a new taxonomy: `threshold` (Task 21's
    retrieval-score gate, decisions/0009), `model` (the model itself
    declining in its own generated text,
    `mcrag.eval.tier0_scoring.looks_like_a_refusal`).

    `gate` (an answerability gate ahead of generation) stays schema-valid but
    **is emitted by no code path** -- Task 27 wired `threshold` and `model`
    only, an explicit human decision recorded in that task's Resolution, on
    the evidence that `decisions/0014` built and rejected such a gate at a
    cost of -0.217 [-0.350, -0.083] refusal_correct. The literal is kept so a
    future gate with new evidence is an additive change, not a schema break."""

    reason: Literal["threshold", "gate", "model"]
    office: str
    contact_url: str
    email: str


class LatencyMs(_StrictModel):
    """Per-stage wall time, milliseconds. Matches `per_query.jsonl`'s
    existing naming (PLAN §5), extended with the `literal` retrieval leg
    Task 18 added after that example was written."""

    embed: float
    dense: float
    bm25: float
    literal: float
    fuse: float
    # Task 28: query reformulation, before retrieval. `None` when no
    # reformulator is configured (today's default) -- a stage that did not
    # run reports nothing rather than a misleading 0.0. Metered when the
    # de-contextualizer is the configured rung, so it must not vanish into
    # `e2e`: every stage that costs wall time is named here.
    reform: float | None = None
    rerank: float | None = None  # None while the reranker stage is off (decisions/0007)
    generate_ttft: float
    generate_total: float
    e2e: float


class ServerNs(_StrictModel):
    """The generation provider's own timing, nanoseconds -- PLAN §5's
    "authoritative cost signal", separate from `latency_ms`'s client-measured
    wall time."""

    total: int
    prompt_eval: int
    eval: int


class DoneEvent(_StrictModel):
    """Always the last event on every request, refused or not."""

    latency_ms: LatencyMs
    server_ns: ServerNs
    refused: bool
    schema_version: str = SCHEMA_VERSION


AnyEvent = SourcesEvent | TokenEvent | CitationEvent | RefusalEvent | DoneEvent
"""The union `answer()` (Task 24) actually yields -- named separately from
`mcrag.types.Event` (see module docstring) so the two are never confused at
an import site."""


EVENT_MODELS: dict[str, type[BaseModel]] = {
    "sources": SourcesEvent,
    "token": TokenEvent,
    "citation": CitationEvent,
    "refusal": RefusalEvent,
    "done": DoneEvent,
}


def to_sse(event_type: str, payload: BaseModel) -> str:
    """One `event: <type>\\ndata: <json>\\n\\n` frame -- the wire format
    `docs/stream_contract.md` specifies. Nothing else in the codebase should
    hand-format this string."""
    expected = EVENT_MODELS.get(event_type)
    if expected is None:
        raise ValueError(f"unknown event type {event_type!r}; expected one of {sorted(EVENT_MODELS)}")
    if not isinstance(payload, expected):
        raise TypeError(f"{event_type!r} events carry a {expected.__name__}, got {type(payload).__name__}")
    return f"event: {event_type}\ndata: {payload.model_dump_json()}\n\n"
