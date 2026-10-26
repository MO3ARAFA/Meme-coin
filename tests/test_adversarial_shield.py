"""Pillar 1: pre-trade kill switch and imitation-penalty math."""

import pytest

from copybot.adversarial_shield import RiskSignals, exit_liquidity_risk, kill_switch, net_expected_value
from copybot.config import ShieldConfig, ScorerConfig
from copybot.wallet_scorer import copy_return, imitation_penalty

CFG = ShieldConfig()


# ---- imitation-penalty math --------------------------------------------------------
def test_net_ev_closed_form():
    # 20% edge, we bought 5% above the whale, 1% to exit, 0.4% tips, 0.5% slippage reserve
    ev = net_expected_value(0.20, 0.05, 0.01, 0.004, 0.005)
    assert ev == pytest.approx(1.20 / 1.05 * 0.99 - 1 - 0.004 - 0.005)


def test_net_ev_turns_negative_when_drift_eats_the_edge():
    assert net_expected_value(0.08, 0.02, 0.01, 0.004, 0.005) > 0
    assert net_expected_value(0.08, 0.07, 0.01, 0.004, 0.005) < 0  # same wallet, 7% later: no alpha left


def test_net_ev_rewards_buying_below_the_whale():
    assert net_expected_value(0.05, -0.03, 0.01, 0.004, 0.005) > net_expected_value(0.05, 0.0, 0.01, 0.004, 0.005)


def test_convex_penalty_grows_with_whale_size_and_is_capped():
    cfg = ScorerConfig()
    assert imitation_penalty(0.0, cfg) == pytest.approx(0.015)
    assert imitation_penalty(2.0, cfg) == pytest.approx(0.015 + 0.016)
    assert imitation_penalty(50.0, cfg) == pytest.approx(0.015 + 0.06)  # capped at 6%
    assert copy_return(0.30, cfg, 0.3) > copy_return(0.30, cfg, 5.0) > copy_return(0.30, cfg, 20.0)
    # break-even whale trade is a guaranteed loss for the copier
    assert copy_return(0.0, cfg, 1.0) < -0.03


# ---- kill switch -------------------------------------------------------------------
def test_clean_trade_with_positive_ev_passes():
    v = kill_switch(RiskSignals(holder_top5_pct=0.12, holder_max_pct=0.03), CFG,
                    edge=0.20, drift=0.03, exit_cost=0.008, tip_frac=0.004)
    assert not v.veto and v.net_ev > 0 and v.risk < CFG.max_exit_liquidity_risk


def test_negative_ev_is_a_hard_veto_even_on_a_clean_token():
    v = kill_switch(RiskSignals(), CFG, edge=0.05, drift=0.05, exit_cost=0.01, tip_frac=0.004)
    assert v.veto and v.net_ev < 0 and "negative copy EV" in v.reasons[0]


def test_unknown_edge_skips_ev_but_still_scores_risk():
    v = kill_switch(RiskSignals(bundled_whale_buy=True, holder_max_pct=0.20), CFG,
                    edge=None, drift=0.0, exit_cost=0.01, tip_frac=0.0)
    assert v.net_ev is None and v.veto and "EXIT-LIQUIDITY RISK" in v.reasons[0]


@pytest.mark.parametrize("signals,expect_veto", [
    (RiskSignals(bundled_whale_buy=True, whale_hunter_strikes=1), True),             # 40 + 20
    (RiskSignals(holder_top5_pct=0.40, holder_max_pct=0.15, identical_holders=4), True),  # 25 + 25 + 30
    (RiskSignals(rugcheck_dangers=["Freeze Authority"], edge_consumed=0.70), True),  # 30 + 30
    (RiskSignals(token_age_hours=0.5, whale_buy_pool_frac=0.03), False),             # 15 + 15
    (RiskSignals(rugcheck_normalised=None), False),                                  # RugCheck down: fails open
])
def test_am_i_the_exit_liquidity(signals, expect_veto):
    v = kill_switch(signals, CFG, edge=0.30, drift=0.0, exit_cost=0.005, tip_frac=0.002)
    assert v.veto is expect_veto, v.reasons


def test_risk_score_is_explainable_and_bounded():
    score, why = exit_liquidity_risk(RiskSignals(
        holder_top5_pct=0.9, holder_max_pct=0.9, identical_holders=9, bundled_whale_buy=True,
        whale_hunter_strikes=5, edge_consumed=0.9, whale_buy_pool_frac=0.5, token_age_hours=0.1,
        rugcheck_dangers=["x"]), CFG)
    assert score == 100 and all(w.startswith("+") for w in why) and len(why) == 9
