# Stream contract (Task 23)

**One endpoint, Server-Sent Events, typed events rather than raw text**
(PLAN §Phase 5). This document is the contract; `mcrag/service/events.py`'s
Pydantic models are the one source of truth for its shape in code.
`tests/test_stream_contract.py` parses every JSON example below and
round-trips it through the matching model with `extra="forbid"` — a field
added to a model and not documented here, or documented here and not
added to the model, fails that test. Doc and models cannot drift silently
apart.

**Governing constraint: no client is privileged.** This contract is the
entire product surface a client sees. Nothing about it may assume a
particular front end — a browser widget, a full site, a terminal client,
and a test all read the same five event types the same way.

## Versioning

The schema is versioned `v1`. The version travels in the `done` event's
`schema_version` field, not as a transport-level detail (an HTTP header, a
URL path segment) — a client checks it once, after the whole stream has
arrived, the same place it reads every other per-request summary field.
A breaking change to any event's shape bumps this string; an additive,
optional field does not.

## Wire format

One request, `POST /ask`, answered as a Server-Sent Events stream. Each
event is one SSE frame:

```
event: <type>
data: <json>

```

`<type>` is one of `sources` · `token` · `citation` · `refusal` · `done`,
always in that relative order (`sources` first, `done` last; `token` and
`citation` events interleave in between; `refusal` replaces the
`token`/`citation` stream entirely on a refused request — see below).
`mcrag.service.events.to_sse(event_type, model)` formats one frame from a
validated model instance; nothing else in the codebase should hand-format
this string.

**`sources` is emitted before the first generation token is requested, not
merely before the first token is yielded.** `gpt-oss`-family models think
before they write, so time-to-first-visible-token is the entire reasoning
phase — 10+ seconds of blank screen otherwise. Emitting sources as soon as
retrieval and reranking finish lets *any* client fill that gap with the
trust surface (what was found, and how fresh it is) instead of a spinner.
This behavior lives in the protocol, not in a UI, so every client gets it
for free. `mcrag/service/answer.py` yields `sources` from a genuine
generator suspension point strictly before the generation call is made —
proved, not just ordered, by `tests/test_service.py`'s
`test_no_generation_call_happens_before_sources_is_consumed`. The measured
gap between `sources` and the first generated token (Task 26) is logged by
`mcrag.service.answer`'s logger (`sources_to_first_token_ms`), the UX
number this whole design exists to shrink; it is not part of the wire
contract itself, since a client observes it directly as the gap between
its own `sources` and `token` frames.

**On a refusal**, the stream is `sources → refusal → done` — no `token` or
`citation` events at all, not an empty answer followed by a refusal
notice. A client never has to detect a refusal by pattern-matching
generated text.

## Event: `sources`

Retrieved chunks, as reranked, before generation starts.

| Field | Type | Description |
|---|---|---|
| `chunks` | list of chunk objects | see below, in final (reranked) order |
| `rewritten_query` | string or null | the query retrieval actually ran on, when it differs from the question the client sent (Task 28, PLAN §4c step 5 — conversational de-contextualization). `null` means no rewrite happened and the client's own question was the query. **Silent rewriting is undebuggable**: without this field a client seeing surprising sources cannot tell whether its question or a server-side rewrite produced them. Retrieval runs on the rewrite; *generation still runs on the original question*, since the model already receives the real prior turns as chat messages and substituting a rewrite there would risk answering a subtly different question than the student asked. |

Each chunk object:

| Field | Type | Description |
|---|---|---|
| `title` | string | the source page's title |
| `url` | string | `Chunk.source_url` |
| `silo` | list of strings | every silo this chunk belongs to (`Chunk.silo`, T8) |
| `heading_path` | list of strings | the heading trail to this chunk within its page |
| `rerank_score` | float or null | `null` while the reranker stage is off (`decisions/0007`) |
| `last_verified` | string (ISO 8601 date) | `Chunk.crawled_at` |
| `stale` | boolean | `last_verified` older than a configurable threshold (Task 26; `mcrag.service.answer.DEFAULT_STALENESS_DAYS`, 180 days, overridable per call) — computed server-side so no client re-implements the threshold policy |

```json sources
{"chunks": [{"title": "Financial Aid", "url": "https://www.maryvillecollege.edu/financial-aid/", "silo": ["financial_aid"], "heading_path": ["Financial Aid", "Types of Aid"], "rerank_score": null, "last_verified": "2026-08-14", "stale": false}], "rewritten_query": null}
```

## Event: `token`

One increment of visible answer text (reasoning-channel content, if the
model emits one, is never forwarded as a `token` — `decisions/0008`).

| Field | Type | Description |
|---|---|---|
| `text` | string | the next chunk of answer text to append |

```json token
{"text": "The FAFSA priority deadline is "}
```

## Event: `citation`

One citation attaching a source to a span of the answer text assembled so
far from `token` events. A client never re-parses prose to find what a
citation covers or where its link should go.

| Field | Type | Description |
|---|---|---|
| `claim_span` | pair of integers `[start, end)` | character offsets into the answer text accumulated so far |
| `source_url` | string | matches one `sources` chunk's `url` |
| `chunk_id` | string | matches one `sources` chunk exactly (`sources` carries no `chunk_id` field itself today — added here rather than there, since a citation is the only place code needs to resolve back to one specific chunk rather than just its page) |

