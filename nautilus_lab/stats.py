"""Small-sample honesty tools. Pure numpy, no Nautilus: they take plain lists of per-trade PnL.

A point estimate of profit factor from a few dozen heavy-tailed trades is mostly noise. These
answer "how much could luck alone move this number?" instead of "what is the number?".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from statistics import NormalDist

import numpy as np


def profit_factor(pnls) -> float:
    pnls = np.asarray(pnls, float)
    win, loss = pnls[pnls > 0].sum(), -pnls[pnls <= 0].sum()
    return math.inf if loss == 0 and win > 0 else (win / loss if loss > 0 else 0.0)


def _ci(draws) -> tuple[float, float]:
    """95% interval taken from actual resampled values: interpolating between two infinities
    (a resample with no losing trade) would return nan."""
    return float(np.percentile(draws, 2.5, method="lower")), float(np.percentile(draws, 97.5, method="higher"))


@dataclass(frozen=True)
class BootstrapPF:
    point: float
    lo: float  # 2.5th percentile
    hi: float  # 97.5th percentile
    p_below_1: float  # share of resamples with PF < 1: how often luck alone erases the edge
    n: int
    unit: str  # "trades" or "tokens"

    @property
    def includes_one(self) -> bool:
        return self.lo <= 1.0 <= self.hi

    def line(self) -> str:
        verdict = "CI includes 1.0: no edge can be claimed" if self.includes_one else "CI excludes 1.0"
        return (f"PF {self.point:.2f}  95% CI [{self.lo:.2f}, {self.hi:.2f}]  "
                f"P(PF<1)={self.p_below_1:.0%}  (resampling {self.n} {self.unit}) -> {verdict}")


def bootstrap_pf(pnls, *, resamples: int = 2000, seed: int = 0) -> BootstrapPF | None:
    """Resample trades with replacement. Treats trades as independent: optimistic when trades
    cluster in time or by token (see `bootstrap_pf_by_group`)."""
    pnls = np.asarray(pnls, float)
    if len(pnls) < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(pnls), (resamples, len(pnls)))
    draws = np.array([profit_factor(pnls[i]) for i in idx])
    lo, hi = _ci(draws)
    return BootstrapPF(profit_factor(pnls), float(lo), float(hi), float((draws < 1.0).mean()), len(pnls), "trades")


def bootstrap_pf_by_group(groups: dict[str, list[float]], *, resamples: int = 2000, seed: int = 0) -> BootstrapPF | None:
    """Resample whole TOKENS (cluster bootstrap). Trades inside one token share its regime, so
    this is the stricter test, and the one that exposes a result carried by a single token."""
    keys = [k for k, v in groups.items() if v]
    if len(keys) < 3:
        return None
    rng = np.random.default_rng(seed)
    arrays = [np.asarray(groups[k], float) for k in keys]
    draws = np.array([
        profit_factor(np.concatenate([arrays[j] for j in rng.integers(0, len(arrays), len(arrays))]))
        for _ in range(resamples)
    ])
    lo, hi = _ci(draws)
    point = profit_factor(np.concatenate(arrays))
    return BootstrapPF(point, float(lo), float(hi), float((draws < 1.0).mean()), len(arrays), "tokens")


@dataclass(frozen=True)
class Concentration:
    total: float
    top3: float
    top3_share_of_total: float | None  # None when total <= 0
    top3_share_of_gross_profit: float | None
    drop_to_zero: int | None  # how many best trades must be removed for total PnL to reach <= 0
    n: int

    @property
    def red_flag(self) -> bool:
        return self.drop_to_zero is not None and self.drop_to_zero <= max(3, math.ceil(0.1 * self.n))


def concentration(pnls) -> Concentration:
    pnls = np.sort(np.asarray(pnls, float))[::-1]
    total, top3 = float(pnls.sum()), float(pnls[:3].sum())
    gross = float(pnls[pnls > 0].sum())
    drop = None
    if total > 0:
        remaining = total
        for k, p in enumerate(pnls, 1):
            remaining -= p
            if remaining <= 0:
                drop = k
                break
    return Concentration(
        total, top3, top3 / total if total > 0 else None, top3 / gross if gross > 0 else None, drop, len(pnls)
    )


# ---- multiple-testing: how much of this could be the best of N tries? --------------------------------
EULER_GAMMA = 0.5772156649015329


def sharpe_stats(returns) -> tuple[float, float, float, int]:
    """(per-trade Sharpe, skewness, raw kurtosis, n). Not annualised: trades are not periodic."""
    r = np.asarray(returns, float)
    n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return 0.0, 0.0, 3.0, n
    mu, sd = r.mean(), r.std(ddof=1)
    z = (r - mu) / sd
    return float(mu / sd), float((z**3).mean()), float((z**4).mean()), n


@dataclass(frozen=True)
class DeflatedSharpe:
    sharpe: float
    sr0: float  # the Sharpe the best of `trials` zero-skill strategies would show by luck
    dsr: float  # probability the true Sharpe exceeds that luck-adjusted bar
    trials: int
    n: int

    def line(self, gate: float = 0.95) -> str:
        return (f"Deflated Sharpe {self.dsr:.2f} (per-trade SR {self.sharpe:.3f} vs luck bar {self.sr0:.3f} after "
                f"{self.trials} trials, n={self.n}) -> {'above' if self.dsr >= gate else 'BELOW'} the {gate:.2f} convention")


def deflated_sharpe(returns, trials: int) -> DeflatedSharpe | None:
    """Bailey & Lopez de Prado (2014). `trials` is the number of configurations tried on this data,
    counted honestly: every threshold change, every rerun with different settings. With the trial
    Sharpe dispersion unknown we use its null value 1/(n-1), the standard fallback."""
    sr, skew, kurt, n = sharpe_stats(returns)
    if n < 10:
        return None
    nd = NormalDist()
    trials = max(1, int(trials))
    sd_sr = math.sqrt(1.0 / (n - 1))
    sr0 = 0.0 if trials == 1 else sd_sr * ((1 - EULER_GAMMA) * nd.inv_cdf(1 - 1 / trials)
                                           + EULER_GAMMA * nd.inv_cdf(1 - 1 / (trials * math.e)))
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr**2))
    return DeflatedSharpe(sr, sr0, nd.cdf((sr - sr0) * math.sqrt(n - 1) / denom), trials, n)


def pbo_cscv(matrix, splits: int = 8) -> float | None:
    """Probability of Backtest Overfitting by combinatorially symmetric cross-validation.
    `matrix`: rows = time slices (e.g. days), columns = configurations tried, values = PnL of that
    configuration in that slice. Returns the share of IS/OOS splits where the in-sample winner ranks
    below the OOS median. Needs >= 3 configurations; returns None otherwise (do not invent one)."""
    m = np.asarray(matrix, float)
    if m.ndim != 2 or m.shape[1] < 3 or m.shape[0] < splits:
        return None
    blocks = np.array_split(np.arange(m.shape[0]), splits)
    below = total = 0
    for is_idx in combinations(range(splits), splits // 2):
        oos_idx = [b for b in range(splits) if b not in is_idx]
        is_rows = np.concatenate([blocks[b] for b in is_idx])
        oos_rows = np.concatenate([blocks[b] for b in oos_idx])
        best = int(np.argmax(m[is_rows].sum(axis=0)))
        oos = m[oos_rows].sum(axis=0)
        rank = (oos < oos[best]).sum() / (len(oos) - 1)  # 1.0 = best OOS
        below += rank < 0.5
        total += 1
    return below / total
