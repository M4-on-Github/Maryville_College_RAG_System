"""Task 19, Tier 3: an LLM judge, gated by calibration. No real quota spent
here -- `judge_fn` is always a fake in these tests; the actual calibration
run against Task 16's hand-scored answers is Task 20's job, per
decisions/0006."""

from __future__ import annotations

import pytest

from mcrag.eval.judge_calibration import CalibrationResult, UncalibratedJudgeError
from mcrag.eval.tier3_judge import (
    JudgesItsOwnOutputError,
    Tier3JudgeScorer,
    TemperatureNotZeroError,
    UnparseableJudgeOutputError,
    build_judge_prompt,
    parse_judge_score,
)

GOOD_CALIBRATION = CalibrationResult(kappa=0.75, n=25, categories=(0, 1, 2))


# ---- build_judge_prompt / parse_judge_score --------------------------------


def test_build_judge_prompt_includes_question_answer_and_context():
    prompt = build_judge_prompt("What is X?", "X is Y.", ["passage one", "passage two"])
    assert "What is X?" in prompt
    assert "X is Y." in prompt
    assert "passage one" in prompt and "passage two" in prompt


def test_parse_judge_score_extracts_the_number():
    assert parse_judge_score("Score: 2") == 2
    assert parse_judge_score("some reasoning...\nScore: 0\n") == 0


def test_parse_judge_score_is_case_insensitive():
    assert parse_judge_score("score: 1") == 1


def test_parse_judge_score_raises_on_unparseable_output():
    with pytest.raises(UnparseableJudgeOutputError):
        parse_judge_score("I think this is pretty good.")


# ---- Tier3JudgeScorer construction guards ----------------------------------


def test_rejects_a_judge_that_is_the_same_model_as_the_judged_one():
    with pytest.raises(JudgesItsOwnOutputError):
        Tier3JudgeScorer(
            judge_fn=lambda p: "Score: 2",
            judge_model_name="gpt-oss:20b",
            judged_model_name="gpt-oss:20b",
            temperature=0.0,
            calibration=GOOD_CALIBRATION,
        )


def test_rejects_a_nonzero_temperature():
    with pytest.raises(TemperatureNotZeroError):
        Tier3JudgeScorer(
            judge_fn=lambda p: "Score: 2",
            judge_model_name="gemma",
            judged_model_name="gpt-oss:20b",
            temperature=0.7,
            calibration=GOOD_CALIBRATION,
        )


# ---- Tier3JudgeScorer.judge / score: the calibration gate ------------------


def test_judge_raises_when_uncalibrated():
    scorer = Tier3JudgeScorer(
        judge_fn=lambda p: "Score: 2",
        judge_model_name="gemma",
        judged_model_name="gpt-oss:20b",
        temperature=0.0,
        calibration=None,
    )
    with pytest.raises(UncalibratedJudgeError):
        scorer.judge("q", "a", ["context"])


def test_judge_raises_when_kappa_is_below_the_floor():
    scorer = Tier3JudgeScorer(
        judge_fn=lambda p: "Score: 2",
        judge_model_name="gemma",
        judged_model_name="gpt-oss:20b",
        temperature=0.0,
        calibration=CalibrationResult(kappa=0.3, n=25, categories=(0, 1, 2)),
    )
    with pytest.raises(UncalibratedJudgeError):
        scorer.judge("q", "a", ["context"])


def test_judge_returns_the_parsed_score_once_calibrated():
    scorer = Tier3JudgeScorer(
        judge_fn=lambda p: "Score: 2",
        judge_model_name="gemma",
        judged_model_name="gpt-oss:20b",
        temperature=0.0,
        calibration=GOOD_CALIBRATION,
    )
    assert scorer.judge("q", "a", ["context"]) == 2


def test_score_implements_the_scorer_interface_with_tier_3():
    scorer = Tier3JudgeScorer(
        judge_fn=lambda p: "Score: 1",
        judge_model_name="gemma",
        judged_model_name="gpt-oss:20b",
        temperature=0.0,
        calibration=GOOD_CALIBRATION,
    )
    result = scorer.score("an answer", {"question": "q", "context": ["ctx"]})
    assert result.tier == 3
    assert result.value == 1.0
    assert result.components["kappa"] == pytest.approx(0.75)


def test_the_prompt_actually_sent_carries_the_real_question_and_answer():
    seen_prompts = []

    def fake_judge(prompt: str) -> str:
        seen_prompts.append(prompt)
        return "Score: 2"

    scorer = Tier3JudgeScorer(
        judge_fn=fake_judge,
        judge_model_name="gemma",
        judged_model_name="gpt-oss:20b",
        temperature=0.0,
        calibration=GOOD_CALIBRATION,
    )
    scorer.judge("What is the deposit amount?", "It is $300.", ["The deposit is $300."])
    assert "What is the deposit amount?" in seen_prompts[0]
    assert "It is $300." in seen_prompts[0]
