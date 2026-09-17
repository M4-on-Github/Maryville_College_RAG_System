"""Task 19, Tier 0: deterministic generation-quality checks.

Verification step: hand-verify against 5 real answers -- see
test_matches_a_hand_verified_t16_answer for the literal T16 case this
mirrors (docs/phase3b-sanity-review.md, adversarial-10).
"""

from __future__ import annotations

from mcrag.eval.tier0_scoring import extract_cited_urls, looks_like_a_refusal, score_tier0


# ---- extract_cited_urls -----------------------------------------------------


def test_extracts_a_bare_url_from_prose():
    answer = "Source: the policy page (https://www.maryvillecollege.edu/business-office/billing/)."
    assert extract_cited_urls(answer) == ["https://www.maryvillecollege.edu/business-office/billing/"]


def test_extracts_multiple_urls_and_strips_trailing_punctuation():
    answer = "See https://a.edu/x, and also https://b.edu/y."
    assert extract_cited_urls(answer) == ["https://a.edu/x", "https://b.edu/y"]


def test_no_urls_returns_empty_list():
    assert extract_cited_urls("No sources cited here at all.") == []


# ---- looks_like_a_refusal ---------------------------------------------------


def test_detects_an_explicit_refusal():
    assert looks_like_a_refusal(
        "The passages you provided do not contain any information about that."
    )


def test_detects_a_cannot_answer_phrasing():
    assert looks_like_a_refusal("I can't answer that based on the retrieved passages.")


def test_a_real_answer_is_not_flagged_as_a_refusal():
    assert not looks_like_a_refusal(
        "The $300 tuition deposit is refundable if you notify the college by May 1st."
    )


# ---- score_tier0 -------------------------------------------------------------


def test_matches_a_hand_verified_t16_answer():
    # docs/phase3b-sanity-review.md, adversarial-10: hand-scored 2 (correct,
    # grounded), cites exactly the one retrieved+gold url.
    answer = (
        "According to Maryville College's deposit policy, the $300 tuition deposit is "
        "not waived but it is refundable if you notify the college by May 1st.\n\n"
        "Source: \"...\" (https://www.maryvillecollege.edu/international/admissions/undergraduate-degree/)"
    )
    retrieved_urls = {
        "https://www.maryvillecollege.edu/international/admissions/undergraduate-degree/",
        "https://www.maryvillecollege.edu/families/new/faq/",
    }
    gold_urls = {"https://www.maryvillecollege.edu/international/admissions/undergraduate-degree/"}
    result = score_tier0(
        answer, "Is there any point in paying my deposit early?", retrieved_urls, gold_urls,
        expects_answer=True,
    )
    assert result.citation_accuracy == 1.0
    assert result.citation_validity == 1.0
    assert result.refused is False
    assert result.refusal_correct is True


def test_citation_accuracy_and_validity_are_none_when_nothing_is_cited():
    result = score_tier0("A plain answer with no citation.", "q", {"u1"}, {"u1"}, expects_answer=True)
    assert result.citation_accuracy is None
    assert result.citation_validity is None


def test_citation_accuracy_penalizes_a_wrong_url_even_if_it_was_retrieved():
    answer = "See https://wrong.edu/page"
    result = score_tier0(answer, "q", {"https://wrong.edu/page"}, {"https://right.edu/page"}, expects_answer=True)
    assert result.citation_accuracy == 0.0
    assert result.citation_validity == 1.0  # it WAS retrieved, just not a gold source


def test_citation_validity_flags_a_fabricated_source_not_in_the_retrieved_set():
    answer = "See https://never-retrieved.edu/page"
    result = score_tier0(answer, "q", {"https://something-else.edu"}, {"https://never-retrieved.edu/page"}, expects_answer=True)
    assert result.citation_validity == 0.0
    assert result.citation_accuracy == 1.0  # coincidentally a real gold url, but hallucinated as a source


def test_refusal_correct_when_the_system_refuses_an_out_of_scope_question():
    answer = "I don't have any information about that in the retrieved passages."
    result = score_tier0(answer, "q", set(), set(), expects_answer=False)
    assert result.refused is True
    assert result.refusal_correct is True


def test_refusal_incorrect_when_the_system_refuses_an_answerable_question():
    answer = "I can't answer that based on the retrieved passages."
    result = score_tier0(answer, "q", set(), {"u1"}, expects_answer=True)
    assert result.refused is True
    assert result.refusal_correct is False


def test_refusal_incorrect_when_the_system_answers_an_out_of_scope_question():
    answer = "Sure! The answer is 42."
    result = score_tier0(answer, "q", set(), set(), expects_answer=False)
    assert result.refused is False
    assert result.refusal_correct is False


def test_exact_match_presence_credits_a_course_code_repeated_in_the_answer():
    result = score_tier0(
        "MATH 1110 is offered every fall semester.",
        "When is MATH 1110 offered?",
        set(), set(), expects_answer=True,
    )
    assert result.exact_match_presence == 1.0


def test_exact_match_presence_is_zero_when_the_entity_is_dropped():
    result = score_tier0(
        "It's offered every fall semester.",
        "When is MATH 1110 offered?",
        set(), set(), expects_answer=True,
    )
    assert result.exact_match_presence == 0.0


def test_exact_match_presence_is_none_when_the_question_has_no_detectable_entity():
    result = score_tier0("A generic answer.", "What is the mission statement?", set(), set(), expects_answer=True)
    assert result.exact_match_presence is None
