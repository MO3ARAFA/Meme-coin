"""nautilus_lab: data hygiene, execution timing (no look-ahead / latency / anti-chase), exit parity
with the live bot, and accounting. Skipped when nautilus_trader (an optional extra) is absent."""

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
pytest.importorskip("nautilus_trader")

from nautilus_lab import cli  # noqa: E402
from nautilus_lab.backtest import Trade, run_backtest, summarize  # noqa: E402
from nautilus_lab.data import BAR_SECONDS, clean, fill_gaps, synthetic_ohlcv, to_nautilus_frame  # noqa: E402

P0 = 1e-5


def candles(closes, vols=None, start="2025-03-01"):
    closes = np.array(closes, float)
    opens = np.r_[closes[0], closes[:-1]]
    idx = pd.date_range(start, periods=len(closes), freq=f"{BAR_SECONDS}s", tz="UTC")
    vols = np.full(len(closes), 100.0) if vols is None else np.array(vols, float)
    return pd.DataFrame(
        {"open": opens, "high": np.maximum(opens, closes) * 1.001, "low": np.minimum(opens, closes) * 0.999,
         "close": closes, "volume": vols},
        index=idx,
    )


def breakout(next_bar=1.0, tail=None):
    """120 flat minutes, 4 rising +2% bars (the signal fires on the 4th), then `next_bar` gap, then `tail`."""
    closes = [P0] * 120 + [P0 * 1.02**i for i in range(1, 5)]
    signal_close = closes[-1]
    closes += [signal_close * next_bar]
    closes += tail if tail is not None else [closes[-1] * 1.002**i for i in range(1, 6)]
    vols = [100.0] * 120 + [600.0] * (len(closes) - 120)  # volume spike = the buy-pressure proxy
    return candles(closes, vols), signal_close


# ---- data hygiene ----------------------------------------------------------------------------
def test_fill_gaps_inserts_flat_zero_volume_candles():
    df = candles([1.0, 1.1, 1.2, 1.3, 1.4, 1.5]).iloc[[0, 1, 5]]
    out = fill_gaps(df)
    assert len(out) == 6
    gap = out.iloc[2:5]
    assert (gap["volume"] == 0).all() and (gap["close"] == 1.1).all()
    assert (gap["open"] == gap["high"]).all() and (gap["high"] == gap["low"]).all()


def test_clean_repairs_ohlc_and_drops_bad_rows():
    df = candles([1.0, 1.1, 1.2, 1.3])
    df.iloc[1, df.columns.get_loc("high")] = 0.5  # high below close: impossible, repaired
    df.iloc[2, df.columns.get_loc("close")] = 0.0  # zero price: row dropped, hole re-filled flat
    out = clean(df)
    assert len(out) == 4
    assert out["high"].iloc[1] >= out["close"].iloc[1]
    assert out["close"].iloc[2] == 1.1 and out["volume"].iloc[2] == 0.0
    assert (out[["open", "high", "low", "close"]] > 0).all().all()
    assert len(clean(df.iloc[:3])) == 2  # a bad LAST row is not extrapolated past real data


def test_nautilus_frame_uses_close_time_and_token_volumes():
    df = candles([2.0, 4.0], vols=[100.0, 100.0])
    out = to_nautilus_frame(df)
    assert out.index[0] == df.index[0] + pd.Timedelta(f"{BAR_SECONDS}s")  # stamped at CLOSE, not open
    assert out["volume"].tolist() == [50.0, 25.0]  # USD volume / price = token count
    assert df["volume"].tolist() == [100.0, 100.0]  # input untouched


# ---- execution timing -------------------------------------------------------------------------
def test_zero_latency_fills_at_the_signal_close_and_one_bar_pays_the_next_price():
    df, sig = breakout(next_bar=1.05)
    optimistic = run_backtest(df, "T", delay_bars=0)
    delayed = run_backtest(df, "T", delay_bars=1)
    assert optimistic.trade_log[0]["entry_px"] == pytest.approx(sig, rel=1e-4)
    assert delayed.trade_log[0]["entry_px"] == pytest.approx(sig * 1.05, rel=1e-4)


def test_entry_is_cancelled_when_price_ran_past_the_signal_during_the_delay():
    df, _ = breakout(next_bar=1.20)  # +20% > SafetyConfig.max_chase_pct (12%): the live gate would abort too
    delayed = run_backtest(df, "T", delay_bars=1)
    assert delayed.signals == 1 and not delayed.trade_log and delayed.chase_aborts == 1
    assert run_backtest(df, "T", delay_bars=0).trade_log  # without latency there is nothing to chase


# ---- exit parity with the live bot ------------------------------------------------------------
def test_hard_stop_comes_from_the_real_exit_engine():
    df, _ = breakout(tail=[P0 * 0.5] * 6)  # collapse right after entry
    r = run_backtest(df, "T", delay_bars=0)
    [t] = r.trades
    assert any(e.startswith("hard stop") for e in t.exits) and t.pnl < 0


def test_scale_out_then_trailing_stop_like_live():
    up = [P0 * 1.02**4 * 1.04**i for i in range(1, 16)]  # steady climb: scale-out at +45%
    down = [up[-1] * 0.93**i for i in range(1, 12)]  # then a slide: the runner's wide trail fires
    df, _ = breakout(tail=up + down)
    [t] = run_backtest(df, "T", delay_bars=0).trades
    assert any(e.startswith("scale-out") for e in t.exits)
    assert any(e.startswith("trailing stop") or e.startswith("moonbag floor") for e in t.exits)


# ---- accounting -------------------------------------------------------------------------------
def test_trade_pnl_reconciles_with_the_account_balance():
    r = run_backtest(synthetic_ohlcv(seed=7), "SYNTH")
    assert len(r.trades) >= 2 and r.still_open == 0
    assert sum(t.pnl for t in r.trades) == pytest.approx(r.account_pnl, abs=0.05 * len(r.trades))
    assert len(r.trade_log) == len(r.trades)  # one log entry per closed position (partial fills merged)


def test_summarize_matches_hand_computation():
    ts = pd.Timestamp("2025-01-01", tz="UTC")
    mk = lambda i, pnl: Trade("T", ts + pd.Timedelta(hours=i), ts + pd.Timedelta(hours=i, minutes=30), pnl / 50, pnl)  # noqa: E731
    s = summarize([mk(0, 30.0), mk(1, -10.0), mk(2, -20.0), mk(3, 40.0)], capital=1000.0)
    assert s.trades == 4 and s.win_rate == 0.5
    assert s.profit_factor == pytest.approx(70 / 30)
    assert s.expectancy == pytest.approx((0.6 - 0.2 - 0.4 + 0.8) / 4)
    assert s.total_return == pytest.approx(0.04)
    assert s.max_drawdown == pytest.approx(30 / 1030)  # peak 1030 -> trough 1000
    assert s.verdict[0].startswith("FAIL trades 4") and not s.passes_gate


# ---- CLI ----------------------------------------------------------------------------------------
def test_cli_rejects_unknown_momentum_parameter():
    with pytest.raises(SystemExit, match="unknown momentum parameter"):
        cli.main(["backtest", "--synthetic", "--momentum", "bogus=1"])


def test_cli_synthetic_run_prints_the_honesty_banner(capsys):
    assert cli.main(["backtest", "--synthetic"]) == 0
    out = capsys.readouterr().out
    assert "SYNTHETIC data" in out and "LIVE-readiness yardsticks" in out
    assert "robustness" in out and "bootstrap:" in out
