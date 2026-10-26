"""Pillar 3 — autonomous CFO: full accounting, meritocracy sizing, high-water-mark profit lock.

* **Ledger** (`data/treasury_ledger.json`, live: `live_treasury_ledger.json`): every lamport in
  (sell proceeds, rent refunds) and out (buy cost, rent), with friction broken down into Solana
  network fees (base + priority/Jito, as paid) and DEX fees + price impact (estimated per leg
  from the live Jupiter round trip at entry), plus realized PnL per whale.
* **Meritocracy sizing**: a whale that earned it (PF >= 1.5 over >= 3 copied trades) gets 12%
  of equity; one that just lost twice in a row is on probation at 5% until it wins again;
  everyone else gets the base 10%.
* **High-water-mark lock**: each time equity grows +20% over the last lock point, 50% of that
  gain moves into a reserve floor. The risk manager never spends below the floor, so a hot
  streak's profits cannot be given back by the next cold one.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from pydantic import BaseModel, Field

from .config import TreasuryConfig
from .constants import LAMPORTS_PER_SOL


class WhaleBook(BaseModel):
    trades: int = 0
    wins: int = 0
    losses: int = 0
    consecutive_losses: int = 0
    gross_win_lamports: int = 0
    gross_loss_lamports: int = 0
    realized_lamports: int = 0
    demoted: bool = False  # set by the self-improver (probation until the whale wins again)

    @property
    def profit_factor(self) -> float:
        if self.gross_loss_lamports == 0:
            return 99.0 if self.gross_win_lamports > 0 else 0.0
        return self.gross_win_lamports / self.gross_loss_lamports


class TreasuryState(BaseModel):
    mode: str = "SHADOW_PAPER"
    created_at: float = Field(default_factory=time.time)
    inflow_lamports: int = 0  # sell proceeds received (net of network fees)
    outflow_lamports: int = 0  # buy cost paid (incl. network fees)
    network_fees_lamports: int = 0  # base + priority + Jito tips, as paid
    dex_friction_lamports: int = 0  # DEX fees + impact, estimated per leg
    rent_locked_lamports: int = 0
    realized_pnl_lamports: int = 0
    trades_closed: int = 0
    hwm_anchor_lamports: int = 0  # equity at the last lock point
    peak_equity_lamports: int = 0
    locked_reserve_lamports: int = 0
    lock_events: list[dict] = Field(default_factory=list)
    whales: dict[str, WhaleBook] = Field(default_factory=dict)


class TreasuryCFO:
    def __init__(self, cfg: TreasuryConfig, path: Path, mode: str = "SHADOW_PAPER") -> None:
        self.cfg = cfg
        self.path = path
        self.state = TreasuryState.model_validate_json(path.read_text()) if path.exists() else TreasuryState(mode=mode)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(self.state.model_dump_json(indent=2))
        os.replace(tmp, self.path)

    def book(self, whale: str) -> WhaleBook:
        return self.state.whales.setdefault(whale, WhaleBook())

    # ---- sizing ------------------------------------------------------------------------
    def size_frac(self, whale: str) -> tuple[float, str]:
        b = self.state.whales.get(whale)
        if b is None:
            return self.cfg.base_size_frac, "base"
        if b.demoted or b.consecutive_losses >= self.cfg.probation_losses:
            return self.cfg.probation_size_frac, "probation"
        if b.trades >= self.cfg.merit_min_trades and b.profit_factor >= self.cfg.merit_profit_factor:
            return self.cfg.merit_size_frac, "merit"
        return self.cfg.base_size_frac, "base"

    # ---- accounting --------------------------------------------------------------------
    def record_entry(self, cost_lamports: int, fees_lamports: int, rent_lamports: int, dex_leg_cost_frac: float) -> None:
        s = self.state
        s.outflow_lamports += cost_lamports
        s.network_fees_lamports += fees_lamports
        s.rent_locked_lamports += rent_lamports
        s.dex_friction_lamports += int((cost_lamports - fees_lamports) * max(dex_leg_cost_frac, 0.0))

    def record_exit(self, whale: str, proceeds_lamports: int, fees_lamports: int, rent_refund_lamports: int,
                    dex_leg_cost_frac: float, closed_pnl_lamports: int | None) -> None:
        """`closed_pnl_lamports` is set when the position is fully closed (one trade outcome)."""
        s = self.state
        s.inflow_lamports += proceeds_lamports
        s.network_fees_lamports += fees_lamports
        s.rent_locked_lamports = max(0, s.rent_locked_lamports - rent_refund_lamports)
        s.dex_friction_lamports += int(proceeds_lamports * max(dex_leg_cost_frac, 0.0))
        if closed_pnl_lamports is None:
            return
        s.trades_closed += 1
        s.realized_pnl_lamports += closed_pnl_lamports
        b = self.book(whale)
        b.trades += 1
        b.realized_lamports += closed_pnl_lamports
        if closed_pnl_lamports > 0:
            b.wins += 1
            b.consecutive_losses = 0
            b.gross_win_lamports += closed_pnl_lamports
            b.demoted = False  # a win ends probation
        else:
            b.losses += 1
            b.consecutive_losses += 1
            b.gross_loss_lamports += -closed_pnl_lamports

    # ---- high-water-mark profit lock ---------------------------------------------------
    def update_hwm(self, equity_lamports: int) -> int:
        """Lock gains at each +hwm_step of equity. Returns lamports newly locked."""
        s = self.state
        if s.hwm_anchor_lamports <= 0:
            s.hwm_anchor_lamports = equity_lamports
        s.peak_equity_lamports = max(s.peak_equity_lamports, equity_lamports)
        locked_now = 0
        while equity_lamports >= s.hwm_anchor_lamports * (1 + self.cfg.hwm_step):
            step_top = int(s.hwm_anchor_lamports * (1 + self.cfg.hwm_step))
            gain = step_top - s.hwm_anchor_lamports
            lock = int(gain * self.cfg.lock_fraction)
            s.locked_reserve_lamports += lock
            locked_now += lock
            s.lock_events.append({"ts": int(time.time()), "anchor": s.hwm_anchor_lamports, "equity": equity_lamports,
                                  "locked": lock, "reserve": s.locked_reserve_lamports})
            s.hwm_anchor_lamports = step_top
        return locked_now

    # ---- statement ---------------------------------------------------------------------
    def statement(self, equity_lamports: int | None = None) -> str:
        s = self.state

        def sol(v: int) -> str:
            return f"{v / LAMPORTS_PER_SOL:+.4f} SOL" if v else " 0.0000 SOL"

        friction = s.network_fees_lamports + s.dex_friction_lamports
        lines = [
            f"=== CFO statement ({s.mode}) ===",
            f"inflow (sell proceeds)       {sol(s.inflow_lamports)}",
            f"outflow (buy cost)           {sol(-s.outflow_lamports)}",
            f"network fees (base+prio+tip) {sol(-s.network_fees_lamports)}",
            f"DEX fees + impact (est.)     {sol(-s.dex_friction_lamports)}",
            f"total friction               {sol(-friction)}",
            f"rent locked (refundable)     {sol(s.rent_locked_lamports)}",
            f"net realized PnL             {sol(s.realized_pnl_lamports)}  over {s.trades_closed} closed trades",
            f"high-water-mark anchor       {s.hwm_anchor_lamports / LAMPORTS_PER_SOL:.4f} SOL "
            f"(peak {s.peak_equity_lamports / LAMPORTS_PER_SOL:.4f})",
            f"LOCKED RESERVE (never risked) {s.locked_reserve_lamports / LAMPORTS_PER_SOL:.4f} SOL "
            f"after {len(s.lock_events)} lock event(s)",
        ]
        if equity_lamports is not None:
            lines.append(f"current equity               {equity_lamports / LAMPORTS_PER_SOL:.4f} SOL")
        if s.whales:
            lines.append("per-whale meritocracy:")
            for w, b in sorted(s.whales.items(), key=lambda kv: -kv[1].realized_lamports):
                frac, tier = self.size_frac(w)
                lines.append(f"  {w[:8]}…  n={b.trades:<3} W/L={b.wins}/{b.losses} PF={b.profit_factor:5.2f} "
                             f"pnl={b.realized_lamports / LAMPORTS_PER_SOL:+.4f} -> size {frac:.0%} ({tier})")
        return "\n".join(lines)
