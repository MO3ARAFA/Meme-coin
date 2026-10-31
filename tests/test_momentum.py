"""Momentum signal source: the pure detector, the scanner loop, and the full shadow path
(signal -> same safety gate -> same sizing -> paper fill -> same exit engine)."""

import time

import pytest

from copybot.config import MomentumConfig, Settings
from copybot.constants import LAMPORTS_PER_SOL, MOMENTUM_SOURCE, WSOL_MINT
from copybot.dexscreener import PairInfo
from copybot.momentum import (
    MomentumScanner,
    MomentumSignal,
    Sample,
    detect_momentum,
    eligible_pair,
)
from copybot.state import PositionStatus

from .helpers import MEME, SOL
from .test_engine_shadow import (
    FakeMarket,
    FakeRpc,
    engine,
)  # noqa: F401  (pytest fixture)

CFG = MomentumConfig()
NOW = 1_800_000_000.0


def series(prices, *, step=30.0, buys=40, sells=10, liq=80_000.0, end=NOW):
    """Samples ending at `end`, `step` seconds apart, one per price."""
    t0 = end - step * (len(prices) - 1)
    return [Sample(t0 + i * step, p, buys, sells, liq) for i, p in enumerate(prices)]


def verdict(samples, cfg=CFG):
    return detect_momentum("MINT", "MEME", samples, cfg, NOW)


# ---- pure detector -------------------------------------------------------------------------
def test_clean_breakout_fires():
    v = verdict(series([1.00, 1.01, 1.03, 1.04, 1.06, 1.08, 1.09, 1.11, 1.12, 1.14]))
    assert v.signal is not None and not v.reasons
    assert v.signal.window_return == pytest.approx(0.14)
    assert v.signal.price_native == 1.14 and v.signal.buy_ratio == pytest.approx(0.8)


def test_flat_market_does_not_fire():
    v = verdict(series([1.0, 1.001, 0.999, 1.0, 1.002, 1.0, 1.001, 1.0, 1.0, 1.001]))
    assert v.signal is None and any("return" in r for r in v.reasons)


def test_vertical_candle_is_refused_as_chasing_the_top():
    v = verdict(series([1.0, 1.1, 1.25, 1.4, 1.6, 1.75, 1.85, 1.9, 1.95, 2.0]))
    assert v.signal is None and any("vertical" in r for r in v.reasons)


def test_single_spike_is_not_a_trend():
    v = verdict(series([1.0] * 9 + [1.12]))
    assert v.signal is None and any("one spike" in r for r in v.reasons)


def test_already_fading_from_the_high_is_refused():
    v = verdict(series([1.0, 1.04, 1.08, 1.12, 1.16, 1.2, 1.18, 1.16, 1.14, 1.12]))
    assert v.signal is None and any("fading" in r for r in v.reasons)


def test_sell_pressure_blocks_the_signal():
    v = verdict(
        series(
            [1.0, 1.02, 1.04, 1.06, 1.08, 1.1, 1.12, 1.13, 1.14, 1.15],
            buys=30,
            sells=40,
        )
    )
    assert v.signal is None and any("buy ratio" in r for r in v.reasons)


def test_thin_liquidity_blocks_the_signal():
    v = verdict(
        series([1.0, 1.02, 1.04, 1.06, 1.08, 1.1, 1.12, 1.13, 1.14, 1.15], liq=10_000)
    )
    assert v.signal is None and any("liquidity" in r for r in v.reasons)


def test_warming_up_and_short_span_never_fire():
    assert "warming up" in verdict(series([1.0, 1.1, 1.2]), CFG).reasons[0]
    short = verdict(series([1.0, 1.02, 1.04, 1.06, 1.08, 1.1, 1.12], step=5.0))
    assert short.signal is None and "span" in short.reasons[0]


def test_old_samples_outside_the_window_are_ignored():
    stale = series([1.0, 1.1, 1.2, 1.3, 1.4, 1.5], step=30.0, end=NOW - 1000)
    assert "warming up" in verdict(stale).reasons[0]


# ---- eligibility -----------------------------------------------------------------------------
def pair(
    *,
    age_h=48.0,
    quote=WSOL_MINT,
    dex="pumpswap",
    liq=80_000.0,
    price=0.5,
    created=True,
):
    ms = int((NOW - age_h * 3600) * 1000) if created else None
    return PairInfo(
        "p",
        dex,
        "MINT",
        "MEME",
        quote,
        price,
        price * 100,
        liq,
        400_000,
        400_000,
        ms,
        10_000,
        (40, 10),
    )


def test_eligible_pair_rules():
    assert eligible_pair([pair()], CFG, NOW) is not None
    assert (
        eligible_pair([pair(age_h=1.0)], CFG, NOW) is None
    )  # a fresh launch is sniping, not momentum
    assert eligible_pair([pair(age_h=15 * 24)], CFG, NOW) is None
    assert (
        eligible_pair(
            [pair(quote="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")], CFG, NOW
        )
        is None
    )
    assert (
        eligible_pair([pair(dex="pumpfun", liq=None)], CFG, NOW) is None
    )  # bonding curve
    assert eligible_pair([pair(created=False)], CFG, NOW) is None


# ---- scanner ---------------------------------------------------------------------------------
class RisingDex:
    """Each poll the token is 1.2% higher; buy pressure healthy."""

    def __init__(self):
        self.calls = 0

    async def pairs_for_tokens(self, mints, **_):
        price = 0.5 * 1.012**self.calls
        self.calls += 1
        return {m: [pair(price=price)] for m in mints}


