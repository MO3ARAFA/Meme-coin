"""Exit policy, risk sizing / fee guard / circuit breaker, mint security, live-readiness gate."""

import time

import pytest

from copybot.config import ExitConfig, LiveGateConfig, RiskConfig
from copybot.constants import LAMPORTS_PER_SOL, TOKEN_2022_PROGRAM, TOKEN_PROGRAM
from copybot.exit_manager import Action, apply_partial_exit, decide_exit
from copybot.report import build_report
from copybot.risk_config import RiskManager, per_leg_cost_from_roundtrip
from copybot.state import BotState, Position
from copybot.token_security import inspect_mint

CFG = ExitConfig()


def pos(**kw) -> Position:
    base = dict(
        mint="M", whale="W", signal_signature="x", opened_at=time.time(), initial_token_raw=1000, token_raw=1000,
        initial_cost_lamports=10**8, cost_basis_lamports=10**8, entry_price=1.0, whale_price=1.0,
        stop_ratio=1 - CFG.hard_stop_loss, whale_peak_balance_raw=1000, whale_balance_raw=1000,
    )
    base.update(kw)
    return Position(**base)


# ---- Module C ------------------------------------------------------------------------
def test_whale_selling_30pct_dumps_everything_even_in_profit():
    p = pos(whale_balance_raw=690, peak_ratio=1.3)
    d = decide_exit(p, 1.3, time.time(), CFG)
    assert (d.action, d.fraction) == (Action.SELL, 1.0)
    assert "whale" in d.reason


def test_whale_selling_less_than_30pct_holds():
    assert decide_exit(pos(whale_balance_raw=750), 1.05, time.time(), CFG).action is Action.HOLD


def test_hard_stop_at_minus_22():
    assert decide_exit(pos(), 0.78, time.time(), CFG).reason.startswith("hard stop")
    assert decide_exit(pos(), 0.79, time.time(), CFG).action is Action.HOLD


def test_scale_out_then_moonbag_floor():
    p = pos(peak_ratio=1.46)
    d = decide_exit(p, 1.46, time.time(), CFG)
    assert (d.action, d.fraction) == (Action.SELL, 0.5)
    apply_partial_exit(p, CFG)
    assert p.scaled_out and p.stop_ratio == pytest.approx(1.15)
    # remainder: no second scale-out, but falling back to +2% closes it
    assert decide_exit(p, 1.40, time.time(), CFG).action is Action.HOLD
    assert "moonbag floor" in decide_exit(p, 1.15, time.time(), CFG).reason


def test_trailing_stop_only_after_25pct_activation():
    assert decide_exit(pos(peak_ratio=1.20), 1.01, time.time(), CFG).action is Action.HOLD
    p = pos(peak_ratio=1.40)
    assert decide_exit(p, 1.20, time.time(), CFG).action is Action.HOLD  # 14.3% off peak
    assert "trailing" in decide_exit(p, 1.19, time.time(), CFG).reason  # 15% off peak


def test_time_decay_after_45min_unless_it_ever_reached_15pct():
    old = time.time() - 46 * 60
    assert "time decay" in decide_exit(pos(opened_at=old, peak_ratio=1.10), 1.05, time.time(), CFG).reason
    assert decide_exit(pos(opened_at=old, peak_ratio=1.16), 1.05, time.time(), CFG).action is Action.HOLD


def test_max_hold_cap():
    old = time.time() - 241 * 60
    assert "max hold" in decide_exit(pos(opened_at=old, peak_ratio=1.2), 1.1, time.time(), CFG).reason


# ---- Module D ------------------------------------------------------------------------
def test_sizing_is_10pct_of_equity_and_respects_limits():
    state = BotState()
    rm = RiskManager(RiskConfig(), state)
    d = rm.size_position(LAMPORTS_PER_SOL)
    assert d.allowed and d.lamports == LAMPORTS_PER_SOL // 10
    for i in range(3):
        state.positions[str(i)] = pos(cost_basis_lamports=10**8)
    assert not rm.size_position(LAMPORTS_PER_SOL).allowed  # max 3 concurrent
    state.positions.clear()
    assert not rm.size_position(int(0.02 * LAMPORTS_PER_SOL)).allowed  # SOL reserve


def test_fee_guard_gives_priority_only_what_the_1_2pct_budget_leaves():
    rm = RiskManager(RiskConfig(), BotState())
    notional = 10**8  # 0.1 SOL -> 1.2% = 1.2M lamports
    ok = rm.fee_budget(notional, dex_cost_frac=0.003)
    assert ok.allowed and ok.max_priority_lamports == int(notional * 0.012 - notional * 0.003 - 5_000)
    # PumpSwap low-cap pools charge ~1.25%/leg: there is no budget left -> skip
    assert not rm.fee_budget(notional, dex_cost_frac=0.0126).allowed


def test_per_leg_cost_from_roundtrip():
    assert per_leg_cost_from_roundtrip(0.975) == pytest.approx(0.01258, abs=1e-4)


