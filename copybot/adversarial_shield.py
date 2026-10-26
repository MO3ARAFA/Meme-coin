"""Pillar 1 — pre-trade kill switch: "am I the exit liquidity?".

Two independent vetoes, evaluated after the safety gate has the live quotes:

1. **Imitation-penalty net EV.** A follower always buys later and higher than the whale (on a
   bonding curve or thin pool, convexly so). Expected net profit of the copy:

       net_ev = (1 + edge) / (1 + drift) * (1 - exit_cost) - 1 - tip_frac - slippage_reserve

   `edge` is the whale's historical raw edge per copyable trade; `drift` is our executable buy
   price vs the whale's fill (so it already contains our buy leg's DEX fee and price impact);
   `exit_cost` is the sell leg's fee + impact (half the live Jupiter round trip, so the buy leg
   is not counted twice); `tip_frac` is the priority/Jito tip for both legs as a fraction of size. If the copy
   has no positive expectancy left, it is vetoed — however good the wallet is.

2. **Exit-liquidity risk score (0-100).** On-chain tells that the buy we are about to copy is
   bait: concentrated or evenly split supply, a bundled whale buy, a whale with fast-dump
   strikes, the edge already mostly consumed, a whale buy that moved a thin pool, a token too
   young to have a real market, and (optional, fail-open) RugCheck danger flags. A score at or
   above `max_exit_liquidity_risk` is a hard veto.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from .config import ShieldConfig
from .http_utils import request_json

log = logging.getLogger(__name__)

RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary"


def net_expected_value(edge: float, drift: float, exit_cost: float, tip_frac: float,
                       slippage_reserve: float) -> float:
    """Expected net return of copying, after every friction a follower pays."""
    return (1.0 + edge) / (1.0 + max(drift, -0.5)) * (1.0 - exit_cost) - 1.0 - tip_frac - slippage_reserve


@dataclass
class RiskSignals:
    holder_top5_pct: float | None = None
    holder_max_pct: float | None = None
    identical_holders: int = 0
    bundled_whale_buy: bool = False
    whale_hunter_strikes: int = 0
    edge_consumed: float | None = None  # fraction of the wallet's edge eaten by drift + costs
    whale_buy_pool_frac: float | None = None  # whale buy as a fraction of pool liquidity
    token_age_hours: float | None = None
    rugcheck_normalised: int | None = None
    rugcheck_dangers: list[str] = field(default_factory=list)


def exit_liquidity_risk(sig: RiskSignals, cfg: ShieldConfig) -> tuple[int, list[str]]:
    """Composite 0-100 score with the reasons that produced it. Weights are additive and
    deliberately simple, so every veto can be explained from the evidence ledger."""
    score, why = 0, []

    def add(points: int, reason: str) -> None:
        nonlocal score
        score += points
        why.append(f"+{points} {reason}")

    if sig.holder_top5_pct is not None and sig.holder_top5_pct > 0.25:
        add(25 if sig.holder_top5_pct > 0.35 else 10, f"top-5 holders own {sig.holder_top5_pct:.0%}")
    if sig.holder_max_pct is not None and sig.holder_max_pct > 0.08:
        add(25 if sig.holder_max_pct > 0.12 else 10, f"largest holder owns {sig.holder_max_pct:.0%}")
    if sig.identical_holders >= 3:
        add(15 if sig.identical_holders < 4 else 30, f"{sig.identical_holders} near-identical top bags")
    if sig.bundled_whale_buy:
        add(40, "whale's buy tx also funded other wallets")
    if sig.whale_hunter_strikes:
        add(20 * min(sig.whale_hunter_strikes, 2), f"whale has {sig.whale_hunter_strikes} fast-dump strike(s)")
    if sig.edge_consumed is not None and sig.edge_consumed > 0.4:
        add(15 if sig.edge_consumed < 0.65 else 30, f"{sig.edge_consumed:.0%} of the wallet's edge already consumed")
    if sig.whale_buy_pool_frac is not None and sig.whale_buy_pool_frac > 0.02:
        add(15, f"whale buy was {sig.whale_buy_pool_frac:.1%} of the pool (we buy after its impact)")
    if sig.token_age_hours is not None and sig.token_age_hours < 1.0:
        add(15, f"token is {sig.token_age_hours * 60:.0f} min old")
    if sig.rugcheck_dangers:
        add(30, "RugCheck danger: " + ", ".join(sig.rugcheck_dangers[:3]))
    elif sig.rugcheck_normalised is not None and sig.rugcheck_normalised >= cfg.rugcheck_max_normalised:
        add(20, f"RugCheck risk {sig.rugcheck_normalised}/100")
    return min(score, 100), why


@dataclass
class KillSwitchVerdict:
    veto: bool
    net_ev: float | None
    risk: int
    reasons: list[str]


def kill_switch(sig: RiskSignals, cfg: ShieldConfig, *, edge: float | None, drift: float, exit_cost: float,
                tip_frac: float) -> KillSwitchVerdict:
    reasons: list[str] = []
    ev = None
    if edge is not None and edge > 0:
        ev = net_expected_value(edge, drift, exit_cost, tip_frac, cfg.slippage_reserve_pct)
        if ev <= cfg.min_net_ev:
            reasons.append(
                f"negative copy EV {ev:+.1%}: edge {edge:.0%} vs drift {drift:+.1%}, exit cost {exit_cost:.1%}, "
                f"tips {tip_frac:.2%}, slippage {cfg.slippage_reserve_pct:.1%}"
            )
    risk, why = exit_liquidity_risk(sig, cfg)
    if risk >= cfg.max_exit_liquidity_risk:
        reasons.append(f"EXIT-LIQUIDITY RISK {risk}/100 (" + "; ".join(why) + ")")
    return KillSwitchVerdict(bool(reasons), ev, risk, reasons)


async def rugcheck_summary(client: httpx.AsyncClient, mint: str, timeout: float) -> tuple[int | None, list[str]]:
    """(normalised risk 0-100, names of 'danger'-level risks). Fails open: (None, [])."""
    try:
        data = await request_json(client, "GET", RUGCHECK.format(mint=mint), timeout=timeout, retries=0)
    except Exception as exc:
        log.debug("rugcheck unavailable for %s: %s", mint[:8], exc)
        return None, []
    dangers = [r.get("name", "?") for r in data.get("risks") or [] if r.get("level") == "danger"]
    norm = data.get("score_normalised")
    return (int(norm) if isinstance(norm, (int, float)) else None), dangers
