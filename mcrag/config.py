"""One config.yaml fully describes a pipeline.

Two properties matter and both are load-bearing for the experiment log:

1. **Unknown keys are an error.** A typo in an ablation config must not silently
   fall back to a default and be recorded as if the arm had run.
2. **The hash is stable.** Identical configs produce identical hashes across
   machines and runs, so a run directory name identifies its configuration.

Seam entries are ``{class: "module:Class", **kwargs}``. The runner passes kwargs
straight to the constructor, which is why adding an arm needs no runner change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

import yaml

T = TypeVar("T")


class ConfigError(ValueError):
    """Raised on an unknown key, a missing required key, or a bad type."""


@dataclass(frozen=True, slots=True)
class SeamConfig:
    """A named implementation plus its constructor kwargs."""

    cls: str
    kwargs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: Any, where: str) -> SeamConfig | None:
        if raw is None:
            return None
        if isinstance(raw, str):
            return cls(cls=raw)
        if not isinstance(raw, dict):
            raise ConfigError(
                f"{where}: expected a class spec or mapping, got {type(raw).__name__}"
            )
        data = dict(raw)
        spec = data.pop("class", None)
        if not spec:
            raise ConfigError(
                f"{where}: mapping must carry a 'class' key naming the implementation"
            )
        return cls(cls=spec, kwargs=data)


@dataclass(frozen=True, slots=True)
class CrawlConfig:
    user_agent: str
    contact: str
    requests_per_second: float = 1.0
    timeout_s: float = 30.0
    max_retries: int = 3
    sitemaps: tuple[str, ...] = ()
    excluded_sitemaps: tuple[str, ...] = ()
    catalog_root: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkConfig:
    max_tokens: int = 400
    overlap_ratio: float = 0.15
    embedder_token_limit: int = 512


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    k: int = 10
    candidate_k: int = 50
    legs: tuple[SeamConfig, ...] = ()
    fuser: SeamConfig | None = None
    reranker: SeamConfig | None = None
    reformulator: SeamConfig | None = None
    silo_boost: float = 0.0


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    model: str = "gpt-oss:20b-cloud"
    base_url: str = "https://ollama.com/v1"
    num_ctx: int = 8192
    temperature: float = 0.0
    max_tokens: int = 1024
    generator: SeamConfig | None = None


@dataclass(frozen=True, slots=True)
class EvalConfig:
    gold_path: str | None = None
    split: str = "dev"
    tau: float | None = None
    scorers: tuple[SeamConfig, ...] = ()


@dataclass(frozen=True, slots=True)
class Config:
    """The whole pipeline. ``arm`` names the ablation cell for the results table."""

    name: str
    arm: str = "baseline"
    seed: int = 42
    crawl: CrawlConfig | None = None
    chunk: ChunkConfig = field(default_factory=ChunkConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    eval: EvalConfig = field(default_factory=EvalConfig)
    notes: str = ""

    # ---- loading -------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str | Path) -> Config:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ConfigError(f"{path}: top level must be a mapping")
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Config:
        data = dict(raw)
        kwargs: dict[str, Any] = {}

        sections = {
            "crawl": CrawlConfig,
            "chunk": ChunkConfig,
            "retrieval": RetrievalConfig,
            "generation": GenerationConfig,
            "eval": EvalConfig,
        }
        for key, section_cls in sections.items():
            if key in data:
                raw_section = data.pop(key)
                # An explicit null round-trips as "absent". to_dict() emits null
                # for unset optional sections, so from_dict must accept it back.
                kwargs[key] = (
                    None if raw_section is None else _build_section(section_cls, raw_section, key)
                )

        for key in ("name", "arm", "seed", "notes"):
            if key in data:
                kwargs[key] = data.pop(key)

        if data:
            raise ConfigError(
                f"unknown config key(s): {sorted(data)} -- "
                "a typo here would silently run a different arm than the one logged"
            )
        if "name" not in kwargs:
            raise ConfigError("config must carry a 'name'")
        return cls(**kwargs)

    # ---- identity ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=True, default_flow_style=False)

    @property
    def config_hash(self) -> str:
        """Stable 12-char digest. Key order and dict ordering cannot affect it."""
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


# ---- helpers -----------------------------------------------------------

_SEAM_KEYS = {"fuser", "reranker", "reformulator", "generator"}
_SEAM_LIST_KEYS = {"legs", "scorers"}


def _build_section(section_cls: type[T], raw: Any, where: str) -> T:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: expected a mapping, got {type(raw).__name__}")
    data = dict(raw)
    known = {f.name for f in fields(section_cls)}  # type: ignore[arg-type]
    unknown = set(data) - known
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {sorted(unknown)}; known keys are {sorted(known)}"
        )

    built: dict[str, Any] = {}
    for key, value in data.items():
        if key in _SEAM_KEYS:
            built[key] = SeamConfig.parse(value, where=f"{where}.{key}")
        elif value is None:
            built[key] = None
        elif key in _SEAM_LIST_KEYS:
            if not isinstance(value, list):
                raise ConfigError(f"{where}.{key}: expected a list")
            built[key] = tuple(
                SeamConfig.parse(v, where=f"{where}.{key}[{i}]") for i, v in enumerate(value)
            )
        elif isinstance(value, list):
            built[key] = tuple(value)
        else:
            built[key] = value
    return section_cls(**built)  # type: ignore[return-value]


def _plain(obj: Any) -> Any:
    """Recursively convert to JSON/YAML-safe primitives, deterministically."""
    if isinstance(obj, SeamConfig):
        # Emit the *input* form, not the internal one. asdict() would write
        # {"cls": ..., "kwargs": {...}}, which does not load back as a seam and
        # so would break both round-tripping and the hash's meaning.
        return _plain({"class": obj.cls, **obj.kwargs})
    if is_dataclass(obj) and not isinstance(obj, type):
        # Walk fields by hand rather than via asdict(): asdict() converts nested
        # dataclasses bottom-up, so a SeamConfig would already be a plain dict
        # by the time the branch above could rewrite it into its input form.
        return {f.name: _plain(getattr(obj, f.name)) for f in sorted(fields(obj), key=lambda f: f.name)}
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj
