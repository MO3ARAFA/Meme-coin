"""Module A: cycle reconstruction and the copyability filters."""

import time

from copybot.config import ScorerConfig
from copybot.constants import WSOL_MINT
from copybot.tx_parser import Side, SwapEvent
from copybot.wallet_scorer import build_cycles, compute_metrics

SOL = 1_000_000_000
NOW = time.time()
CFG = ScorerConfig()


def ev(t, side, mint, sol, tokens, before, after):
    return (t, t, "swap", SwapEvent(
        signature=f"{mint}{t}", slot=t, block_time=t, wallet="W", side=side, mint=mint, token_amount_raw=tokens,
        decimals=6, quote_mint=WSOL_MINT, quote_amount_raw=int(sol * SOL), token_balance_before_raw=before,
        token_balance_after_raw=after, fee_lamports=5000,
    ))


def trader(n, roi_fn, hold_s, start=None, size=1.0):
    """n round trips: buy `size` SOL, sell all after hold_s for size*(1+roi)."""
    start = start or int(NOW - 3 * 86400)
    events = []
    for i in range(n):
        t = start + i * 3600
        mint = f"Mint{i:03d}"
        roi = roi_fn(i)
        events.append(ev(t, Side.BUY, mint, size, 1000, 0, 1000))
        events.append(ev(t + hold_s, Side.SELL, mint, size * (1 + roi), 1000, 1000, 0))
    return events


def metrics(events, created=None, history_days=20.0, txs=200):
    events.sort(key=lambda e: (e[0], e[1]))
    return compute_metrics("W", build_cycles(events, 100.0), txs_scanned=txs, history_days=history_days,
                           token_created_ms=created or {}, cfg=CFG, now=NOW)


def good_roi(i):  # 70% winners at +40%, losers at -20%
    return 0.40 if i % 10 < 7 else -0.20


def test_real_swing_trader_passes():
    m = metrics(trader(30, good_roi, hold_s=1200))
    assert m.passed, m.rejections
    assert m.closed_trades == 30 and abs(m.win_rate - 0.7) < 1e-9
    assert abs(m.median_roi - 0.40) < 1e-9 and m.score > 0


def test_copy_trader_farmer_flipping_under_2min_is_blacklisted():
    m = metrics(trader(30, good_roi, hold_s=45))
    assert not m.passed
    assert any("BLACKLIST" in r for r in m.rejections)


def test_win_rate_above_82pct_is_rejected_as_unreplicable():
    m = metrics(trader(30, lambda i: 0.3 if i % 20 != 0 else -0.1, hold_s=900))  # 95% win rate
    assert any("not replicable" in r for r in m.rejections)


def test_lottery_gambler_rejected_by_median_roi_and_concentration():
    m = metrics(trader(30, lambda i: 50.0 if i == 0 else -0.5 if i % 3 == 0 else 0.05, hold_s=900))
    assert m.mean_roi > 1.0  # the mean looks amazing...
    assert not m.passed  # ...the median exposes it
    assert any("median ROI" in r for r in m.rejections)


def test_block0_sniper_rejected():
    events = trader(30, good_roi, hold_s=1200)
    created = {e[3].mint: (e[0] - 1) * 1000 for e in events if e[3].side is Side.BUY}  # bought 1s after launch
    m = metrics(events, created=created)
    assert any("sniper" in r for r in m.rejections)


def test_too_few_trades_and_inactivity():
    m = metrics(trader(10, good_roi, hold_s=1200, start=int(NOW - 25 * 86400)))
    assert any("closed trades" in r for r in m.rejections)
    assert any("inactive" in r for r in m.rejections)


def test_scaling_in_and_out_forms_one_cycle_and_presale_bags_are_excluded():
    t = int(NOW - 86400)
    events = [
        ev(t, Side.BUY, "A", 1.0, 1000, 0, 1000),
        ev(t + 60, Side.BUY, "A", 1.0, 1000, 1000, 2000),
        ev(t + 600, Side.SELL, "A", 1.5, 1000, 2000, 1000),
        ev(t + 900, Side.SELL, "A", 1.5, 990, 1000, 10),  # dust left -> closed
        ev(t, Side.SELL, "B", 1.0, 500, 500, 0),  # bag bought before the window: ignored
        ev(t + 5, Side.BUY, "C", 1.0, 100, 900, 1000),  # already held a bag -> contaminated
        ev(t + 50, Side.SELL, "C", 2.0, 1000, 1000, 0),
    ]
    cycles = {c.mint: c for c in build_cycles(sorted(events, key=lambda e: e[0]), 100.0)}
    a = cycles["A"]
    assert a.outcome == "sold" and a.buys == 2 and a.sells == 2
    assert abs(a.roi - 0.5) < 1e-9 and a.hold_s == 900 and a.first_sell_delay_s == 600
    assert "B" not in cycles
    assert cycles["C"].outcome == "contaminated"


def test_insider_moving_tokens_to_other_wallets_is_rejected():
    events = trader(30, good_roi, hold_s=1200)
    t = int(NOW - 2 * 86400)
    for i in range(12):
        mint = f"X{i}"
        events.append(ev(t + i * 100, Side.BUY, mint, 1.0, 1000, 0, 1000))
        events.append((t + i * 100 + 30, t + i * 100 + 30, "xfer", (mint, 1000, 0)))
    m = metrics(events)
    assert any("transfers to other wallets" in r for r in m.rejections)
