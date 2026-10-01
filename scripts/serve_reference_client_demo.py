"""Task 29's manual verification harness -- serves the disposable reference
client (`clients/reference_client.html`) next to a real FastAPI app whose
*generation is faked*, so the three required manual questions (including one
refusal) cost zero generation quota.

Everything below the transport is real: `mcrag.service.api.create_app`, the
real `answer()` pipeline shape, the real event models, the real SSE framing.
Only the leaves that would cost money or need an index on disk are doubles --
the same ones `tests/test_service.py` already defines, imported rather than
re-invented here for the same reason `tests/test_api.py` imports them (two
copies of a double drift).

The reformulator is the *real* `HistoryConcatenationReformulator`, not a fake:
it is free (no model call), and it makes `rewritten_query` genuinely non-null
on a follow-up, which is one of the things the client has to render.

    python scripts/serve_reference_client_demo.py              # Task 29's fixture
    python scripts/serve_reference_client_demo.py --client chat  # clients/chat.html
    # then open http://127.0.0.1:8099/ and paste the token it prints

This is a fixture, not a deployment: it binds loopback only, its token is a
constant in the source, and it must never be pointed at real traffic.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcrag.retrieval.reformulation import HistoryConcatenationReformulator  # noqa: E402
from mcrag.service.api import create_app  # noqa: E402
from mcrag.service.config import Settings  # noqa: E402
from mcrag.types import Hit  # noqa: E402
from tests.test_service import FakeGenerator, FakeLeg, _chunk, _pipeline  # noqa: E402

CLIENTS = {
    "reference": ROOT / "clients" / "reference_client.html",
    "chat": ROOT / "clients" / "chat.html",
}
DEFAULT_CLIENT = "reference"
TOKEN = "demo-token-not-a-secret"  # noqa: S105 -- a fixture's constant, loopback only
PORT = 8099

# One fresh chunk and one deliberately old one, so the client's `stale` badge
# (Task 26, 180-day default) has something to render.
CHUNKS = [
    _chunk(),
    _chunk(
        chunk_id="c2",
        url="https://www.maryvillecollege.edu/financial-aid/",
        title="Financial Aid",
        crawled_at=datetime.datetime(2024, 1, 5),
    ),
]

REFUSAL_TEXT = "I cannot find any information about that in the passages provided."


def build_app(client: str = DEFAULT_CLIENT):
    generator = FakeGenerator()
    # The third manual question: a model-pathway refusal. Keyed on a substring
    # of the prompt, which contains the user's own question verbatim inside
    # <question> -- ask anything mentioning "parking" to see the refusal path.
    generator.by_keyword["parking"] = REFUSAL_TEXT
    pipeline = _pipeline(generator, CHUNKS, reformulator=HistoryConcatenationReformulator())
    # `_pipeline` only hits its first chunk; the demo wants both retrieved so the
    # client renders a multi-source list with one stale entry in it.
    pipeline.dense = FakeLeg(
        [Hit(chunk_id=c.chunk_id, score=1.0 - i / 10, leg="dense", rank=i, chunk=c) for i, c in enumerate(CHUNKS)]
    )

    app = create_app(settings=Settings(api_token=TOKEN, cors_origins=[]), pipeline=pipeline)

    page = CLIENTS[client]

    @app.get("/")
    def serve_client() -> FileResponse:
        return FileResponse(page, media_type="text/html")

    return app


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        choices=sorted(CLIENTS),
        default=DEFAULT_CLIENT,
        help="which client to serve at /. Default `reference` is Task 29's own fixture, so a"
        " re-run of T29's manual verification shows exactly what it showed then; `chat` serves"
        " clients/chat.html, the kept conversational client.",
    )
    args = parser.parse_args()

    print(f"{args.client} client: http://127.0.0.1:{PORT}/   API key: {TOKEN}")
    print("suggested three questions: 'What is the deposit?' -> a follow-up like")
    print("'When is it due?' (shows rewritten_query) -> anything with 'parking' (refusal)")
    uvicorn.run(build_app(args.client), host="127.0.0.1", port=PORT, log_level="warning")
