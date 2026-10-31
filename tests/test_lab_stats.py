"""Pure statistics (no Nautilus needed)."""

import math

import pytest

pytest.importorskip("numpy")

from nautilus_lab.stats import bootstrap_pf, bootstrap_pf_by_group, concentration, profit_factor


def test_profit_factor_basics():
    assert profit_factor([10, -5, -5]) == pytest.approx(1.0)
    assert math.isinf(profit_factor([1, 2]))
    assert profit_factor([-1, -2]) == 0.0


def test_bootstrap_ci_for_a_lucky_looking_sample_includes_one():
    b = bootstrap_pf([60, -5, -5, -5, -5, -5, -5, -5, 5, -5, -5, -5])
    assert b.point > 1.0 and b.includes_one and "no edge can be claimed" in b.line()


def test_bootstrap_ci_for_a_consistent_edge_excludes_one():
    b = bootstrap_pf([3, 4, -1, 5, 3, -1, 4, 6, -1, 3] * 6)
    assert not b.includes_one and b.lo > 1.0 and b.p_below_1 == 0.0


def test_bootstrap_is_deterministic_and_needs_data():
    assert bootstrap_pf([1, -1, 2, -1]) == bootstrap_pf([1, -1, 2, -1])
    assert bootstrap_pf([1.0]) is None
    assert bootstrap_pf_by_group({"a": [1.0], "b": [2.0]}) is None  # < 3 tokens


def test_token_bootstrap_is_stricter_when_one_token_carries_the_result():
    groups = {"star": [50, 40, 30], **{f"t{i}": [-4, -3, 2] for i in range(7)}}
    per_trade = bootstrap_pf([p for v in groups.values() for p in v])
    per_token = bootstrap_pf_by_group(groups)
    assert (per_token.hi - per_token.lo) > (per_trade.hi - per_trade.lo)
    assert per_token.p_below_1 > per_trade.p_below_1


def test_concentration_counts_trades_that_must_go():
    c = concentration([100, 80, 60, -30, -30, -30, -30, -30])
    assert c.total == 90 and c.drop_to_zero == 1 and c.red_flag
    assert c.top3_share_of_gross_profit == pytest.approx(1.0)
    spread = concentration([5] * 20 + [-4] * 10)
    assert spread.drop_to_zero == 12 and not spread.red_flag  # total 60, each best trade is 5


def test_resamples_without_a_losing_trade_do_not_poison_the_interval():
    b = bootstrap_pf([5, 6, 7, -1])  # many resamples have no loss at all -> PF = inf
    assert not math.isnan(b.lo) and not math.isnan(b.hi) and b.lo > 0


# ---- deflated Sharpe / PBO ---------------------------------------------------------------------------
def test_deflated_sharpe_separates_edge_from_noise_and_penalises_more_trials():
    import numpy as np

    from nautilus_lab.stats import deflated_sharpe

    rng = np.random.default_rng(3)
    edge, noise = rng.normal(0.05, 0.1, 200), rng.normal(0.0, 0.1, 200)
    assert deflated_sharpe(edge, 1).dsr > 0.95
    assert deflated_sharpe(noise, 1).dsr < 0.95  # a lucky-looking +0.02 Sharpe is not significant
    assert deflated_sharpe(noise, 20).dsr < 0.25  # ...and it collapses once 20 tries are admitted
    marginal = rng.normal(0.012, 0.1, 150)
    d1, d50, d500 = (deflated_sharpe(marginal, t) for t in (1, 50, 500))
    assert d1.dsr > d50.dsr > d500.dsr and d1.sr0 < d50.sr0 < d500.sr0  # luck bar rises with trials
    assert deflated_sharpe(edge[:9], 1) is None  # too few trades to say anything


def test_pbo_is_none_without_enough_configurations_and_low_for_a_real_winner():
    import numpy as np

    from nautilus_lab.stats import pbo_cscv

    rng = np.random.default_rng(5)
    noise = rng.normal(0, 1, (48, 10))
    assert pbo_cscv(noise[:, :2]) is None  # < 3 configurations: refuse to invent a number
    assert 0.2 < pbo_cscv(noise) < 0.8  # all configurations equal: the IS winner is a coin flip OOS
    real = noise.copy()
    real[:, 0] += 1.5  # one configuration is genuinely better in every slice
    assert pbo_cscv(real) < 0.05
