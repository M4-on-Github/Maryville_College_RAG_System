"""Config names a class; this resolves the name to the class.

The point is that the ablation runner contains no `if arm == "bm25"`. A config
value like `mcrag.retrieval.bm25:BM25Retriever` is imported and constructed with
whatever kwargs sit beside it in the config.

Resolution is restricted to the `mcrag` package by default. A config file is
data, and data that can import arbitrary modules is a code-execution surface;
tests widen the allowlist explicitly rather than the loader relaxing it.
"""

from __future__ import annotations

import importlib
from typing import Any, TypeVar

T = TypeVar("T")

_ALLOWED_ROOTS: set[str] = {"mcrag"}


def allow_root(root: str) -> None:
    """Widen the import allowlist. Tests use this; production config does not."""
    _ALLOWED_ROOTS.add(root)


def resolve(spec: str) -> type:
    """Turn 'package.module:ClassName' into the class object."""
    if ":" not in spec:
        raise ValueError(
            f"class spec {spec!r} must be 'module.path:ClassName' -- "
            "a bare name is ambiguous and silently resolves to the wrong thing"
        )
    module_path, _, class_name = spec.partition(":")
    root = module_path.split(".", 1)[0]
    if root not in _ALLOWED_ROOTS:
        raise ValueError(
            f"refusing to import from {root!r}; allowed roots are {sorted(_ALLOWED_ROOTS)}"
        )
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise ValueError(f"cannot import module {module_path!r} for spec {spec!r}") from exc
    try:
        obj = getattr(module, class_name)
    except AttributeError as exc:
        raise ValueError(f"{module_path!r} has no attribute {class_name!r}") from exc
    if not isinstance(obj, type):
        raise ValueError(f"{spec!r} resolved to {type(obj).__name__}, not a class")
    return obj


def build(spec: str, expected: type[T] | None = None, **kwargs: Any) -> T:
    """Resolve and instantiate. `expected` enforces the seam's contract."""
    cls = resolve(spec)
    if expected is not None and not issubclass(cls, expected):
        raise TypeError(f"{spec!r} is not a {expected.__name__}; it cannot fill that seam")
    return cls(**kwargs)  # type: ignore[return-value]
