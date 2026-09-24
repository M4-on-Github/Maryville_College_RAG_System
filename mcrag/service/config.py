"""Task 25: everything the API shell needs to know that isn't code -- the
API token and the CORS allowlist -- read from the environment rather than
hardcoded, so a deployment is configured by its process environment, never
by editing a file that could get committed with a real token in it.

`Settings.from_env()` is called fresh, not cached at import time, so a test
can set environment variables and get an isolated `Settings` back without
reloading `mcrag.service.api` -- see `tests/test_api.py`'s use of
`create_app(settings=...)` instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    api_token: str | None
    cors_origins: list[str]

    @classmethod
    def from_env(cls) -> Settings:
        """No token configured means every request to `/ask` is rejected --
        the safe default is a service nobody can call, not one anybody can,
        so a deployment that forgot to set `MCRAG_API_TOKEN` fails closed
        rather than silently serving in the open."""
        return cls(
            api_token=os.environ.get("MCRAG_API_TOKEN") or None,
            cors_origins=_split_csv(os.environ.get("MCRAG_CORS_ORIGINS", "")),
        )
