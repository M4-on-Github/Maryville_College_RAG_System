"""Task 19, Tier 1: local NLI faithfulness scoring.

The model is faked, as with CrossEncoderReranker, but the fake reads each
(premise, claim) pair and entails only when every word of the claim appears
in that premise. Canned per-row logits -- what the first version of these
tests used -- can't see which premise a claim was checked against, which is
how a scorer that silently truncated ~80% of its context passed them.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from mcrag.eval.nli_faithfulness import (
    SCORER_VERSION,
    NLIFaithfulnessScorer,
    answer_claims,
    normalize_text,
    premise_windows,
    split_sentences,
    strip_attribution,
)

_WORD = re.compile(r"[a-z0-9$]+")
_ENTAIL = [0.0, 5.0, 0.0]
_NEUTRAL = [0.0, 0.0, 5.0]


class _WordOverlapNLI:
    """Entails iff every word of the claim occurs in the *visible* premise.

    Only the first `read_chars` of a premise are visible, the way a real
    512-token model silently truncates -- without this, a fake that reads an
    unbounded premise would pass the one bug these tests most need to catch.
    """

    def __init__(self, read_chars: int = 1500) -> None:
        self.read_chars = read_chars
        self.pairs_seen: list[tuple[str, str]] = []

    def predict(self, pairs):
        self.pairs_seen.extend(pairs)
        rows = []
        for premise, claim in pairs:
            premise_words = set(_WORD.findall(premise[: self.read_chars].lower()))
            claim_words = set(_WORD.findall(claim.lower()))
            rows.append(_ENTAIL if claim_words <= premise_words else _NEUTRAL)
        return np.array(rows)


def _scorer(**kwargs) -> tuple[NLIFaithfulnessScorer, _WordOverlapNLI]:
    scorer = NLIFaithfulnessScorer(**kwargs)
    fake = _WordOverlapNLI()
    scorer._model = fake
    return scorer, fake


# ---- split_sentences ---------------------------------------------------------


def test_splits_on_sentence_boundaries():
    assert split_sentences("The deposit is $300. It is refundable by May 1st.") == [
        "The deposit is $300.",
        "It is refundable by May 1st.",
    ]


def test_does_not_split_on_a_decimal_number():
    assert split_sentences("Your GPA must be 3.5 or higher to qualify.") == [
        "Your GPA must be 3.5 or higher to qualify."
    ]


def test_empty_text_produces_no_sentences():
    assert split_sentences("   ") == []


# ---- answer_claims -------------------------------------------------------------


def test_strips_markdown_citation_markers_and_source_asides():
    answer = (
        "Bonner Scholars volunteer **10 hours per week**【1】. "
        "(Source: https://www.maryvillecollege.edu/bonner/)"
    )
    assert answer_claims(answer) == ["Bonner Scholars volunteer 10 hours per week."]


def test_splits_bulleted_lines_into_separate_claims():
    answer = "- The deposit is $300 total.\n- It is refundable by May 1st."
    assert answer_claims(answer) == ["The deposit is $300 total.", "It is refundable by May 1st."]


def test_drops_source_lines_and_fragments_too_short_to_check():
    answer = "No. The deposit is refundable by May 1st.\nSource: the admissions page"
    assert answer_claims(answer) == ["The deposit is refundable by May 1st."]


# ---- normalize_text / strip_attribution ----------------------------------------


def test_normalizes_the_unicode_punctuation_llm_output_actually_uses():
    # Straight from a real T20 answer: non-breaking hyphen, narrow no-break space, curly quotes.
    assert normalize_text("$3,000 per‑year stipend “quoted”") == '$3,000 per-year stipend "quoted"'


def test_strips_a_leading_according_to_wrapper():
    claim = 'According to the Fine Arts instrumental programs page, "Regardless of your major or instrument, we can find a place for you!"'
    assert strip_attribution(claim) == "Regardless of your major or instrument, we can find a place for you!"


def test_strips_a_states_that_wrapper():
    claim = "Maryville College's financial aid policy states that students must file the FAFSA to be considered."
    assert strip_attribution(claim) == "Students must file the FAFSA to be considered."


def test_leaves_a_claim_with_no_wrapper_untouched():
    claim = "The deposit is refundable by May 1st."
    assert strip_attribution(claim) == claim


def test_does_not_reduce_a_claim_to_nothing_when_the_wrapper_is_the_content():
    claim = "According to the catalog, yes."
    assert strip_attribution(claim) == claim


def test_an_attributed_verbatim_quote_is_supported():
    # ss-16 in the T20 baseline: a verbatim quote from the passage scored 0.00
    # entailment because of its "According to ..." wrapper.
    scorer, _ = _scorer()
    result = scorer.score_answer(
        'According to the Fine Arts page, "Regardless of your major or instrument, we can find a place for you!"',
        ["Regardless of your major or instrument, we can find a place for you! Ensembles earn credit."],
    )
    assert result.value == 1.0


# ---- premise_windows -------------------------------------------------------------


def test_every_window_fits_the_budget():
    text = " ".join(f"Sentence number {i} has some filler words in it." for i in range(60))
    windows = premise_windows(text, max_chars=200)
    assert windows
    assert all(len(w) <= 200 for w in windows)


def test_windows_cover_every_sentence():
    sentences = [f"Fact {i} is stated plainly here." for i in range(40)]
    windows = premise_windows(" ".join(sentences), max_chars=150)
    for s in sentences:
        assert any(s in w for w in windows)


def test_consecutive_windows_overlap():
    text = " ".join(f"Sentence {i} is here." for i in range(30))
    windows = premise_windows(text, max_chars=100)
    assert len(windows) > 2
    first_words = set(windows[0].split())
    second_words = set(windows[1].split())
    assert first_words & second_words


def test_a_sentence_longer_than_the_budget_is_hard_split_not_dropped():
    long_sentence = "word " * 100  # 500 chars, no sentence boundary
    windows = premise_windows(long_sentence.strip() + ".", max_chars=120)
    assert all(len(w) <= 120 for w in windows)
    assert sum(w.count("word") for w in windows) >= 100


def test_rejects_a_non_positive_budget():
    with pytest.raises(ValueError):
        premise_windows("text", max_chars=0)


# ---- NLIFaithfulnessScorer ---------------------------------------------------


def test_does_not_load_a_model_at_construction():
    assert NLIFaithfulnessScorer()._model is None


def test_a_claim_supported_only_deep_in_the_context_is_still_found():
    # The regression test for the truncation bug: 4,000+ chars of unrelated
    # context come first, and the only supporting sentence is at the very
    # end of the last chunk -- far past what one 512-token premise holds.
    filler = " ".join(f"Unrelated sentence number {i} about campus parking." for i in range(80))
    context = [filler, filler, "The Bonner stipend is three thousand dollars per year."]
    scorer, _ = _scorer(window_chars=300)
    result = scorer.score_answer("The Bonner stipend is three thousand dollars per year.", context)
    assert result.value == 1.0


def test_no_single_premise_sent_to_the_model_exceeds_the_window_budget():
    filler = " ".join(f"Unrelated sentence number {i} about campus parking." for i in range(80))
    scorer, fake = _scorer(window_chars=300)
    scorer.score_answer("Some claim about parking lots here.", [filler, filler])
    assert fake.pairs_seen
    assert all(len(premise) <= 300 for premise, _ in fake.pairs_seen)


def test_partially_supported_answer_scores_the_supported_fraction():
    scorer, _ = _scorer()
    result = scorer.score_answer(
        "The deposit is three hundred dollars. The library opens at midnight.",
        ["The deposit is three hundred dollars and it is refundable."],
    )
    assert result.value == 0.5
    assert result.per_claim == (True, False)


def test_a_claim_counts_if_any_one_chunk_supports_it():
    scorer, _ = _scorer()
    result = scorer.score_answer(
        "Tuition is due in August.",
        ["Housing forms are due in March.", "Tuition is due in August each year."],
    )
    assert result.value == 1.0


def test_no_claims_returns_none_not_zero():
    scorer, _ = _scorer()
    assert scorer.score_answer("No.", ["some context here"]).value is None


def test_no_context_returns_none_not_zero():
    scorer, _ = _scorer()
    assert scorer.score_answer("A real answer sentence here.", []).value is None


def test_truncation_count_is_zero_when_no_tokenizer_is_available():
    scorer, _ = _scorer()
    result = scorer.score_answer("The deposit is three hundred dollars.", ["The deposit is three hundred dollars."])
    assert result.n_truncated_pairs == 0


def test_truncation_count_flags_pairs_over_the_model_limit():
    scorer, _ = _scorer()
    scorer._tokenizer = lambda premise, claim: {"input_ids": (premise + " " + claim).split()}
    scorer._max_length = 5  # any real pair exceeds five "tokens"
    result = scorer.score_answer(
        "The deposit is three hundred dollars.", ["The deposit is three hundred dollars."]
    )
    assert result.n_truncated_pairs == result.n_pairs > 0


def test_score_implements_the_scorer_interface_with_tier_1():
    scorer, _ = _scorer()
    result = scorer.score("The deposit is three hundred dollars.", {"context": ["The deposit is three hundred dollars."]})
    assert result.tier == 1
    assert result.metric == "faithfulness"
    assert result.value == 1.0
    assert result.components["scorer_version"] == SCORER_VERSION


def test_score_reports_undefined_rather_than_a_misleading_zero():
    scorer, _ = _scorer()
    result = scorer.score("A sentence with words.", {"context": []})
    assert result.value == 0.0
    assert result.components["undefined"] is True
