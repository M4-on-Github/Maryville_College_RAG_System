"""Read ``.env`` without taking a dependency to do it.

Only two rules, and both exist so that a secret cannot be committed or logged by
accident: the file is never written to, and a value already present in the real
environment always wins. Overriding the environment from a file on disk is how a
developer's stale key ends up in a CI run.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> list[str]:
    """Set any ``KEY=value`` not already in the environment. Returns key names."""
    p = Path(path)
    if not p.exists():
        return []
    loaded = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def require(name: str, hint: str = "") -> str:
    """Fetch a secret or fail with a message that never echoes its value."""
    load_dotenv()
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set{'; ' + hint if hint else ''}")
    return value