def test_circuit_breaker_trips_at_minus_15pct_and_halts_24h():
    state = BotState()
    rm = RiskManager(RiskConfig(), state)
    rm.roll_day(LAMPORTS_PER_SOL)
    rm.record_realized(-int(0.10 * LAMPORTS_PER_SOL))
    assert not rm.check_circuit_breaker(unrealized_pnl_lamports=0)
    assert rm.check_circuit_breaker(unrealized_pnl_lamports=-int(0.05 * LAMPORTS_PER_SOL))
    assert rm.is_halted() and state.halted_until > time.time() + 23.9 * 3600
    assert not rm.size_position(LAMPORTS_PER_SOL).allowed


# ---- Module B: mint security ---------------------------------------------------------
def _mint(owner, mint_auth=None, freeze=None, extensions=None):
    info = {"decimals": 6, "supply": "1000", "mintAuthority": mint_auth, "freezeAuthority": freeze, "isInitialized": True}
    if extensions is not None:
        info["extensions"] = extensions
    return {"owner": owner, "data": {"parsed": {"type": "mint", "info": info}, "program": "x"}}


def test_new_pumpfun_token2022_mint_is_safe():
    ext = [{"extension": "metadataPointer", "state": {}}, {"extension": "tokenMetadata", "state": {}}]
    assert inspect_mint("M", _mint(TOKEN_2022_PROGRAM, extensions=ext)).is_safe


def test_authorities_and_dangerous_extensions_are_rejected():
    assert not inspect_mint("M", _mint(TOKEN_PROGRAM, mint_auth="A")).is_safe
    assert not inspect_mint("M", _mint(TOKEN_PROGRAM, freeze="F")).is_safe
    for ext in (
        {"extension": "permanentDelegate", "state": {"delegate": "D"}},
        {"extension": "transferHook", "state": {"programId": "P", "authority": None}},
        {"extension": "transferFeeConfig", "state": {"newerTransferFee": {"transferFeeBasisPoints": 500},
                                                     "olderTransferFee": {"transferFeeBasisPoints": 0},
                                                     "transferFeeConfigAuthority": None}},
        {"extension": "pausableConfig", "state": {}},  # unknown -> fail closed
    ):
        info = inspect_mint("M", _mint(TOKEN_2022_PROGRAM, extensions=[ext]))
        assert not info.is_safe, ext


def test_missing_or_non_mint_account_is_rejected():
    assert not inspect_mint("M", None).is_safe
    assert not inspect_mint("M", {"owner": TOKEN_PROGRAM, "data": ["", "base64"]}).is_safe


# ---- LIVE gate -----------------------------------------------------------------------
def _rows(returns):
    return [{"event": "EXIT", "position_net_pnl_sol": str(r * 0.1), "position_net_return_pct": str(r * 100),
             "reason": "trailing stop", "whale": "W", "hold_minutes": "20"} for r in returns]


def test_live_gate_rejects_many_small_wins_with_big_losses():
    rep = build_report(_rows([0.05] * 50 + [-0.22] * 15), 1.0, LiveGateConfig())
    assert rep.wins == 50 and not rep.live_ready  # "50 profitable trades" is not an edge


def test_live_gate_accepts_a_real_edge():
    rep = build_report(_rows([0.30, -0.12, 0.08, 0.20, -0.10] * 12), 1.0, LiveGateConfig())
    assert rep.live_ready, rep.gate_failures


def test_moonbag_runner_is_never_cut_by_timers():
    """The 15x held 17 h in a real whale's history: after de-risking, no clock closes the runner."""
    day_old = time.time() - 17 * 3600
    unscaled = pos(opened_at=day_old, peak_ratio=1.30)
    assert "max hold" in decide_exit(unscaled, 1.30, time.time(), CFG).reason
    runner = pos(opened_at=day_old, peak_ratio=12.0, scaled_out=True, stop_ratio=1.15)
    assert decide_exit(runner, 11.0, time.time(), CFG).action is Action.HOLD  # 8% off peak, 17 h old
    assert "25%" in decide_exit(runner, 8.9, time.time(), CFG).reason  # 25.8% off peak
    assert decide_exit(pos(opened_at=day_old, scaled_out=True, stop_ratio=1.15, peak_ratio=1.2), None,
                       time.time(), CFG).action is Action.HOLD  # no price + no timer = hold


def test_overwatch_eject_sells_everything():
    p = pos(eject_reason="top holder dumped 40% of supply")
    d = decide_exit(p, 1.10, time.time(), CFG)
    assert (d.action, d.fraction) == (Action.SELL, 1.0) and "EJECT" in d.reason


def test_moonbags_do_not_block_new_entries():
    state = BotState()
    rm = RiskManager(RiskConfig(), state)
    for i in range(3):
        state.positions[str(i)] = pos(cost_basis_lamports=5 * 10**7, scaled_out=True, stop_ratio=1.15)
    assert rm.size_position(LAMPORTS_PER_SOL).allowed  # three de-risked runners: still room
    state.positions["x"] = pos()
    state.positions["y"] = pos()
    state.positions["z"] = pos()
    assert not rm.size_position(LAMPORTS_PER_SOL).allowed  # three unscaled positions: full
