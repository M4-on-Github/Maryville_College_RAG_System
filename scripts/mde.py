"""Task 16b: reproduces PLAN §4f's detectable-effect table by simulation.

The normal approximation to McNemar's test understates every minimum
detectable effect (MDE) in that table by roughly a point, so power here is
estimated the slow, honest way: simulate paired question outcomes many times,
run the *real* exact test on each simulated draw, and see how often it
rejects. `power_mcnemar` calls `mcrag.eval.significance.mcnemar_p_value`
directly rather than reimplementing the test, so this script cannot silently
drift from what an actual Phase 4 comparison computes.

    python scripts/mde.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.eval.significance import mcnemar_p_value  # noqa: E402

# PLAN 4f's own splits: pooled test set, dev, cross-silo test slice, out-of-
# scope test slice.
SPLIT_SIZES = {"pooled test": 120, "dev": 60, "cross-silo test": 28, "out-of-scope test": 24}


def power_mcnemar(
    n: int,
    p_b_wins: float,
    p_a_wins: float,
    *,
    alpha: float = 0.05,
    sims: int = 4000,
    seed: int = 7,
) -> float:
    """Simulated power: how often the exact test rejects at `alpha`.

    `p_b_wins` = P(config `a` misses, config `b` hits) on a random question;
    `p_a_wins` the reverse; the remainder is concordant (both miss or both
    hit) and irrelevant to McNemar. Each simulated trial draws `n` questions
    from that 3-outcome distribution and re-derives the discordant counts.
    """
    p_concordant = 1 - p_b_wins - p_a_wins
    if p_concordant < 0:
        raise ValueError(f"p_b_wins + p_a_wins must be <= 1, got {p_b_wins + p_a_wins}")
    rng = random.Random(seed)
    outcomes = ("b_wins", "a_wins", "concordant")
    weights = (p_b_wins, p_a_wins, p_concordant)
    rejections = 0
    for _ in range(sims):
        draw = rng.choices(outcomes, weights=weights, k=n)
        n01 = draw.count("b_wins")
        n10 = draw.count("a_wins")
        if n01 + n10 == 0:
            continue
        if mcnemar_p_value(n01, n10) < alpha:
            rejections += 1
    return rejections / sims


def minimum_detectable_effect(
    n: int,
    discordance: float,
    *,
    target_power: float = 0.80,
    lo: float = 0.01,
    hi: float | None = None,
    bisection_steps: int = 12,
    sims_per_step: int = 3000,
    seed: int = 7,
) -> float:
    """Smallest paired effect (`p_b_wins - p_a_wins`) detectable at
    `target_power`, by bisection on the simulated power curve."""
    hi = min(discordance, 0.99) if hi is None else hi
    for _ in range(bisection_steps):
        mid = (lo + hi) / 2
        p_b_wins, p_a_wins = (discordance + mid) / 2, (discordance - mid) / 2
        power = power_mcnemar(n, p_b_wins, p_a_wins, sims=sims_per_step, seed=seed)
        if power < target_power:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def print_power_table() -> None:
    print("Paired config comparison, exact McNemar, alpha=0.05")
    print(f"{'n':>5} {'delta':>7} {'discord':>8} {'power':>7}")
    for n in SPLIT_SIZES.values():
        for delta, disc in ((0.10, 0.20), (0.10, 0.35), (0.05, 0.20), (0.20, 0.30)):
            p_b_wins, p_a_wins = (disc + delta) / 2, (disc - delta) / 2
            if p_a_wins < 0:
                continue
            power = power_mcnemar(n, p_b_wins, p_a_wins)
            print(f"{n:>5} {delta:>7.2f} {disc:>8.2f} {power:>7.2f}")


def print_mde_table() -> None:
    print(f"\n{'split':>18} {'n':>5} {'discord':>8} {'MDE @80% power':>16}")
    for label, n in SPLIT_SIZES.items():
        for disc in (0.15, 0.20, 0.30):
            mde = minimum_detectable_effect(n, disc)
            print(f"{label:>18} {n:>5} {disc:>8.2f} {mde:>15.1%}")


def main() -> int:
    print_power_table()
    print_mde_table()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
