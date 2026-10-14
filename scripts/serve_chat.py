"""Serve the chat page against the real pipeline: real indexes, real reranker,
real generation through Ollama Cloud.

    python scripts/serve_chat.py            # http://127.0.0.1:8099/
    python scripts/serve_chat.py --host 0.0.0.0 --port 8080

The page has no key field. `OLLAMA_API_KEY` is read from `.env` (or the real
environment, which wins) by `mcrag.env.load_dotenv`, inside this process; its
value is never printed, only whether it is present. The service's own
`X-API-Key` guard stays on, with a per-process random token that this server
adds to `/ask` itself, so `create_app` and its tests are unchanged.

That also means `/ask` is open to anyone who can reach this server, and every
question spends generation quota. Bind loopback (the default) for local use;
put a rate limit in front of it before exposing it (see docs/deploy.md).
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # indexes/, corpus/ and data/ are read by relative path

from fastapi.responses import FileResponse  # noqa: E402

from mcrag.env import load_dotenv  # noqa: E402
from mcrag.service.api import create_app  # noqa: E402
from mcrag.service.config import Settings  # noqa: E402

PAGE = ROOT / "clients" / "chat.html"


class _InjectKey:
    """Pure ASGI middleware: add the server's token to `/ask` requests."""

    def __init__(self, app, token: str) -> None:
        self.app, self.header = app, (b"x-api-key", token.encode())

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/ask":
            headers = [h for h in scope["headers"] if h[0] != b"x-api-key"]
            scope = {**scope, "headers": [*headers, self.header]}
        await self.app(scope, receive, send)


def build_app(warm: bool = True):
    load_dotenv()
    if not os.environ.get("OLLAMA_API_KEY"):
        raise SystemExit("OLLAMA_API_KEY is not set: add it to .env or the environment.")
    if warm:
        # Load indexes and models now, not on the first visitor's question.
        from mcrag.service.answer import get_default_pipeline

        get_default_pipeline()

    token = secrets.token_urlsafe(32)
    app = create_app(settings=Settings(api_token=token, cors_origins=[]))

    @app.get("/")
    def page() -> FileResponse:
        return FileResponse(PAGE, media_type="text/html")

    app.add_middleware(_InjectKey, token=token)
    return app


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8099")))
    args = parser.parse_args()
    app = build_app()
    print(f"OLLAMA_API_KEY present; serving http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
