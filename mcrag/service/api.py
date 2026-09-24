"""Task 25: FastAPI + SSE shell over Task 24's `answer()` -- thin by
construction, no logic beyond transport. Auth, CORS, and streaming
mechanics live here; retrieval, generation, and the event contract all live
in `mcrag.service.answer` / `mcrag.service.events`, untouched by this
module's existence, and `mcrag.service.answer` still imports no web
framework (`tests/test_service.py` asserts that, not this module).

`create_app(settings=..., pipeline=...)` is a factory, not a bare module
`app`, specifically so `tests/test_api.py` can stand up an isolated app
(its own token, its own CORS allowlist, a fake pipeline) with no monkeypatched
environment variable and no module reload. `app` at the bottom is the one
real deployments run (`uvicorn mcrag.service.api:app`).

**Auth.** A single static token in an `X-API-Key` header, compared with
`secrets.compare_digest` (constant-time, same reasoning as any credential
check). No token configured (`Settings.api_token is None`) means every
request is rejected -- fails closed, not open.

**Cancellation.** `answer()` buffers the model's full reply before yielding
any `token`/`citation` events -- it has to: whether the reply is a refusal
is decided from the *complete* text, and `docs/stream_contract.md` requires
`refusal` to replace `token`/`citation` entirely, not retract them after
the fact. That means the generator is only ever suspended at a `yield`
in two places: before retrieval starts (nothing spent yet, moot), and right
after `sources` is emitted but before the model call begins (the one place
that matters -- the entire generation call, the expensive step, has not
started). `_stream` below checks `request.is_disconnected()` before every
pull from the generator, so a client that has already left when `sources`
would otherwise trigger the model call never causes that call to be made,
and closes the generator in every exit path so Python raises `GeneratorExit`
at whichever `yield` it is suspended at. A disconnect noticed *during* the
model call itself cannot interrupt that call early with this generator
shape -- documented here rather than silently claimed as finer-grained than
it is.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from mcrag.service.answer import AnswerPipeline, answer
from mcrag.service.config import Settings
from mcrag.service.events import EVENT_MODELS, AnyEvent, to_sse
from mcrag.service.health import get_health_info

_EVENT_TYPE_NAMES = {model: name for name, model in EVENT_MODELS.items()}


def _to_sse(event: AnyEvent) -> str:
    return to_sse(_EVENT_TYPE_NAMES[type(event)], event)


_EXHAUSTED = object()


def _next_or_exhausted(gen):
    # A bare `next(gen)` run through `loop.run_in_executor` re-raises a
    # `StopIteration` the executor caught into the awaiting coroutine, which
    # asyncio refuses (`StopIteration interacts badly with generators`) --
    # so exhaustion is signaled by return value instead of by exception.
    try:
        return next(gen)
    except StopIteration:
        return _EXHAUSTED


class AskRequest(BaseModel):
    """`history` is prior **user** turns only, oldest first -- the client
    sends no assistant text, because this service regenerates its own prior
    answers rather than trusting a transcript of what it supposedly said
    (`mcrag.service.answer._run_prior_turns`).

    There is no session id and no server-side conversation store, by design
    (Task 28's first criterion): the whole conversation arrives with every
    request, so the server holds no state it could not rebuild, a restart
    loses nothing, and two processes behind a load balancer need no shared
    session affinity. The cost is paid honestly -- prior turns are
    re-answered each request -- rather than hidden in a cache that would
    have to be invalidated, replicated, and expired.
    """

    question: str
    history: list[str] = []


async def _stream(
    request: Request, question: str, history: list[str], pipeline: AnswerPipeline | None
) -> AsyncIterator[str]:
    loop = asyncio.get_event_loop()
    # `answer()` is a synchronous generator that makes blocking network
    # calls (retrieval's embedder, the generation provider); pulling it
    # straight in this async function would stall the event loop for every
    # other request, so each `next()` runs in the default threadpool.
    gen = answer(question, history, pipeline=pipeline)
    try:
        while True:
            if await request.is_disconnected():
                break
            event = await loop.run_in_executor(None, _next_or_exhausted, gen)
            if event is _EXHAUSTED:
                break
            yield _to_sse(event)
    finally:
        gen.close()


def create_app(settings: Settings | None = None, pipeline: AnswerPipeline | None = None) -> FastAPI:
    """`pipeline=None` means `answer()` falls back to its own process-wide
    default (`mcrag.service.answer.get_default_pipeline`) -- real
    deployments never pass one. `tests/test_api.py` always passes a fake."""
    settings = settings or Settings.from_env()
    app = FastAPI(title="mcrag answer service")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["POST", "GET"],
        allow_headers=["*"],
    )

    def require_token(request: Request) -> None:
        supplied = request.headers.get("x-api-key")
        configured = settings.api_token
        if not configured or not supplied or not secrets.compare_digest(supplied, configured):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing API token")

    @app.post("/ask", dependencies=[Depends(require_token)])
    async def ask(request: Request, body: AskRequest) -> StreamingResponse:
        return StreamingResponse(
            _stream(request, body.question, body.history, pipeline), media_type="text/event-stream"
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        info = get_health_info()
        return {"status": info.status, "index_build_id": info.index_build_id, "corpus_hash": info.corpus_hash}

    return app


app = create_app()
