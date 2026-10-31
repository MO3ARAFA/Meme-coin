"""NautilusTrader strategy that reuses the live bot's own decision code.

  entry : `copybot.momentum.detect_momentum`   (same breakout rules, run on OHLCV samples)
  exits : `copybot.exit_manager.decide_exit`   (same stop / trail / scale-out / moonbag / timers)
  chase : `SafetyConfig.max_chase_pct`         (entry is cancelled if price ran past the signal)

So a backtest here exercises the production logic, not a lookalike. Honest differences:

  * OHLCV candles carry no buy/sell counts or pool liquidity, so those two checks are skipped by
    the detector (it is built to). `min_volume_spike` stands in for buy pressure: the last
    window's volume must exceed the previous baseline by that multiple. It is a proxy.
  * There is no safety gate here (no honeypot / holder / mint checks). A backtest cannot tell you
    whether a token was a trap; the live path still runs the full gate.

Execution timing (the part backtests most often get wrong): Nautilus fills a market order at the
last price it has when the order is sent, i.e. the CLOSE of the candle that triggered it. That is
zero latency and flatters every strategy. So decisions are made on a closed candle but the order is
sent `delay_bars` candles later (default 1 = one minute, pessimistic for a bot that lands in
seconds) and fills at that later candle's close. `delay_bars=0` gives the optimistic zero-latency
number; compare the two to see how latency-sensitive an edge is. Both legs pay `leg_cost`.
"""

from __future__ import annotations

import math
from collections import deque

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from copybot.config import ExitConfig, MomentumConfig, SafetyConfig
from copybot.constants import MOMENTUM_SOURCE
from copybot.exit_manager import Action, apply_partial_exit, decide_exit
from copybot.momentum import Sample, detect_momentum
from copybot.state import Position


class MemeMomentumConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    size_frac: float = 0.05  # share of free USD per entry (mirrors MOMENTUM__SIZE_FRAC)
    leg_cost: float = 0.012  # taker fee per leg; also the cost the exit ratio is net of
    delay_bars: int = (
        1  # candles between decision and order; 0 = optimistic zero latency
    )
    min_volume_spike: float = 1.5  # proxy for buy pressure; 0 disables
    volume_baseline_bars: int = 60
    momentum: dict[str, float] = {}  # overrides for copybot.config.MomentumConfig
    exits: dict[str, float] = {}  # overrides for copybot.config.ExitConfig
    max_chase_pct: float = SafetyConfig().max_chase_pct  # same default as the live gate


