"""Small-sample honesty tools. Pure numpy, no Nautilus: they take plain lists of per-trade PnL.

A point estimate of profit factor from a few dozen heavy-tailed trades is mostly noise. These
answer "how much could luck alone move this number?" instead of "what is the number?".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

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
