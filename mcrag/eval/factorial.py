"""Task 18: main effects and two-way interactions for a 2-level full factorial.

T18's 32 cells are a full 2^5 design -- boilerplate, chunking scheme,
reranker, fusion mode, silo boost, each at two levels -- so this uses the
standard coded (+-1) contrast method rather than a bespoke ANOVA: every level
combination is coded +1/-1, and an effect (main or interaction) is the mean
response over the '+1 product' half of the design minus the mean response
over the '-1 product' half. For a main effect that product is just the one
factor's own coding; for a two-way interaction it is the product of both
factors' codings. This is what makes "reranker is worth +X at k=20 and +Y at
k=5" (PLAN §Phase 4) reportable from the same 32 runs that give main effects,
with no extra runs.

Every cell must appear exactly once and every factor must take both levels
for the design to be balanced; `factorial_effects` checks both rather than
silently averaging over an unbalanced or duplicated design.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True, slots=True)
class Cell:
    """One evaluated arm: its factor levels and the metric value it scored."""

    levels: dict[str, bool]  # factor name -> True ("on"/high) or False ("off"/low)
    value: float


@dataclass(frozen=True, slots=True)
class FactorialResult:
    factors: tuple[str, ...]
    main_effects: dict[str, float]
    interactions: dict[tuple[str, str], float]
    n_cells: int


def _code(level: bool) -> int:
    return 1 if level else -1


def factorial_effects(cells: list[Cell]) -> FactorialResult:
    """Main effects and two-way interactions over a balanced 2-level design.

    `main_effects[f]` is in the metric's own units: `mean(value | f=on) -
    mean(value | f=off)`, holding nothing else fixed -- PLAN §4b's own
    "the reranker is worth +X" framing.

    `interactions[(f, g)]` follows the standard (Box/Hunter/Hunter) two-factor
    interaction convention: half the difference between f's simple effect
    when g is on and f's simple effect when g is off. A large value means f's
    effect genuinely depends on g's level -- e.g. "the reranker is worth more
    at k=20 than at k=5."
    """
    if not cells:
        raise ValueError("no cells to analyze")

    factors = tuple(sorted(cells[0].levels))
    for cell in cells:
        if sorted(cell.levels) != list(factors):
            raise ValueError(f"every cell must report the same factors; got {sorted(cell.levels)}")

    seen: set[tuple[bool, ...]] = set()
    for cell in cells:
        key = tuple(cell.levels[f] for f in factors)
        if key in seen:
            raise ValueError(f"duplicate cell {dict(zip(factors, key))} -- design is not balanced")
        seen.add(key)

    # A distinct-cell count exactly matching 2**len(factors), over binary
    # factors, can only be the full crossing by pigeonhole -- there are no
    # other 2**n distinct binary tuples to fill it with -- so this check
    # alone also guarantees every factor takes both levels.
    expected_n = 2 ** len(factors)
    if len(cells) != expected_n:
        raise ValueError(
            f"{len(factors)} factors implies a balanced design of {expected_n} cells, got {len(cells)}"
        )

    # Conventional factorial "effect" is a difference of means (PLAN's own
    # "worth +X" framing), which is exactly twice the coded regression
    # contrast `mean(code * y)` -- doubling here keeps main effects and
    # interactions in the same, directly-interpretable units.
    main_effects: dict[str, float] = {}
    for f in factors:
        main_effects[f] = 2 * statistics.mean(_code(cell.levels[f]) * cell.value for cell in cells)

    interactions: dict[tuple[str, str], float] = {}
    for f, g in combinations(factors, 2):
        interactions[(f, g)] = 2 * statistics.mean(
            _code(cell.levels[f]) * _code(cell.levels[g]) * cell.value for cell in cells
        )

    return FactorialResult(
        factors=factors, main_effects=main_effects, interactions=interactions, n_cells=len(cells)
    )