async def test_scanner_fires_once_then_respects_cooldown():
    s = Settings(_env_file=None)
    got: list[MomentumSignal] = []

    async def on_signal(sig):
        got.append(sig)

    async def discover():
        return ["MINT"]

    scanner = MomentumScanner(s, None, RisingDex(), on_signal, discover)
    for i in range(40):  # 40 polls, 20 s apart
        await scanner.scan_once(now=NOW + i * 20.0)
    assert (
        len(got) == 1
    )  # the cooldown stops a still-rising token from re-firing every poll
    assert got[0].mint == "MINT" and got[0].window_return >= CFG.min_return


async def test_scanner_survives_a_failing_handler():
    async def boom(sig):
        raise RuntimeError("handler exploded")

    async def discover():
        return ["MINT"]

    scanner = MomentumScanner(
        Settings(_env_file=None), None, RisingDex(), boom, discover
    )
    for i in range(30):
        await scanner.scan_once(now=NOW + i * 20.0)  # must not raise
    assert scanner.cooldown_until["MINT"] > 0


async def test_empty_discovery_keeps_the_previous_universe():
    calls = iter([["MINT"], []])

    async def discover():
        return next(calls)

    scanner = MomentumScanner(
        Settings(_env_file=None), None, RisingDex(), lambda s: None, discover
    )
    await scanner.refresh_universe(NOW)
    await scanner.refresh_universe(NOW + 1)
    assert scanner.universe == ["MINT"]


# ---- full shadow path through the real engine -------------------------------------------------
def signal(
    mint=MEME, price_native=0.5
):  # FakeMarket: 500 lamports/raw, 6 decimals => 0.5 SOL per UI token
    return MomentumSignal(
        mint, "FAKE", time.time(), price_native, 0.14, 0.8, 0.0, 40, 0.8, 80_000
    )


async def test_momentum_entry_uses_the_same_gate_sizing_and_exit_engine(
    engine,
):  # noqa: F811
    eng, market = engine, engine.market
    await eng.handle_momentum(signal())
    [pos] = eng.store.state.open_positions()
    assert pos.whale == MOMENTUM_SOURCE and pos.size_tier == "momentum"
    # 5% of 1 SOL (momentum has no track record: half the base copy size) + base fee + capped priority
    assert pos.initial_cost_lamports == pytest.approx(0.05 * SOL + 105_000, rel=1e-6)
    assert pos.whale_sold_frac == 0.0  # no whale behind it

    market.price *= 0.70  # -30%: the ordinary hard stop closes it
    await eng.exits.evaluate(pos, force_quote=True)
    assert pos.status is PositionStatus.CLOSED and "hard stop" in pos.close_reason
    assert [r["event"] for r in eng.journal.read()] == ["ENTRY", "EXIT"]


async def test_momentum_runs_the_gate_and_aborts_when_price_ran_past_the_signal(
    engine,
):  # noqa: F811
    eng, market = engine, engine.market
    market.price *= (
        1.30  # +30% since the breakout was detected: we would be the exit liquidity
    )
    await eng.handle_momentum(signal())
    assert not eng.store.state.open_positions()


async def test_momentum_cannot_bypass_the_honeypot_check(engine):  # noqa: F811
    eng, market = engine, engine.market
    market.routable = False
    await eng.handle_momentum(signal())
    assert not eng.store.state.open_positions()


async def test_only_max_open_momentum_positions(engine):  # noqa: F811
    eng = engine
    await eng.handle_momentum(
        signal(mint="MintAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    )
    await eng.handle_momentum(
        signal(mint="MintBbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    )
    assert len(eng.store.state.open_positions()) == eng.s.momentum.max_open == 1


async def test_whale_buy_size_floor_does_not_apply_to_momentum_but_still_applies_to_whales(
    engine,
):  # noqa: F811
    from copybot.tx_parser import Side, SwapEvent

    eng = engine
    tiny = dict(
        signature="x",
        slot=0,
        block_time=int(time.time()),
        side=Side.BUY,
        mint=MEME,
        token_amount_raw=10**6,
        decimals=6,
        quote_mint=WSOL_MINT,
        quote_amount_raw=int(0.05 * LAMPORTS_PER_SOL),
        token_balance_before_raw=0,
        token_balance_after_raw=10**6,
        fee_lamports=0,
    )
    assert any(
        "too small" in r
        for r in eng.gate.precheck(SwapEvent(wallet="somewhale", **tiny))
    )
    assert not any(
        "too small" in r
        for r in eng.gate.precheck(SwapEvent(wallet=MOMENTUM_SOURCE, **tiny))
    )


# ---- OHLCV-only samples (nautilus_lab) ---------------------------------------------------------
def test_price_only_samples_skip_flow_and_liquidity_checks_instead_of_faking_them():
    samples = [Sample(s.ts, s.price_native) for s in series([1.00, 1.01, 1.03, 1.04, 1.06, 1.08, 1.09, 1.11, 1.12, 1.14])]
    v = verdict(samples)
    assert v.signal is not None and v.signal.buys_m5 is None and v.signal.buy_ratio is None
    assert "buys5m" not in v.signal.summary() and "liq" not in v.signal.summary()
    # ...but the price rules still bite
    assert verdict([Sample(s.ts, s.price_native) for s in series([1.0] * 10)]).signal is None
