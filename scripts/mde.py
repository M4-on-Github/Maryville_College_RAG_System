import numpy as np
from scipy.stats import binomtest
rng = np.random.default_rng(7)

def power_mcnemar(n, b, c, alpha=0.05, sims=4000):
    """b = P(A wrong, B right), c = P(A right, B wrong). Exact McNemar."""
    p_conc = 1 - b - c
    hits = 0
    for _ in range(sims):
        draw = rng.choice([0,1,2], size=n, p=[b, c, p_conc])
        nb = int((draw==0).sum()); nc = int((draw==1).sum())
        if nb + nc == 0:
            continue
        if binomtest(nb, nb+nc, 0.5).pvalue < alpha:
            hits += 1
    return hits/sims

print("Paired config comparison, exact McNemar, alpha=0.05")
print(f"{'n':>5} {'delta':>7} {'discord':>8} {'power':>7}")
for n in (120, 60, 28, 24):
    for delta, disc in ((0.10, 0.20), (0.10, 0.35), (0.05, 0.20), (0.20, 0.30)):
        b = (disc + delta)/2; c = (disc - delta)/2
        if c < 0: continue
        print(f"{n:>5} {delta:>7.2f} {disc:>8.2f} {power_mcnemar(n,b,c):>7.2f}")

# MDE by bisection on the simulated power curve. Slow but exact; the normal
# approximation understates every value here by roughly a point.
def mde(n, disc, target=0.80, lo=0.01, hi=None):
    hi = min(disc, 0.99) if hi is None else hi
    for _ in range(12):
        mid = (lo + hi) / 2
        b, c = (disc + mid) / 2, (disc - mid) / 2
        if power_mcnemar(n, b, c, sims=3000) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2

if __name__ == "__main__":
    print(f"\n{'n':>5} {'discord':>8} {'MDE @80% power':>16}")
    for n in (120, 60, 28):
        for disc in (0.15, 0.20, 0.30):
            print(f"{n:>5} {disc:>8.2f} {mde(n, disc):>15.1%}")
