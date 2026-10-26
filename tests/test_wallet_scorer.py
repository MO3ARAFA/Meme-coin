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
    m = metrics(trader(30, lambda i: 19.0 if i == 0 else -0.5 if i % 3 == 0 else 0.05, hold_s=900))
    assert m.mean_roi > 0.4  # the mean looks great...
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


def test_vault_funded_buys_are_unpriced_not_lottery_wins():
    """A trading-bot vault pays for the buy, so the wallet's SOL barely moves; the sell then
    looks like a 100,000x. Seen live on mainnet (Oct 2026)."""
    events = trader(30, good_roi, hold_s=1200)
    t = int(NOW - 86400)
    for i in range(12):
        mint = f"V{i}"
        events.append(ev(t + i * 100, Side.BUY, mint, 0.0002, 1000, 0, 1000))
        events.append(ev(t + i * 100 + 900, Side.SELL, mint, 26.0, 1000, 1000, 0))
    m = metrics(events)
    assert m.closed_trades == 30  # the 12 vault cycles don't pollute ROI stats
    assert m.mean_roi < 1.0
    assert any("off-wallet" in r for r in m.rejections)


# ---- scratch-aware ROI + latency-adjusted replay -----------------------------------
def scratcher_roi(i):
    """FSTqRd92-like pro: half the trades scratched near 0%, winners run, losers cut."""
    k = i % 10
    return 0.01 if k < 5 else (0.60 if k < 8 else -0.15)


def test_scratching_pro_passes_on_non_scratch_median_and_replay():
    m = metrics(trader(40, scratcher_roi, hold_s=900))
    assert abs(m.median_roi) < 0.05  # the plain median would have rejected this trader
    assert m.nonscratch_median_roi >= 0.15
    assert m.replay_trades == 38  # 40 copied, top 5% (2) trimmed
    assert m.replay_profit_factor >= 1.35 and m.replay_expectancy > 0
    assert m.passed, m.rejections


def test_thin_scalper_edge_dies_under_copy_latency():
    # +4% winners / -3% losers at 65% win rate: PF ~2.5 for the whale, but after a 2.5% entry
    # penalty and 1.2%/leg fees every winner becomes a loser for the copier.
    m = metrics(trader(40, lambda i: 0.20 if i % 20 < 13 else -0.03, hold_s=900))
    assert m.profit_factor > 2.0
    m2 = metrics(trader(40, lambda i: 0.04 if i % 20 < 13 else -0.03, hold_s=900))
    assert any("copy latency" in r for r in m2.rejections)
    assert m2.replay_expectancy < 0


def test_replay_skips_buys_the_live_gate_would_never_copy():
    events = trader(30, good_roi, hold_s=1200, size=2.0)
    t = int(NOW - 3600 * 5)
    for i in range(10):  # tiny bait-sized trades that "win" big
        events.append(ev(t + i, Side.BUY, f"B{i}", 0.2, 10, 0, 10))
        events.append(ev(t + i + 600, Side.SELL, f"B{i}", 1.0, 10, 10, 0))
    m = metrics(events)
    assert m.median_buy_sol == 2.0
    assert m.replay_trades == 29  # 30 real buys, top 5% trimmed; the 0.2 SOL bait-sized buys excluded


# ---- sybil links -------------------------------------------------------------------
def test_linked_wallets_are_one_operator_and_only_the_best_is_approved():
    from copybot.wallet_scorer import WalletMetrics, select_approved

    def fresh():
        return (WalletMetrics("A", passed=True, score=80, counterparties=["B"]),
                WalletMetrics("B", passed=True, score=70), WalletMetrics("C", passed=True, score=60))

    a, b, c = fresh()
    approved = select_approved([a, b, c], top_n=5, quarantined=set())
    assert [m.address for m in approved] == ["A", "C"]
    assert a.link_group == b.link_group != c.link_group
    assert any("same operator" in r for r in b.rejections)
    # A quarantined as a hunter: its linked sibling B is the same operator and is barred too
    assert [m.address for m in select_approved(list(fresh()), 5, quarantined={"A"})] == ["C"]


def test_counterparty_extraction_from_parsed_instructions():
    from copybot.wallet_scorer import sol_counterparties

    tx = {"transaction": {"message": {"instructions": [
        {"program": "system", "parsed": {"type": "transfer", "info": {"source": "W", "destination": "X", "lamports": 10**8}}},
        {"program": "system", "parsed": {"type": "transfer", "info": {"source": "Y", "destination": "W", "lamports": 10**3}}},
    ]}}, "meta": {"innerInstructions": [{"instructions": [
        {"program": "system", "parsed": {"type": "transfer", "info": {"source": "Z", "destination": "W", "lamports": 10**9}}}]}]}}
    assert sol_counterparties(tx, "W", 5 * 10**7) == {"X", "Z"}  # Y below the link threshold


def test_moonbag_replay_captures_long_runners_but_lottery_wallets_still_fail():
    # A gambler: 30 small trades, mostly losers, closed within 4h, plus 3 huge winners held 17h.
    events = trader(30, lambda i: 0.02 if i % 3 == 0 else -0.05, hold_s=1800)
    t = int(NOW - 3600 * 30)
    for i in range(3):
        events.append(ev(t + i, Side.BUY, f"L{i}", 1.0, 10, 0, 10))
        events.append(ev(t + i + 17 * 3600, Side.SELL, f"L{i}", 15.0, 10, 10, 0))
    m = metrics(events)
    assert m.replay_trades == 32  # the 17h runners ARE replayed now (moonbag); top 5% (1) trimmed
    assert not m.passed
    assert any("win rate" in r for r in m.rejections)  # power-law luck on a losing base is not skill


def test_moonbag_model_halves_at_scale_out_and_floors_losses():
    from copybot.wallet_scorer import Cycle, moonbag_return

    def cyc(roi, hold_h, buy_sol=0.5):
        c = Cycle(mint="M", opened_at=0, sol_in=buy_sol * SOL, sol_out=buy_sol * SOL * (1 + roi), first_buy_sol=buy_sol * SOL)
        c.closed_at = int(hold_h * 3600)
        return c

    big = moonbag_return(cyc(14.0, 17), CFG)  # 15x held 17 h
    assert 6.5 < big < 7.5  # half sold at +45%, half rode the copy-adjusted ~13.9x
    assert moonbag_return(cyc(0.30, 17), CFG) is None  # unscaled long hold: our timer -> unknowable
    assert moonbag_return(cyc(-0.80, 2), CFG) == CFG.replay_loss_floor  # stop fired near -22%
    assert moonbag_return(cyc(-0.80, 30), CFG) == CFG.replay_loss_floor  # big losers count even if held long
    small, large = moonbag_return(cyc(0.20, 1, 0.3), CFG), moonbag_return(cyc(0.20, 1, 10.0), CFG)
    assert large < small  # convex penalty: copying a 10 SOL whale costs more than a 0.3 SOL one


def test_non_scratch_median_needs_enough_meaningful_trades():
    m = metrics(trader(30, lambda i: 30.0 if i < 2 else 0.01, hold_s=1800))
    assert m.nonscratch_median_roi == m.median_roi  # 2 non-scratch trades are not a "typical" trade
