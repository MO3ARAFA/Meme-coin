"""Shadow-trade performance report and the LIVE-readiness gate.

The mandate's "50+ profitable shadow trades" is a weak criterion: 50 small wins and 10
large losses is a losing system. LIVE is unlocked only when the shadow journal shows a real
statistical edge after all fees: enough trades, profit factor, expectancy, and drawdown.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from .config import LiveGateConfig


@dataclass
class Report:
    trades: int = 0
    wins: int = 0
    total_pnl_sol: float = 0.0
    expectancy_pct: float = 0.0
    median_return_pct: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_hold_min: float = 0.0
    by_reason: dict[str, tuple[int, float]] = field(default_factory=dict)
    by_whale: dict[str, tuple[int, float]] = field(default_factory=dict)
    gate_failures: list[str] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def live_ready(self) -> bool:
        return not self.gate_failures


def _reason_bucket(reason: str) -> str:
    r = reason.lower()
    for key in ("whale", "break-even", "hard stop", "trailing", "time decay", "max hold", "write-off", "emergency"):
        if key in r:
            return key
    return reason[:20] or "?"


def build_report(rows: list[dict], starting_sol: float, gate: LiveGateConfig) -> Report:
    closed = [r for r in rows if r.get("event") == "EXIT" and r.get("position_net_pnl_sol")]
    rep = Report(trades=len(closed))
    pnls = [float(r["position_net_pnl_sol"]) for r in closed]
    rets = [float(r["position_net_return_pct"]) / 100 for r in closed]
    if closed:
        rep.wins = sum(1 for p in pnls if p > 0)
        rep.total_pnl_sol = sum(pnls)
        rep.expectancy_pct = statistics.fmean(rets)
        rep.median_return_pct = statistics.median(rets)
        gw, gl = sum(p for p in pnls if p > 0), -sum(p for p in pnls if p < 0)
        rep.profit_factor = gw / gl if gl > 0 else (99.0 if gw > 0 else 0.0)
        equity, peak, mdd = starting_sol, starting_sol, 0.0
        for p in pnls:
            equity += p
            peak = max(peak, equity)
            mdd = max(mdd, (peak - equity) / peak if peak > 0 else 0.0)
        rep.max_drawdown_pct = mdd
        rep.avg_hold_min = statistics.fmean(float(r.get("hold_minutes") or 0) for r in closed)
        reasons: dict[str, list[float]] = defaultdict(list)
        whales: dict[str, list[float]] = defaultdict(list)
        for r, p in zip(closed, pnls):
            reasons[_reason_bucket(r.get("reason", ""))].append(p)
            whales[r.get("whale", "?")].append(p)
        rep.by_reason = {k: (len(v), sum(v)) for k, v in reasons.items()}
        rep.by_whale = {k: (len(v), sum(v)) for k, v in whales.items()}

    if rep.trades < gate.min_shadow_trades:
        rep.gate_failures.append(f"{rep.trades} closed shadow trades < {gate.min_shadow_trades}")
    if rep.profit_factor < gate.min_profit_factor:
        rep.gate_failures.append(f"profit factor {rep.profit_factor:.2f} < {gate.min_profit_factor}")
    if rep.expectancy_pct < gate.min_expectancy_pct:
        rep.gate_failures.append(f"expectancy {rep.expectancy_pct:+.2%}/trade < {gate.min_expectancy_pct:+.2%}")
    if rep.max_drawdown_pct > gate.max_drawdown_pct:
        rep.gate_failures.append(f"max drawdown {rep.max_drawdown_pct:.1%} > {gate.max_drawdown_pct:.0%}")
    return rep


def format_report(rep: Report) -> str:
    lines = [
        "=== Shadow performance (net of fees, impact, latency haircut) ===",
        f"closed trades     {rep.trades}",
        f"win rate          {rep.win_rate:.1%}",
        f"total PnL         {rep.total_pnl_sol:+.4f} SOL",
        f"expectancy        {rep.expectancy_pct:+.2%} per trade (median {rep.median_return_pct:+.2%})",
        f"profit factor     {rep.profit_factor:.2f}",
        f"max drawdown      {rep.max_drawdown_pct:.1%}",
        f"avg hold          {rep.avg_hold_min:.0f} min",
    ]
    if rep.by_reason:
        lines.append("exits by trigger:")
        lines += [f"  {k:<12} n={n:<4} pnl={p:+.4f} SOL" for k, (n, p) in sorted(rep.by_reason.items())]
    if rep.by_whale:
        lines.append("by copied wallet:")
        lines += [f"  {k[:8]}…  n={n:<4} pnl={p:+.4f} SOL" for k, (n, p) in sorted(rep.by_whale.items(), key=lambda x: -x[1][1])]
    lines.append("LIVE readiness: " + ("READY ✅" if rep.live_ready else "NOT READY ❌"))
    lines += [f"  - {f}" for f in rep.gate_failures]
    return "\n".join(lines)