```json citation
{"claim_span": [104, 168], "source_url": "https://www.maryvillecollege.edu/financial-aid/", "chunk_id": "financial-aid-000042"}
```

## Event: `refusal`

Replaces the `token`/`citation` stream entirely when the system declines
to answer. Every field here is structured — no client parses an apology
to find an office's email.

| Field | Type | Description |
|---|---|---|
| `reason` | string, one of `threshold` \| `gate` \| `model` | which refusal pathway fired. Deliberately reuses `per_query.jsonl`'s existing `refusal_source` vocabulary (PLAN §5) rather than inventing a second taxonomy: `threshold` is Task 21's retrieval-score gate (`decisions/0009`, τ = 4.96 on the frozen top 5), checked before generation runs so a threshold refusal spends no generation quota; `model` is the model itself declining in its own generated text (`mcrag.eval.tier0_scoring.looks_like_a_refusal`), checked only when `threshold` did not already fire — any-signal-wins precedence between exactly these two, realized as short-circuit order rather than a simultaneous vote. `gate` stays schema-valid but **is not wired by any code path** (Task 27, explicit human decision recorded in `tasks/plan.md` T27's Resolution): `decisions/0014` already built and rejected a dedicated two-step LLM answerability gate at rung 3 — it closed the out-of-scope gap completely but cost `-0.217 [-0.350, -0.083]` refusal_correct, outside every noise floor measured in this project and worse than rung 2's own rejected cost. Re-wiring one here without new evidence would re-litigate that settled decision. |
| `office` | string | the routed office's name, resolved from `data/offices.yaml` (T8, `decisions/0002`) |
| `contact_url` | string | that office's `destination_url` |
| `email` | string | that office's `email` |

```json refusal
{"reason": "threshold", "office": "Financial Aid", "contact_url": "https://www.maryvillecollege.edu/financial-aid/", "email": "financialaid@maryvillecollege.edu"}
```

An unroutable refusal (no chunk retrieved at all, or the routing chunk's
silo is `other`/absent from `data/offices.yaml`) falls back to Admissions
(`mcrag.offices.GENERAL_SILO`, a Task 27 policy decision, not a fact drawn
from `offices.yaml` itself) rather than emitting an empty `office` field —
this contract does not special-case it, the same three fields are always
populated.

## Event: `done`

Always the last event on every request, refused or not.

| Field | Type | Description |
|---|---|---|
| `latency_ms` | object | per-stage wall time, milliseconds — see below |
| `server_ns` | object | the generation provider's own timing, nanoseconds — the authoritative cost signal (PLAN §5), separate from the client-measured `latency_ms` |
| `refused` | boolean | true iff a `refusal` event preceded this one |
| `schema_version` | string | `"v1"` — see Versioning above |

`latency_ms` fields (matches `per_query.jsonl`'s existing naming, PLAN §5,
extended with the `literal` retrieval leg T18 added after that example was
written):

| Field | Type | Description |
|---|---|---|
| `embed` | float | query embedding time |
| `dense` | float | dense-index search time |
| `bm25` | float | BM25-index search time |
| `literal` | float | literal-index search time |
| `fuse` | float | RRF fusion time across the three legs above |
| `reform` | float or null | Task 28's query-reformulation pass, before retrieval — a metered cloud call in the shipped default (`LlmDecontextualizer`, adopted in `decisions/0015`), so it must not disappear into `e2e`. `null` only when no reformulator is configured at all; a stage that did not run reports `null`, never a misleading `0.0`. On a single-turn request the stage runs but makes no model call, so this is a sub-millisecond number rather than a generation cost |
| `rerank` | float or null | Task 27's threshold-gate cross-encoder pass (`decisions/0009`) — a different use of the same model `decisions/0007` froze the *retrieval* reranker stage off for (scoring only here, never reordering), so this now reports real wall time on every request rather than always being `null` |
| `generate_ttft` | float | time to first generated token |
| `generate_total` | float | total generation wall time |
| `e2e` | float | end-to-end request time |

`server_ns` fields:

| Field | Type | Description |
|---|---|---|
| `total` | integer | total server-side generation time |
| `prompt_eval` | integer | server-side prompt-processing time |
| `eval` | integer | server-side token-generation time |

```json done
{"latency_ms": {"embed": 12.0, "dense": 3.0, "bm25": 6.0, "literal": 4.0, "fuse": 1.0, "reform": null, "rerank": 45.0, "generate_ttft": 8100.0, "generate_total": 11200.0, "e2e": 11326.0}, "server_ns": {"total": 11040000000, "prompt_eval": 1210000000, "eval": 9830000000}, "refused": false, "schema_version": "v1"}
```

## A note on `mcrag.types.Event`

`mcrag/types.py` already defines a small, untyped `Event` dataclass
(`type: str`, `data: dict`), used internally by
`mcrag/generate/ollama_cloud.py` to stream a *generation call's* own
`token`/`done` events out of that one stage. That is a different,
lower-level concept from this document: it is one stage's private
streaming primitive, produced and consumed entirely inside a single
`Generator` implementation, and its `done` event carries that call's
token/timing usage — not a whole request's. Task 24's `answer()` callable
is the place these get composed: it drives retrieval, reranking and one or
more generation calls, and it is `answer()`'s job to translate whatever
those stages report into the five wire event types this document defines,
constructing the `mcrag.service.events` models directly. Nothing upstream
of Task 24 needs to change for this contract to exist; nothing described
here reaches a client until Task 24/25 exist to serve it.
