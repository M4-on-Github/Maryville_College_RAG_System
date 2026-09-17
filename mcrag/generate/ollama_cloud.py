"""The metered seam: an OpenAI-compatible chat completion, streamed.

Programmed against ``/v1/chat/completions`` rather than against Ollama. That
interface is what Ollama Cloud, local Ollama, vLLM, llama.cpp, Groq, Together
and OpenRouter all speak, so the provider is a base URL in ``config.yaml`` and
not a code change. Nothing in this file names Ollama except the default URL.

Two behaviours here are the whole point of the class:

**A prompt that will not fit raises.** ``num_ctx`` truncates silently, dropping
the retrieved chunks off the front of the prompt while every retrieval metric
still looks healthy. The failure then reads as a retrieval bug for as long as it
takes someone to suspect the generator. So the prompt is measured before it is
sent, and an oversized one is refused.

**Reasoning is separated from the answer.** ``gpt-oss`` emits a reasoning
channel. Left inline it lands in citations, in scored answer text, and in the
output-token count the cost budget is built from.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import requests

from mcrag.env import require
from mcrag.generate.tokens import TokenEstimator
from mcrag.interfaces import Generator
from mcrag.types import Event

DEFAULT_BASE_URL = "https://ollama.com/v1"
DEFAULT_MODEL = "gpt-oss:20b-cloud"


class GenerationError(RuntimeError):
    """The provider refused, failed, or returned something unparseable."""


class ContextOverflow(GenerationError):
    """The prompt does not fit under ``num_ctx``, so it was never sent.

    Raised instead of sending, because the alternative is a silent truncation
    that is indistinguishable, downstream, from bad retrieval.
    """

    def __init__(self, prompt_tokens: int, budget: int, num_ctx: int) -> None:
        super().__init__(
            f"prompt is ~{prompt_tokens} tokens against a {budget}-token budget "
            f"(num_ctx {num_ctx} less the reply reservation); "
            "sending it would truncate the retrieved context silently"
        )
        self.prompt_tokens = prompt_tokens
        self.budget = budget
        self.num_ctx = num_ctx


@dataclass(frozen=True, slots=True)
class Usage:
    """What one call cost.

    ``timing_source`` says whether the timing is the provider's own or our
    stopwatch. Client wall-clock includes queueing behind the free tier's single
    concurrency slot, so it is an upper bound on GPU time rather than a
    measurement of it, and a budget built from it is conservative, not wrong.
    """

    prompt_tokens: int
    completion_tokens: int
    wall_s: float
    server_s: float | None = None
    timing_source: str = "client"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def seconds(self) -> float:
        """The number the quota budget is computed from."""
        return self.server_s if self.server_s is not None else self.wall_s


@dataclass(frozen=True, slots=True)
class Completion:
    """A drained generation: visible answer, hidden reasoning, and the bill."""

    text: str
    reasoning: str
    usage: Usage
    finish_reason: str | None = None
    model: str = ""


class ReasoningSplitter:
    """Peels the reasoning channel out of a token stream.

    Two encodings have to be handled, because providers disagree. Some put
    reasoning in its own ``delta`` field; others inline it between ``<think>``
    markers in the content. Feeding the splitter both and letting it decide keeps
    that disagreement out of the caller.
    """

    _OPEN = re.compile(r"<(think|thinking|reasoning)>", re.I)
    _CLOSE = re.compile(r"</(think|thinking|reasoning)>", re.I)

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    def feed(self, content: str) -> tuple[str, str]:
        """Return ``(visible, reasoning)`` for this piece of content.

        Anything that might be half a marker is held back rather than emitted, so
        a marker split across two stream chunks never reaches the answer.
        """
        self._buffer += content
        visible, reasoning = "", ""
        while self._buffer:
            pattern = self._CLOSE if self._inside else self._OPEN
            match = pattern.search(self._buffer)
            if match is None:
                head, self._buffer = self._hold_back(self._buffer)
                if self._inside:
                    reasoning += head
                else:
                    visible += head
                break
            before = self._buffer[: match.start()]
            if self._inside:
                reasoning += before
            else:
                visible += before
            self._buffer = self._buffer[match.end() :]
            self._inside = not self._inside
        return visible, reasoning

    def flush(self) -> tuple[str, str]:
        """Emit whatever was held back. Call once the stream has ended."""
        rest, self._buffer = self._buffer, ""
        return ("", rest) if self._inside else (rest, "")

    @staticmethod
    def _hold_back(text: str) -> tuple[str, str]:
        cut = text.rfind("<")
        # An angle bracket with a whole tag's worth of text after it cannot be a
        # partial marker; only a trailing fragment needs holding back.
        if cut == -1 or len(text) - cut > len("</thinking>"):
            return text, ""
        return text[:cut], text[cut:]


class OllamaCloudGenerator(Generator):
    """One chat completion per call, streamed, with the context guard in front.

    No network in the constructor and no API key read in it either: building the
    object from config must not require a key, so that config loading, hashing
    and the whole test suite work on a machine that has none.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        *,
        api_key: str | None = None,
        api_key_env: str = "OLLAMA_API_KEY",
        num_ctx: int = 8192,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        timeout_s: float = 180.0,
        reserve_tokens: int = 64,
        estimator: TokenEstimator | None = None,
        enforce_context: bool = True,
        stream: bool = True,
        session: requests.Session | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.reserve_tokens = reserve_tokens
        self.estimator = estimator or TokenEstimator()
        # Off only for the calibration probe, whose whole job is to send a prompt
        # the guard would refuse and record what the server does with it. No
        # pipeline arm ever sets this: an arm that silently truncates is an arm
        # whose retrieval numbers mean nothing.
        self.enforce_context = enforce_context
        self.stream = stream
        self._api_key = api_key
        self._api_key_env = api_key_env
        self._session = session

    # ---- context guard --------------------------------------------------

    @property
    def prompt_budget(self) -> int:
        """Tokens the prompt may occupy: the window less the reply we asked for.

        ``max_tokens`` is subtracted because the reply shares the window with the
        prompt. A prompt sized to the full window leaves the model no room to
        answer, and the truncation that follows is the same silent one.
        """
        budget = self.num_ctx - self.max_tokens - self.reserve_tokens
        if budget <= 0:
            raise ValueError(
                f"num_ctx {self.num_ctx} leaves no room for a prompt after reserving "
                f"{self.max_tokens} reply tokens; raise num_ctx or lower max_tokens"
            )
        return budget

    def check_prompt(self, text: str) -> int:
        """Estimate the prompt's tokens, raising if it will not fit."""
        tokens = self.estimator.estimate(text)
        if tokens > self.prompt_budget and self.enforce_context:
            raise ContextOverflow(tokens, self.prompt_budget, self.num_ctx)
        return tokens

    # ---- the call -------------------------------------------------------

    def generate(self, prompt: str, **kwargs: Any) -> Iterator[Event]:
        """Yield ``token`` events for the visible answer, then one ``done``.

        Reasoning never appears as a ``token`` event. It is accumulated and
        handed over in ``done``, where it can be logged and audited without ever
        being mistaken for the answer.
        """
        system = kwargs.pop("system", None)
        # Prior turns as chat messages, oldest first, between the system prompt
        # and this turn. Counted by the context guard like everything else: a
        # long conversation must overflow loudly, not push the retrieved
        # passages off the front of the window.
        history = kwargs.pop("history", None) or []
        for turn in history:
            if turn.get("role") not in ("user", "assistant") or not isinstance(turn.get("content"), str):
                raise ValueError(f"history turns must be {{role: user|assistant, content: str}}, got {turn!r}")
        messages = (
            ([{"role": "system", "content": system}] if system else [])
            + [{"role": t["role"], "content": t["content"]} for t in history]
            + [{"role": "user", "content": prompt}]
        )
        self.check_prompt("\n".join(m["content"] for m in messages))

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": self.stream,
            # Ollama reads num_ctx from options; OpenAI-compatible providers that
            # do not know the key ignore it. Sending it is the difference between
            # an explicit window and whatever the server's default happens to be.
            "options": {"num_ctx": self.num_ctx},
        }
        if self.stream:
            # Without this the streamed response carries no usage block at all,
            # and every token count in the cost record would be our own estimate
            # rather than the tokenizer's.
            payload["stream_options"] = {"include_usage": True}
        payload.update(kwargs)

        splitter = ReasoningSplitter()
        reasoning: list[str] = []
        visible: list[str] = []
        finish_reason: str | None = None
        raw_usage: dict[str, Any] = {}
        started = time.perf_counter()

        for chunk in self._post(payload):
            usage = chunk.get("usage")
            if usage:
                raw_usage = dict(usage)
            for key in ("eval_duration", "prompt_eval_duration"):
                if key in chunk:
                    raw_usage[key] = chunk[key]
            for choice in chunk.get("choices") or []:
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta") or choice.get("message") or {}
                thought = delta.get("reasoning") or delta.get("reasoning_content") or ""
                if thought:
                    reasoning.append(thought)
                content = delta.get("content") or ""
                if content:
                    shown, thought_inline = splitter.feed(content)
                    if thought_inline:
                        reasoning.append(thought_inline)
                    if shown:
                        visible.append(shown)
                        yield Event("token", {"text": shown})

        shown, thought_inline = splitter.flush()
        if thought_inline:
            reasoning.append(thought_inline)
        if shown:
            visible.append(shown)
            yield Event("token", {"text": shown})

        wall = time.perf_counter() - started
        answer = "".join(visible)
        thinking = "".join(reasoning)
        usage_obj = self._usage(raw_usage, prompt, answer, thinking, wall)
        yield Event(
            "done",
            {
                "text": answer,
                "reasoning": thinking,
                "finish_reason": finish_reason,
                "model": self.model,
                "usage": {
                    "prompt_tokens": usage_obj.prompt_tokens,
                    "completion_tokens": usage_obj.completion_tokens,
                    "wall_s": usage_obj.wall_s,
                    "server_s": usage_obj.server_s,
                    "timing_source": usage_obj.timing_source,
                    "seconds": usage_obj.seconds,
                },
            },
        )

    def complete(self, prompt: str, **kwargs: Any) -> Completion:
        """Drain :meth:`generate` into one value. Convenience, not a second path."""
        done: dict[str, Any] = {}
        for event in self.generate(prompt, **kwargs):
            if event.type == "done":
                done = event.data
        usage = done.get("usage", {})
        return Completion(
            text=done.get("text", ""),
            reasoning=done.get("reasoning", ""),
            usage=Usage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                wall_s=usage.get("wall_s", 0.0),
                server_s=usage.get("server_s"),
                timing_source=usage.get("timing_source", "client"),
            ),
            finish_reason=done.get("finish_reason"),
            model=done.get("model", self.model),
        )

    # ---- transport ------------------------------------------------------

    def _usage(
        self, raw: dict[str, Any], prompt: str, answer: str, thinking: str, wall: float
    ) -> Usage:
        """Prefer the provider's numbers; fall back to ours, and say which.

        Whether this endpoint reports token counts and durations at all is an
        open question in PLAN, and the answer belongs in the calibration record
        rather than in an assumption. ``timing_source`` is that answer, carried
        per call.
        """
        # Ollama's native API reports nanosecond durations; the OpenAI-compatible
        # surface may report neither. Read both spellings, insist on neither.
        server_ns = raw.get("eval_duration")
        prompt_ns = raw.get("prompt_eval_duration")
        server_s = None
        if server_ns is not None:
            server_s = (float(server_ns) + float(prompt_ns or 0)) / 1e9
        return Usage(
            prompt_tokens=int(raw.get("prompt_tokens") or self.estimator.estimate(prompt)),
            completion_tokens=int(
                raw.get("completion_tokens") or self.estimator.estimate(answer + thinking)
            ),
            wall_s=wall,
            server_s=server_s,
            timing_source="server" if server_s is not None else "client",
            raw=raw,
        )

    def resolve_api_key(self) -> str:
        """The key for this generator, read at call time rather than at construction.

        Constructors do no I/O and read no secrets here, so a config can be
        loaded and the whole test suite can run on a machine that has no key.
        The value is returned, never logged: the caller is expected to put it in
        an ``Authorization`` header and nowhere else.
        """
        return self._api_key or require(
            self._api_key_env,
            "put it in .env (which is gitignored) as OLLAMA_API_KEY=...",
        )

    def _post(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        session = self._session or requests.Session()
        key = self.resolve_api_key()
        response = session.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            stream=bool(payload.get("stream")),
            timeout=self.timeout_s,
        )
        if response.status_code >= 400:
            # The body carries the provider's reason: rate limit, unknown model,
            # bad key. Losing it turns every failure into "HTTP 400".
            raise GenerationError(f"HTTP {response.status_code}: {response.text[:500]}")

        # The provider sends UTF-8 (curly quotes, non-breaking spaces, accented
        # names all appear in real answers) but its `Content-Type` carries no
        # explicit charset, so `requests` falls back to Latin-1 and every
        # multi-byte character comes out as mojibake -- silently, since the
        # bytes still decode to *something*. Pin it before either read path.
        response.encoding = "utf-8"

        if not payload.get("stream"):
            yield response.json()
            return

        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                return
            try:
                yield json.loads(data)
            except json.JSONDecodeError as exc:
                raise GenerationError(f"unparseable stream chunk: {data[:200]}") from exc
