"""Run MemeMomentumStrategy on candles with NautilusTrader's BacktestEngine and summarise it with
the same yardsticks the bot's LIVE-readiness gate uses (`copybot.config.LiveGateConfig`).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, CurrencyType, OmsType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Currency, Money, Price, Quantity
from nautilus_trader.persistence.wranglers import BarDataWrangler

from copybot.config import LiveGateConfig

from .data import to_nautilus_frame
from .strategy import MemeMomentumConfig, MemeMomentumStrategy

VENUE = Venue("DEX")


@dataclass
class Trade:
    symbol: str
    opened: pd.Timestamp
    closed: pd.Timestamp
    ret: float  # net of both legs' fees, on the entry notional
    pnl: float  # USD
    exits: list[str] = field(default_factory=list)
    features: dict = field(default_factory=dict)  # market state at the signal


@dataclass
class Result:
    symbol: str
    candles: int
    signals: int
    trades: list[Trade]
    still_open: int = 0
    chase_aborts: int = 0  # entries cancelled by the anti-chase rule after the delay
    trade_log: list[dict] = field(
        default_factory=list
    )  # raw strategy log, for debugging
    account_pnl: float = (
        0.0  # USD balance change per the account; must equal sum(trade.pnl)
    )


def _currency_code(symbol: str) -> str:
    clean = re.sub(r"[^A-Z0-9]", "", symbol.upper())[:8] or "TOKEN"
    return f"T{clean}"  # prefix: a token called "USD" or "SOL" must never shadow a real currency


def build_instrument(symbol: str, min_price: float, leg_cost: float) -> CurrencyPair:
    digits = min(
        15, max(8, math.ceil(-math.log10(min_price)) + 4)
    )  # memecoins trade at 1e-6 and below
    code = _currency_code(symbol)
    base = Currency(
        code=code, precision=0, iso4217=0, name=code, currency_type=CurrencyType.CRYPTO
    )
    return CurrencyPair(
        instrument_id=InstrumentId(Symbol(f"{code}-USD"), VENUE),
        raw_symbol=Symbol(f"{code}-USD"),
        base_currency=base,
        quote_currency=USD,
        price_precision=digits,
        size_precision=0,
        price_increment=Price(10.0**-digits, digits),
        size_increment=Quantity(1, 0),
        ts_event=0,
        ts_init=0,
        maker_fee=Decimal(str(leg_cost)),
        taker_fee=Decimal(str(leg_cost)),
    )


def run_backtest(
    candles: pd.DataFrame,
    symbol: str,
    *,
    capital: float = 1000.0,
    leg_cost: float = 0.012,
    size_frac: float = 0.05,
    min_volume_spike: float = 1.5,
    delay_bars: int = 1,
    momentum: dict[str, float] | None = None,
    exits: dict[str, float] | None = None,
) -> Result:
    """`candles`: 1-minute USD OHLCV indexed by candle OPEN time (see data.py)."""
    frame = to_nautilus_frame(candles)  # close-time stamps: no look-ahead
    inst = build_instrument(symbol, float(candles["low"].min()), leg_cost)
    bar_type = BarType.from_str(f"{inst.id}-1-MINUTE-LAST-EXTERNAL")
    bars = BarDataWrangler(bar_type, inst).process(frame)

    engine = BacktestEngine(
        BacktestEngineConfig(
            logging=LoggingConfig(log_level="ERROR", bypass_logging=True)
        )
    )
    try:
        engine.add_venue(
            venue=VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=None,
            starting_balances=[Money(capital, USD)],
        )
        engine.add_instrument(inst)
        engine.add_data(bars)
        strategy = MemeMomentumStrategy(
            MemeMomentumConfig(
                instrument_id=inst.id,
                bar_type=bar_type,
                size_frac=size_frac,
                leg_cost=leg_cost,
                min_volume_spike=min_volume_spike,
                delay_bars=delay_bars,
                momentum=momentum or {},
                exits=exits or {},
            )
        )
        engine.add_strategy(strategy)
        engine.run()
        # NETTING closes a cycle by snapshotting the position, so closed cycles live in
        # `position_snapshots()` and only the latest in `positions()`.
        cycles = [
            p
            for p in [*engine.cache.position_snapshots(), *engine.cache.positions()]
            if p.is_closed
        ]
        cycles.sort(key=lambda p: p.ts_opened)
        trades: list[Trade] = []
        for p, log in zip(cycles, strategy.trade_log):
            notional = float(p.avg_px_open) * float(p.peak_qty)
            pnl = p.realized_pnl.as_double()
            trades.append(
                Trade(
                    symbol,
                    pd.Timestamp(p.ts_opened, unit="ns", tz="UTC"),
                    pd.Timestamp(p.ts_closed, unit="ns", tz="UTC"),
                    pnl / notional if notional else 0.0,
                    pnl,
                    [e["reason"] for e in log["exits"]],
                    log.get("features", {}),
                )
            )
        account = engine.cache.accounts()[0]
        return Result(
            symbol=symbol,
            candles=len(candles),
            signals=strategy.signals_seen,
            trades=trades,
            still_open=len(engine.cache.positions_open()),
            trade_log=strategy.trade_log,
            account_pnl=account.balance_total(USD).as_double() - capital,
            chase_aborts=strategy.chase_aborts,
        )
    finally:
        engine.dispose()


# ---- summary --------------------------------------------------------------------------------
@dataclass
class Summary:
    trades: int
    win_rate: float
    profit_factor: float
    expectancy: float  # mean net return per trade
    avg_win: float
    avg_loss: float
    total_return: float  # on starting capital, closed trades only
    max_drawdown: float
    verdict: list[str]  # per LiveGateConfig criterion: PASS/FAIL lines

    @property
    def passes_gate(self) -> bool:
        return all(v.startswith("PASS") for v in self.verdict)


def summarize(
    trades: list[Trade], capital: float, gate: LiveGateConfig | None = None
) -> Summary:
    gate = gate or LiveGateConfig()
    ordered = sorted(trades, key=lambda t: t.closed)
    wins = [t for t in ordered if t.pnl > 0]
    losses = [t for t in ordered if t.pnl <= 0]
    gross_win, gross_loss = sum(t.pnl for t in wins), -sum(t.pnl for t in losses)
    pf = (
        gross_win / gross_loss
        if gross_loss > 0
        else (math.inf if gross_win > 0 else 0.0)
    )
    equity, peak, mdd = capital, capital, 0.0
    for t in ordered:
        equity += t.pnl
        peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak)
    n = len(ordered)
    exp = sum(t.ret for t in ordered) / n if n else 0.0
    s = Summary(
        n,
        len(wins) / n if n else 0.0,
        pf,
        exp,
        sum(t.ret for t in wins) / len(wins) if wins else 0.0,
        sum(t.ret for t in losses) / len(losses) if losses else 0.0,
        (equity - capital) / capital,
        mdd,
        [],
    )
    s.verdict = [
        f"{'PASS' if n >= gate.min_shadow_trades else 'FAIL'} trades {n} (need >= {gate.min_shadow_trades})",
        f"{'PASS' if pf >= gate.min_profit_factor else 'FAIL'} profit factor {pf:.2f} (need >= {gate.min_profit_factor})",
        f"{'PASS' if exp >= gate.min_expectancy_pct else 'FAIL'} expectancy {exp:+.2%}/trade (need >= {gate.min_expectancy_pct:+.0%})",
        f"{'PASS' if mdd <= gate.max_drawdown_pct else 'FAIL'} max drawdown {mdd:.1%} (need <= {gate.max_drawdown_pct:.0%})",
    ]
    return s
