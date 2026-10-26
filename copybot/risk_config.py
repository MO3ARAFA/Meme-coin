"""Module D — $100 micro-capital sizing, per-leg fee guard and the daily circuit breaker.

Why the fee guard matters at this size: a $10 position pays the same ~5,000-lamport base
fee and similar priority fees as a $10,000 one. Without a cap, landing fees + DEX fees +
price impact eat the edge. We budget the *whole* leg cost (DEX fee + impact + network fee)
at <= 1.2% of notional and give the priority fee only what is left of that budget.

Rent: opening a token account locks ~0.002 SOL (~4% of a 0.05 SOL position!). It is not a
fee — it is refunded when the account is closed after the exit — so it is tracked as locked
capital, and LIVE mode closes the account after every full exit.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from .config import RiskConfig
from .constants import BASE_FEE_LAMPORTS, LAMPORTS_PER_SOL
from .state import BotState, utc_day

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SizingDecision:
    allowed: bool
    lamports: int = 0
    reason: str = ""


@dataclass(frozen=True)
class FeeBudget:
    allowed: bool
    max_priority_lamports: int = 0
    dex_cost_frac: float = 0.0
    reason: str = ""


def per_leg_cost_from_roundtrip(roundtrip_return: float) -> float:
    """Round trip (buy quote -> sell quote) loses fees+impact twice; one leg is ~ the sqrt."""
    roundtrip_return = min(max(roundtrip_return, 1e-9), 1.0)
    return 1.0 - math.sqrt(roundtrip_return)


class RiskManager:
    def __init__(self, cfg: RiskConfig, state: BotState) -> None:
        self.cfg = cfg
        self.state = state

    # ---- sizing ---------------------------------------------------------------------------
    def equity_lamports(self, free_lamports: int) -> int:
        locked = sum(p.cost_basis_lamports + p.rent_lamports for p in self.state.open_positions())
        return free_lamports + locked

    def size_position(self, free_lamports: int) -> SizingDecision:
        if self.is_halted():
            left = (self.state.halted_until - time.time()) / 3600
            return SizingDecision(False, reason=f"circuit breaker active ({left:.1f}h left)")
        if len(self.state.open_positions()) >= self.cfg.max_open_positions:
            return SizingDecision(False, reason=f"max {self.cfg.max_open_positions} open positions")
        equity = self.equity_lamports(free_lamports)
        size = int(equity * self.cfg.position_size_frac)
        reserve = int(self.cfg.sol_reserve * LAMPORTS_PER_SOL)
        spendable = free_lamports - reserve
        if spendable <= 0:
            return SizingDecision(False, reason="free balance below SOL reserve")
        size = min(size, spendable)
        if size < 0.005 * LAMPORTS_PER_SOL:
            return SizingDecision(False, reason="position size below 0.005 SOL")
        return SizingDecision(True, lamports=size)

    # ---- fee guard -----------------------------------------------------------------------
    def fee_budget(self, notional_lamports: int, dex_cost_frac: float) -> FeeBudget:
        """Priority fee (or Jito tip) we may pay so that the leg costs <= max_leg_cost_pct."""
        budget = notional_lamports * self.cfg.max_leg_cost_pct
        remaining = budget - notional_lamports * dex_cost_frac - BASE_FEE_LAMPORTS
        if remaining < self.cfg.min_priority_fee_lamports:
            return FeeBudget(
                False,
                dex_cost_frac=dex_cost_frac,
                reason=(
                    f"leg cost too high: DEX fee+impact {dex_cost_frac:.2%} leaves "
                    f"{max(remaining, 0) / LAMPORTS_PER_SOL:.6f} SOL for priority (cap "
                    f"{self.cfg.max_leg_cost_pct:.1%} of {notional_lamports / LAMPORTS_PER_SOL:.4f} SOL)"
                ),
            )
        return FeeBudget(
            True,
            max_priority_lamports=int(min(remaining, self.cfg.max_priority_fee_lamports)),
            dex_cost_frac=dex_cost_frac,
        )

    # ---- circuit breaker -----------------------------------------------------------------
    def is_halted(self) -> bool:
        return time.time() < self.state.halted_until

    def roll_day(self, equity_lamports: int) -> None:
        today = utc_day()
        if self.state.daily.day != today:
            self.state.daily.day = today
            self.state.daily.start_equity_lamports = equity_lamports
            self.state.daily.realized_pnl_lamports = 0

    def record_realized(self, pnl_lamports: int) -> None:
        self.state.daily.realized_pnl_lamports += pnl_lamports

    def check_circuit_breaker(self, unrealized_pnl_lamports: int = 0) -> bool:
        """Trip the breaker if today's realized + unrealized PnL <= -daily_loss_limit. Returns True if tripped."""
        start = self.state.daily.start_equity_lamports
        if start <= 0 or self.is_halted():
            return False
        pnl = self.state.daily.realized_pnl_lamports + unrealized_pnl_lamports
        if pnl <= -self.cfg.daily_loss_limit_frac * start:
            self.state.halted_until = time.time() + self.cfg.halt_hours * 3600
            log.warning(
                "CIRCUIT BREAKER: daily PnL %.4f SOL (%.1f%%) — copying halted for %.0fh",
                pnl / LAMPORTS_PER_SOL,
                100 * pnl / start,
                self.cfg.halt_hours,
            )
            return True
        return False
