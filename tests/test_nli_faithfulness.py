"""Task 19, Tier 1: local NLI faithfulness scoring."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from mcrag.eval.nli_faithfulness import NLIFaithfulnessScorer, split_sentences


# ---- split_sentences --------------------------------------------------------


def test_splits_on_sentence_boundaries():
    text = "The deposit is $300. It is refundable by May 1st. Contact admissions for details."
    assert split_sentences(text) == [
        "The deposit is $300.",
        "It is refundable by May 1st.",
        "Contact admissions for details.",
    ]


def test_single_sentence_with_no_boundary():
    assert split_sentences("Just one sentence here") == ["Just one sentence here"]


def test_empty_text_produces_no_sentences():
    assert split_sentences("   ") == []


def test_does_not_split_on_a_decimal_number():
    # no capital letter follows the "." in "3.5", so this must not split
    assert split_sentences("Your GPA must be 3.5 or higher to qualify.") == [
        "Your GPA must be 3.5 or higher to qualify."
    ]


# ---- NLIFaithfulnessScorer: orchestration, not the real model --------------
# Matches the project's existing convention (CrossEncoderReranker) of not
# unit-testing the real downloaded model -- _load is monkeypatched.


def _logits(*rows: tuple[float, float, float]) -> np.ndarray:
    return np.array(rows)


def test_does_not_load_a_model_at_construction():
    scorer = NLIFaithfulnessScorer()
    assert scorer._model is None


def test_fully_entailed_answer_scores_1():
    scorer = NLIFaithfulnessScorer()
    fake_model = MagicMock()
    fake_model.predict.return_value = _logits((0.1, 0.8, 0.1), (0.0, 0.9, 0.1))
    scorer._model = fake_model

    result = scorer.score_answer(
        "The deposit is $300. It is refundable by May 1st.",
        ["The $300 tuition deposit is refundable if you notify us by May 1st."],
    )
    assert result.value == 1.0
    assert result.n_sentences == 2
    assert result.n_entailed == 2


def test_partially_entailed_answer_scores_the_entailed_fraction():
    scorer = NLIFaithfulnessScorer()
    fake_model = MagicMock()
    # sentence 1 entailed (index 1 highest), sentence 2 contradiction (index 0 highest)
    fake_model.predict.return_value = _logits((0.1, 0.8, 0.1), (0.9, 0.05, 0.05))
    scorer._model = fake_model

    result = scorer.score_answer("True claim. False claim.", ["context supporting the true claim"])
    assert result.value == 0.5
    assert result.per_sentence == (True, False)


def test_no_sentences_returns_none_not_zero():
    scorer = NLIFaithfulnessScorer()
    result = scorer.score_answer("   ", ["some context"])
    assert result.value is None


def test_no_context_returns_none_not_zero():
    scorer = NLIFaithfulnessScorer()
    result = scorer.score_answer("A real answer sentence.", [])
    assert result.value is None


def test_score_implements_the_scorer_interface_with_tier_1():
    scorer = NLIFaithfulnessScorer()
    fake_model = MagicMock()
    fake_model.predict.return_value = _logits((0.1, 0.8, 0.1))
    scorer._model = fake_model

    result = scorer.score("One entailed sentence.", {"context": ["supporting context"]})
    assert result.tier == 1
    assert result.metric == "faithfulness"
    assert result.value == 1.0


def test_score_reports_undefined_rather_than_a_misleading_zero():
    scorer = NLIFaithfulnessScorer()
    result = scorer.score("A sentence.", {"context": []})
    assert result.value == 0.0
    assert result.components["undefined"] is True
