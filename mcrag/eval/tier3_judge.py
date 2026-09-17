"""Task 19, Tier 3: an LLM judge, gated by calibration (PLAN Sec 4d).

Built and tested here; **not run against real answers by this task**. PLAN's
own reservation (`decisions/0006`) is that Tier 2/3 scoring is spent at
Task 20's control run and the final test-split confirmation, not per
ablation -- so invoking this for real, against Task 16's 25 hand-scored
answers, is that calibration step, done once, when Task 20 needs it, not a
thing to spend quota on here.

Two hard rules PLAN states, both enforced in code rather than left as
documentation someone has to remember:

- `gpt-oss:20b` must never grade its own output -- so the judge is
  constructed with its own model name, checked against the model being
  judged.
- **Temperature 0 is mandatory.** Same-verdict consistency is >95% at temp 0
  and falls to ~70% at temp 1 -- an LLM judge run at any other temperature
  is not a measurement, it's a coin flip with extra steps.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from mcrag.eval.judge_calibration import CalibrationResult, assert_calibrated
from mcrag.interfaces import Scorer
from mcrag.types import Score

JUDGE_PROMPT_TEMPLATE = """You are grading one answer from a college-website \
question-answering system. Score it 0, 1, or 2:

2 = correct and grounded in the passages
1 = substantially correct but flawed (partial, or a minor grounding slip)
0 = wrong or hallucinated (not supported by the passages)

Question: {question}

Retrieved passages:
{context}

Answer to grade:
{answer}

Respond with exactly one line: "Score: N" where N is 0, 1, or 2."""

_SCORE_LINE = re.compile(r"score:\s*([012])\b", re.I)


class JudgesItsOwnOutputError(ValueError):
    """PLAN Sec 4d: `gpt-oss:20b` must never grade its own output."""


class TemperatureNotZeroError(ValueError):
    """PLAN Sec 4d: temperature 0 is mandatory for a judge call -- same-verdict
    consistency falls from >95% (temp 0) to ~70% (temp 1)."""


class UnparseableJudgeOutputError(ValueError):
    """The judge didn't return a `Score: N` line -- treated as a hard error,
    not a silent 0, since a parsing failure and a genuine "wrong" verdict
    must never be conflated in the reported metric."""


def build_judge_prompt(question: str, answer: str, context: list[str]) -> str:
    return JUDGE_PROMPT_TEMPLATE.format(
        question=question, context="\n\n".join(context), answer=answer
    )


def parse_judge_score(judge_output: str) -> int:
    match = _SCORE_LINE.search(judge_output)
    if match is None:
        raise UnparseableJudgeOutputError(f"no 'Score: N' line in judge output: {judge_output!r}")
    return int(match.group(1))


@dataclass(frozen=True, slots=True)
class Tier3JudgeScorer(Scorer):
    """`judge_fn` is a caller-supplied `str -> str` closure over whatever
    `Generator` is actually judging (kept decoupled from this module the
    same way `mcrag.eval.ablation_runner`'s `evaluate_fn` is kept decoupled
    from any one pipeline) -- this class owns the prompt, the parsing, the
    self-judging guard, and the calibration gate; not the HTTP call.
    """

    judge_fn: Callable[[str], str]
    judge_model_name: str
    judged_model_name: str
    temperature: float
    calibration: CalibrationResult | None = None
    tier: int = 3

    def __post_init__(self) -> None:
        if self.judge_model_name == self.judged_model_name:
            raise JudgesItsOwnOutputError(
                f"{self.judge_model_name!r} cannot judge its own output -- PLAN Sec 4d"
            )
        if self.temperature != 0:
            raise TemperatureNotZeroError(
                f"judge temperature must be 0, got {self.temperature} -- PLAN Sec 4d"
            )

    def judge(self, question: str, answer: str, context: list[str]) -> int:
        """Raises `UncalibratedJudgeError` unless this scorer carries a
        `calibration` that clears the kappa floor -- checked on every call,
        not just once, so a scorer built before calibration existed can
        never silently start reporting once one is attached later without
        re-verifying it still clears the bar."""
        assert_calibrated(self.calibration)
        prompt = build_judge_prompt(question, answer, context)
        return parse_judge_score(self.judge_fn(prompt))

    def score(self, answer: str, gold: dict) -> Score:
        value = self.judge(gold.get("question", ""), answer, gold.get("context", []))
        return Score(
            metric="judge_score",
            value=float(value),
            tier=self.tier,
            components={"kappa": self.calibration.kappa if self.calibration else None},
        )
