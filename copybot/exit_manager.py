"""Module C — independent exit engine.

We never wait for the whale to finish selling. Every open position is re-evaluated against
five triggers; whichever fires first wins:

  1. Whale exit      — the copied wallet sold >= 30% of its peak holding  -> sell 100%
  2. Hard stop       — net value <= -22% (or <= +2% break-even after scale-out) -> sell 100%
  3. Trailing stop   — once peak >= +25%, a 15% drop from the peak       -> sell 100%
  4. Scale-out       — net value >= +45% the first time                   -> sell 50%, stop -> +2%
  5. Time decay      — 45 min without ever reaching +15%                  -> sell 100%
  (+ an absolute max-hold cap, and an emergency exit if the sell route disappears)

"Value" is always what we would really receive: a Jupiter SELL quote for our exact token
amount, i.e. net of DEX fees and price impact — not the chart price. Between quote refreshes
we mark positions with one batched DexScreener call and only spend a Jupiter quote when the
mark suggests a trigger may have fired.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .config import ExitConfig
from .constants import LAMPORTS_PER_SOL, WSOL_MINT
from .dexscreener import DexScreenerClient, pick_best_pair
from .jupiter import JupiterClient, NoRouteError
from .state import Position, PositionStatus

if TYPE_CHECKING:
    from .copy_engine import CopyEngine

log = logging.getLogger(__name__)


class Action(str, Enum):
    HOLD = "HOLD"
    SELL = "SELL"


@dataclass(frozen=True)
class ExitDecision:
    action: Action
    fraction: float = 0.0
    reason: str = ""


HOLD = ExitDecision(Action.HOLD)


def decide_exit(pos: Position, ratio: float | None, now: float, cfg: ExitConfig) -> ExitDecision:
    """Pure function: given the position and its current net value ratio (value / cost basis
    of the remaining tokens), return what to do. `ratio=None` means no price is available.
    `pos.peak_ratio` must already include `ratio`."""
    if pos.whale_sold_frac >= cfg.whale_sell_trigger_frac:
        return ExitDecision(Action.SELL, 1.0, f"whale sold {pos.whale_sold_frac:.0%} of its bag")

    age_min = (now - pos.opened_at) / 60.0
    if ratio is not None:
        if ratio <= pos.stop_ratio:
            kind = "break-even stop" if pos.scaled_out else "hard stop"
            return ExitDecision(Action.SELL, 1.0, f"{kind} at {ratio - 1:+.1%}")
        if pos.peak_ratio >= 1 + cfg.trailing_activation_profit and ratio <= pos.peak_ratio * (1 - cfg.trailing_stop_pct):
            return ExitDecision(
                Action.SELL, 1.0, f"trailing stop: {ratio - 1:+.1%} from peak {pos.peak_ratio - 1:+.1%}"
            )
        if not pos.scaled_out and ratio >= 1 + cfg.scale_out_profit:
            return ExitDecision(Action.SELL, cfg.scale_out_fraction, f"scale-out at {ratio - 1:+.1%}")

    if age_min >= cfg.time_decay_minutes and pos.peak_ratio < 1 + cfg.time_decay_min_profit:
        return ExitDecision(Action.SELL, 1.0, f"time decay: {age_min:.0f}min, peak {pos.peak_ratio - 1:+.1%}")
    if age_min >= cfg.max_hold_minutes:
        return ExitDecision(Action.SELL, 1.0, f"max hold {cfg.max_hold_minutes:.0f}min reached")
    return HOLD


def apply_partial_exit(pos: Position, cfg: ExitConfig) -> None:
    """State change after a scale-out fill: lock in break-even on the remainder."""
    pos.scaled_out = True
    pos.stop_ratio = max(pos.stop_ratio, 1 + cfg.breakeven_stop_profit)


class ExitManager:
    def __init__(
        self,
        cfg: ExitConfig,
        engine: "CopyEngine",
        jupiter: JupiterClient,
        dex: DexScreenerClient,
    ) -> None:
        self.cfg = cfg
        self.engine = engine
        self.jupiter = jupiter
        self.dex = dex
        self._locks: dict[str, asyncio.Lock] = {}
        self._marks: dict[str, float] = {}

    def _lock(self, pos_id: str) -> asyncio.Lock:
        return self._locks.setdefault(pos_id, asyncio.Lock())

    async def quote_ratio(self, pos: Position) -> float | None:
        """Executable net value ratio for the remaining tokens. None if no route."""
        if pos.token_raw <= 0 or pos.cost_basis_lamports <= 0:
            return None
        try:
            q = await self.jupiter.quote(pos.mint, WSOL_MINT, pos.token_raw, self.cfg.exit_slippage_bps, retries=1)
        except NoRouteError:
            if pos.no_route_since is None:
                pos.no_route_since = time.time()
            return None
        except Exception as exc:  # rate limit / network: no price this tick, but not a rug signal
            log.debug("sell quote for %s unavailable: %s", pos.mint[:8], exc)
            return None
        pos.no_route_since = None
        est_exit_fee = self.engine.estimated_exit_fee_lamports()
        return (q.out_amount - est_exit_fee) / pos.cost_basis_lamports

    def mark_ratio(self, pos: Position) -> float | None:
        mark = self._marks.get(pos.mint)
        if not mark or not pos.mark_calibration:
            return None
        return mark * pos.mark_calibration

    def calibrate(self, pos: Position, ratio: float) -> None:
        mark = self._marks.get(pos.mint)
        if mark:
            pos.mark_calibration = ratio / mark

    async def refresh_marks(self, positions: list[Position]) -> None:
        mints = sorted({p.mint for p in positions})
        if not mints:
            return
        try:
            pairs = await self.dex.pairs_for_tokens(mints)
        except Exception as exc:
            log.debug("mark refresh failed: %s", exc)
            return
        for mint, plist in pairs.items():
            # Any quote token works (some memes pair with WBTC/USDC, not SOL): the mark is only
            # a cheap relative signal, re-calibrated against a real SOL sell quote every refresh,
            # and it can only trigger a confirming quote — never a sell by itself.
            best = pick_best_pair(plist)
            if best and best.price_native > 0:
                self._marks[mint] = best.price_native

    async def evaluate(self, pos: Position, *, force_quote: bool = False) -> None:
        async with self._lock(pos.id):
            if pos.token_raw <= 0 or pos.status is not PositionStatus.OPEN:
                return
            now = time.time()

            # Whale exit needs no price: act immediately.
            if pos.whale_sold_frac >= self.cfg.whale_sell_trigger_frac:
                await self._execute(pos, decide_exit(pos, None, now, self.cfg))
                return

            est = self.mark_ratio(pos)
            need_quote = force_quote or now - pos.last_quote_ts >= self.cfg.quote_refresh_s
            if not need_quote and est is not None:
                probe = pos.model_copy()
                probe.peak_ratio = max(pos.peak_ratio, est)
                # Mark says a trigger may have fired, or a new high: confirm with a real quote.
                need_quote = decide_exit(probe, est, now, self.cfg).action is Action.SELL or est > pos.peak_ratio * 1.03
            if not need_quote:
                if decide_exit(pos, None, now, self.cfg).action is Action.SELL:
                    need_quote = True  # time-based trigger: get a real price for the fill
                else:
                    return

            ratio = await self.quote_ratio(pos)
            pos.last_quote_ts = now
            if ratio is None:
                if pos.no_route_since and now - pos.no_route_since >= self.cfg.no_route_emergency_s:
                    await self._execute(pos, ExitDecision(Action.SELL, 1.0, "EMERGENCY: sell route vanished (rug?)"), emergency=True)
                else:
                    decision = decide_exit(pos, None, now, self.cfg)
                    if decision.action is Action.SELL:
                        await self._execute(pos, decision)
                return

            pos.last_ratio = ratio
            pos.peak_ratio = max(pos.peak_ratio, ratio)
            self.calibrate(pos, ratio)
            decision = decide_exit(pos, ratio, now, self.cfg)
            if decision.action is Action.SELL:
                await self._execute(pos, decision)
            else:
                self.engine.store.save()

    async def _execute(self, pos: Position, decision: ExitDecision, *, emergency: bool = False) -> None:
        log.info("EXIT %s %s: sell %.0f%% — %s", pos.symbol or pos.mint[:8], pos.id, decision.fraction * 100, decision.reason)
        await self.engine.close_or_reduce(pos, decision.fraction, decision.reason, emergency=emergency)

    async def run(self) -> None:
        """Main loop: mark all positions with one DexScreener call per tick, quote selectively."""
        while True:
            try:
                positions = self.engine.store.state.open_positions()
                if positions:
                    await self.refresh_marks(positions)
                    results = await asyncio.gather(*(self.evaluate(p) for p in positions), return_exceptions=True)
                    for p, r in zip(positions, results):
                        if isinstance(r, Exception):
                            log.error("evaluating %s failed: %r", p.mint[:8], r)
                    self.engine.check_breaker()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("exit loop error")
            await asyncio.sleep(self.cfg.poll_interval_s)


def describe(pos: Position) -> str:
    return (
        f"{pos.symbol or pos.mint[:8]} value {pos.last_ratio - 1:+.1%} peak {pos.peak_ratio - 1:+.1%} "
        f"cost {pos.cost_basis_lamports / LAMPORTS_PER_SOL:.4f} SOL age {pos.age_minutes:.0f}m "
        f"whale sold {pos.whale_sold_frac:.0%}{' [scaled]' if pos.scaled_out else ''}"
    )
