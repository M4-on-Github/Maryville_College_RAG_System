"""Task 18: main effects and two-way interactions over a 2-level full factorial."""

from __future__ import annotations

from itertools import product

import pytest

from mcrag.eval.factorial import Cell, factorial_effects


def _full_2x2(values: dict[tuple[bool, bool], float]) -> list[Cell]:
    return [Cell(levels={"a": a, "b": b}, value=v) for (a, b), v in values.items()]


def test_main_effect_matches_the_hand_computed_difference_of_means():
    # a's effect: mean(value | a=True) - mean(value | a=False), independent of b
    cells = _full_2x2({
        (True, True): 0.9, (True, False): 0.7,
        (False, True): 0.5, (False, False): 0.3,
    })
    result = factorial_effects(cells)
    mean_a_true = (0.9 + 0.7) / 2
    mean_a_false = (0.5 + 0.3) / 2
    assert result.main_effects["a"] == pytest.approx(mean_a_true - mean_a_false)
    assert result.main_effects["a"] == pytest.approx(0.4)


def test_main_effect_of_b_is_independent_of_a_when_additive():
    cells = _full_2x2({
        (True, True): 0.9, (True, False): 0.7,
        (False, True): 0.5, (False, False): 0.3,
    })
    result = factorial_effects(cells)
    assert result.main_effects["b"] == pytest.approx(0.2)


def test_zero_interaction_for_a_purely_additive_response():
    # value = base + 0.4*a + 0.2*b, no interaction term at all
    cells = _full_2x2({
        (True, True): 0.6, (True, False): 0.4,
        (False, True): 0.2, (False, False): 0.0,
    })
    result = factorial_effects(cells)
    assert result.interactions[("a", "b")] == pytest.approx(0.0, abs=1e-9)


def test_interaction_detected_when_the_effect_of_a_depends_on_b():
    # a's effect is +0.5 when b is True, but 0 when b is False -- a real
    # interaction, the PLAN 4b "reranker helps more at large k" case.
    cells = _full_2x2({
        (True, True): 1.0, (True, False): 0.5,
        (False, True): 0.5, (False, False): 0.5,
    })
    result = factorial_effects(cells)
    effect_a_given_b_true = 1.0 - 0.5
    effect_a_given_b_false = 0.5 - 0.5
    # Standard (Box/Hunter/Hunter) convention: the interaction is HALF the
    # difference between the two simple effects, not the raw difference.
    expected_interaction = (effect_a_given_b_true - effect_a_given_b_false) / 2
    assert result.interactions[("a", "b")] == pytest.approx(expected_interaction)
    assert result.interactions[("a", "b")] == pytest.approx(0.25)


def test_rejects_an_unbalanced_cell_count():
    cells = _full_2x2({(True, True): 1.0, (True, False): 1.0, (False, True): 1.0})
    with pytest.raises(ValueError, match="balanced"):
        factorial_effects(cells)


def test_rejects_duplicate_cells():
    cells = _full_2x2({(True, True): 1.0, (True, False): 1.0, (False, True): 1.0, (False, False): 1.0})
    cells.append(Cell(levels={"a": True, "b": True}, value=0.5))
    with pytest.raises(ValueError, match="duplicate"):
        factorial_effects(cells)


def test_rejects_empty_input():
    with pytest.raises(ValueError, match="no cells"):
        factorial_effects([])


def test_rejects_mismatched_factor_sets_across_cells():
    cells = [
        Cell(levels={"a": True, "b": True}, value=1.0),
        Cell(levels={"a": True, "c": True}, value=1.0),
    ]
    with pytest.raises(ValueError, match="same factors"):
        factorial_effects(cells)


def test_a_full_2_to_the_3_design_reports_every_pairwise_interaction():
    levels = list(product([True, False], repeat=3))
    cells = [Cell(levels=dict(zip(("x", "y", "z"), lv)), value=sum(lv)) for lv in levels]
    result = factorial_effects(cells)
    assert result.n_cells == 8
    assert set(result.main_effects) == {"x", "y", "z"}
    assert set(result.interactions) == {("x", "y"), ("x", "z"), ("y", "z")}
    # value is a pure sum of indicator(level=True) -- purely additive, so
    # every pairwise interaction should be ~0.
    for interaction_value in result.interactions.values():
        assert interaction_value == pytest.approx(0.0, abs=1e-9)
