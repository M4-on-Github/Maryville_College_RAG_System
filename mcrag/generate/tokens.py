"""Counting prompt tokens without the tokenizer.

The context guard needs a token count *before* the call, and the server that
owns the tokenizer only reports the count afterwards, in ``usage``. So we
estimate, and we estimate in the safe direction.

**Safe means over-counting.** Under-counting lets an oversized prompt through and
``num_ctx`` truncates it silently: the retrieved chunks fall off the front,
recall@k still looks fine, and the failure presents as a retrieval bug for as
long as it takes someone to suspect the generator. Over-counting refuses a
prompt that would have fitted, which costs one shortened prompt and no wrong
answers.

The estimate has two parts, and the second is not optional. A chat model wraps
every request in a template, so tokens are ``overhead + text``: on
``gpt-oss:20b-cloud`` a seven-character prompt measures 70 tokens, of which
about 63 are template. A pure chars-per-token model fitted to that sample would
conclude 0.1 chars per token and refuse everything thereafter.

The parameters are not a guess for long. Every completed call returns the real
prompt token count, so a run of calls fits them -- see :meth:`TokenEstimator.calibrate`
and ``scripts/calibrate_quota.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Conservative starting point for English prose in a BPE vocabulary, which
# usually lands near 4 chars/token. Deliberately low: the estimate divides by
# this, so a smaller ratio yields a larger token count.
DEFAULT_CHARS_PER_TOKEN = 3.2

# Room for a chat template we have not measured yet. Replaced by a fitted value
# once a calibration run exists.
DEFAULT_OVERHEAD_TOKENS = 128


@dataclass(frozen=True, slots=True)
class TokenEstimator:
    """Characters to tokens, biased high, plus the chat template's fixed cost."""

    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN
    overhead_tokens: int = DEFAULT_OVERHEAD_TOKENS

    def __post_init__(self) -> None:
        if self.chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")
        if self.overhead_tokens < 0:
            raise ValueError("overhead_tokens cannot be negative")

    def estimate(self, text: str) -> int:
        """Upper-ish bound on the tokens this text will occupy in a request."""
        return self.overhead_tokens + (int(len(text) / self.chars_per_token) + 1 if text else 0)

    @classmethod
    def calibrate(
        cls,
        samples: Sequence[tuple[str, int]],
        *,
        slope_safety: float = 0.9,
        overhead_margin: int = 16,
    ) -> TokenEstimator:
        """Fit from observed ``(prompt_text, prompt_tokens)`` pairs.

        Least squares gives the slope, ``slope_safety`` tilts it in the safe
        direction, and the overhead is then raised until the line sits above
        every sample in the set, plus a margin. The result over-counts every
        prompt it was fitted on, which is the only property that matters here.

        Least squares rather than the steepest observed pair: two prompts of
        nearly equal length can differ by tokens for reasons that have nothing to
        do with density, and the pair-slope between them is arbitrarily small.
        One such pair in twenty would set the ratio for the whole run.

        Fewer than two distinct lengths, or a fit that slopes the wrong way,
        returns the defaults rather than a line through one point.
        """
        points = [(float(len(text)), float(tokens)) for text, tokens in samples if tokens > 0]
        if len({chars for chars, _ in points}) < 2:
            return cls()

        n = len(points)
        mean_chars = sum(c for c, _ in points) / n
        mean_tokens = sum(t for _, t in points) / n
        variance = sum((c - mean_chars) ** 2 for c, _ in points)
        covariance = sum((c - mean_chars) * (t - mean_tokens) for c, t in points)
        tokens_per_char = covariance / variance if variance else 0.0
        if tokens_per_char <= 0:
            return cls()

        ratio = slope_safety / tokens_per_char
        overhead = max(tokens - chars / ratio for chars, tokens in points)
        return cls(
            chars_per_token=ratio,
            overhead_tokens=int(max(0.0, overhead)) + overhead_margin,
        )