class MemeMomentumStrategy(Strategy):
    def __init__(self, config: MemeMomentumConfig) -> None:
        super().__init__(config)
        self.mcfg = MomentumConfig(**config.momentum)
        self.xcfg = ExitConfig(**config.exits)
        self.samples: deque[Sample] = deque(maxlen=max(self.mcfg.history_len, 120))
        self.volumes: deque[float] = deque(maxlen=config.volume_baseline_bars + 6)
        self.pos: Position | None = None
        self.cooldown_until = 0.0
        self._bar_idx = 0
        self._scheduled: list[tuple[int, str, dict]] = (
            []
        )  # (due bar index, kind, payload)
        self._entry_pending = False  # entry decided, scheduled or part-filled
        self._exit_pending = False
        self._pending_reason = ""
        self._signal = None
        self.trade_log: list[dict] = []
        self.signals_seen = 0
        self.chase_aborts = 0

    # ---- lifecycle -------------------------------------------------------------------------
    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.subscribe_bars(self.config.bar_type)

    def on_stop(self) -> None:
        self.close_all_positions(self.config.instrument_id)

    # ---- decision loop (one call per closed candle) ----------------------------------------
    def on_bar(self, bar: Bar) -> None:
        self._bar_idx += 1
        now, price = bar.ts_event / 1e9, float(bar.close)
        self.samples.append(Sample(ts=now, price_native=price))
        self.volumes.append(float(bar.volume))
        self._run_due(price)
        if self.pos is not None:
            if not self._entry_pending:
                self._manage(price, now)
        elif not self._entry_pending and now >= self.cooldown_until:
            self._maybe_enter(price, now)

    def _volume_ok(self) -> bool:
        spike = self.config.min_volume_spike
        if spike <= 0:
            return True
        n = max(1, int(self.mcfg.window_s // 60))
        if len(self.volumes) < n + 10:
            return False
        recent = sum(list(self.volumes)[-n:]) / n
        base = sorted(list(self.volumes)[:-n])
        median = base[len(base) // 2]
        return median > 0 and recent >= spike * median

    # ---- scheduling (models decision -> order latency) ---------------------------------------
    def _schedule(self, kind: str, payload: dict, price: float) -> None:
        if self.config.delay_bars <= 0:
            self._send(kind, payload, price)
        else:
            self._scheduled.append(
                (self._bar_idx + self.config.delay_bars, kind, payload)
            )

    def _run_due(self, price: float) -> None:
        due = [s for s in self._scheduled if s[0] <= self._bar_idx]
        self._scheduled = [s for s in self._scheduled if s[0] > self._bar_idx]
        for _, kind, payload in due:
            self._send(kind, payload, price)

    def _send(self, kind: str, payload: dict, price: float) -> None:
        """Submit now; Nautilus fills at `price`, the close of the current candle."""
        leg = self.config.leg_cost
        if kind == "buy":
            if price > payload["signal_price"] * (1 + self.config.max_chase_pct):
                # The live gate's anti-chase rule: the market ran away while we were deciding.
                self.chase_aborts += 1
                self._entry_pending = False
                return
            usd = self.portfolio.account(self.config.instrument_id.venue).balance_free(
                self.instrument.quote_currency
            )
            qty = min(payload["qty"], math.floor(usd.as_double() / (price * (1 + leg))))
            if qty <= 0:
                self._entry_pending = False
                return
            order = self.order_factory.market(
                self.config.instrument_id, OrderSide.BUY, self.instrument.make_qty(qty)
            )
        else:
            order = self.order_factory.market(
                self.config.instrument_id,
                OrderSide.SELL,
                self.instrument.make_qty(payload["qty"]),
                reduce_only=True,
            )
        self.submit_order(order)

    def _maybe_enter(self, price: float, now: float) -> None:
        verdict = detect_momentum(
            self.config.instrument_id.symbol.value,
            "",
            list(self.samples),
            self.mcfg,
            now,
        )
        if verdict.signal is None or not self._volume_ok():
            return
        self.signals_seen += 1
        self.cooldown_until = now + self.mcfg.cooldown_s
        usd = self.portfolio.account(self.config.instrument_id.venue).balance_free(
            self.instrument.quote_currency
        )
        qty = math.floor(
            usd.as_double()
            * self.config.size_frac
            / (price * (1 + self.config.leg_cost))
        )
        if qty <= 0:
            return
        self._entry_pending = True
        self._signal = verdict.signal
        self._schedule("buy", {"qty": qty, "signal_price": price}, price)

    def _manage(self, price: float, now: float) -> None:
        pos = self.pos
        if pos is None or self._exit_pending:
            return
        leg = self.config.leg_cost
        ratio = (
            price * (1 - leg) / (pos.entry_price * (1 + leg))
        )  # net value / cost, like the live exit engine
        pos.last_ratio = ratio
        pos.peak_ratio = max(pos.peak_ratio, ratio)
        decision = decide_exit(pos, ratio, now, self.xcfg)
        if decision.action is not Action.SELL:
            return
        qty = (
            pos.token_raw
            if decision.fraction >= 1.0
            else max(1, math.floor(pos.token_raw * decision.fraction))
        )
        self._exit_pending = True
        self._pending_reason = decision.reason
        if decision.fraction < 1.0:
            apply_partial_exit(
                pos, self.xcfg
            )  # runner gets the moonbag floor + wide trail, as live
        self._schedule("sell", {"qty": qty}, price)

    # ---- fills ------------------------------------------------------------------------------
    # A market order can fill in several pieces (Nautilus caps a fill by the candle's traded
    # volume, which is also how a real pool behaves for size). Accumulate until the order closes.
    def on_order_filled(self, event: OrderFilled) -> None:
        px, qty, ts = float(event.last_px), int(event.last_qty), event.ts_event / 1e9
        order = self.cache.order(event.client_order_id)
        done = order is None or order.is_closed
        if event.order_side is OrderSide.BUY:
            self._on_buy_fill(px, qty, ts, done)
        else:
            self._on_sell_fill(px, qty, ts, done)

    def _on_buy_fill(self, px: float, qty: int, ts: float, done: bool) -> None:
        pos = self.pos
        if pos is None:
            pos = self.pos = Position(
                mint=self.config.instrument_id.symbol.value,
                whale=MOMENTUM_SOURCE,
                signal_signature="backtest",
                opened_at=ts,
                initial_token_raw=0,
                token_raw=0,
                initial_cost_lamports=0,
                cost_basis_lamports=0,
                entry_price=px,
                whale_price=px,
                stop_ratio=1 - self.xcfg.hard_stop_loss,
            )
            self.trade_log.append(
                {
                    "opened": ts,
                    "window_return": self._signal.window_return,
                    "qty": 0,
                    "fill_usd": 0.0,
                    "exits": [],
                }
            )
        entry = self.trade_log[-1]
        entry["qty"] += qty
        entry["fill_usd"] += px * qty
        pos.token_raw = pos.initial_token_raw = entry["qty"]
        pos.entry_price = (
            entry["fill_usd"] / entry["qty"]
        )  # volume-weighted across the pieces
        entry["entry_px"] = pos.entry_price
        if done:
            self._entry_pending = False

    def _on_sell_fill(self, px: float, qty: int, ts: float, done: bool) -> None:
        pos = self.pos
        if pos is None:
            return
        pos.token_raw -= qty
        self.trade_log[-1]["exits"].append(
            {"ts": ts, "px": px, "qty": qty, "reason": self._pending_reason}
        )
        if done:
            self._exit_pending = False
        if pos.token_raw <= 0:
            self.trade_log[-1]["closed"] = ts
            self.pos = None
            self._exit_pending = False
