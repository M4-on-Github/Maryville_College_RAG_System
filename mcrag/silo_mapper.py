"""Task 8 step 4: assign silo labels from `data/silos.yaml`'s path-prefix rules.

One implementation, no planned ablation -- per `mcrag/interfaces.py`'s own
convention this stays a plain class, not an ABC seam.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

OTHER = "other"


class SiloMapper:
    """Longest-path-prefix match against `silos.yaml`'s rule table.

    Every rule from every silo is flattened into one table and sorted by
    prefix length, longest first, so a page matches the most specific rule
    that applies (e.g. `about/inside/titleix` beats `about/inside`) rather
    than whichever silo happened to be listed first in the YAML.
    """

    def __init__(self, rules: list[tuple[str, str]]) -> None:
        self._rules = sorted(rules, key=lambda r: -len(r[0]))

    @classmethod
    def from_yaml(cls, path: str | Path = "data/silos.yaml") -> SiloMapper:
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        rules = [
            (prefix, silo["name"])
            for silo in data["silos"]
            for prefix in silo["path_prefixes"]
        ]
        return cls(rules)

    def silo_names(self) -> set[str]:
        return {silo for _, silo in self._rules}

    def assign(self, url: str, base: str) -> tuple[str, ...]:
        """One silo label for a URL, or `("other",)` if nothing matches."""
        path = url.replace(base, "").strip("/").split("#")[0]
        for prefix, silo in self._rules:
            if path == prefix or path.startswith(prefix + "/"):
                return (silo,)
        return (OTHER,)
