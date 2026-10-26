"""Pillar 3 (CFO) and Pillar 4 (self-improver) — accounting, sizing tiers, profit lock,
bounded tuning and hot reload."""

import json
import time

import pytest

from copybot.config import Settings, TreasuryConfig
from copybot.constants import LAMPORTS_PER_SOL
from copybot.risk_config import RiskManager
from copybot.self_improver import TUNABLE, RegretTracker, RuntimeOverrides, clamp_proposal, evolve, rule_based_proposal
from copybot.state import BotState
from copybot.treasury_cfo import TreasuryCFO

SOL = LAMPORTS_PER_SOL


def cfo(tmp_path) -> TreasuryCFO:
    return TreasuryCFO(TreasuryConfig(), tmp_path / "ledger.json")


def close(c: TreasuryCFO, whale: str, pnl_sol: float) -> None:
    c.record_exit(whale, int(max(0.1 + pnl_sol, 0) * SOL), 5_000, 2_039_280, 0.003, int(pnl_sol * SOL))


# ---- CFO -----------------------------------------------------------------------------
def test_meritocracy_sizing_tiers(tmp_path):
    c = cfo(tmp_path)
    assert c.size_frac("new") == (0.10, "base")
    for p in (0.05, 0.04, -0.02):
        close(c, "good", p)
    assert c.size_frac("good") == (0.12, "merit")  # PF 4.5 over 3 trades
    close(c, "bad", -0.02)
    close(c, "bad", -0.03)
    assert c.size_frac("bad") == (0.05, "probation")  # two losses in a row
    close(c, "bad", 0.04)
    assert c.size_frac("bad")[1] == "base"  # a win ends probation


def test_ledger_tracks_flows_friction_and_rent(tmp_path):
    c = cfo(tmp_path)
    c.record_entry(int(0.1 * SOL), 105_000, 2_039_280, 0.004)
    close(c, "w", 0.03)
    s = c.state
    assert s.outflow_lamports == int(0.1 * SOL) and s.inflow_lamports == int(0.13 * SOL)
    assert s.network_fees_lamports == 110_000 and s.dex_friction_lamports > 0
    assert s.rent_locked_lamports == 0  # refunded on close
    assert s.realized_pnl_lamports == int(0.03 * SOL) and s.trades_closed == 1
    c.save()
    assert TreasuryCFO(TreasuryConfig(), tmp_path / "ledger.json").state.realized_pnl_lamports == int(0.03 * SOL)
    assert "LOCKED RESERVE" in c.statement(SOL)


def test_high_water_mark_locks_half_of_each_20pct_step(tmp_path):
    c = cfo(tmp_path)
    assert c.update_hwm(SOL) == 0
    assert c.update_hwm(int(1.19 * SOL)) == 0
    assert c.update_hwm(int(1.20 * SOL)) == int(0.10 * SOL)  # 50% of the +0.20 SOL step
    assert c.update_hwm(int(1.50 * SOL)) == int(0.12 * SOL)  # next step 1.20 -> 1.44
    assert c.state.locked_reserve_lamports == int(0.22 * SOL)
    assert c.update_hwm(int(1.0 * SOL)) == 0  # drawdowns never unlock the reserve
    assert c.state.locked_reserve_lamports == int(0.22 * SOL)


def test_locked_reserve_is_never_spent(tmp_path):
    rm = RiskManager(Settings(_env_file=None).risk, BotState())
    assert rm.size_position(int(0.30 * SOL), 0.10, locked_reserve_lamports=int(0.29 * SOL)).allowed is False
    d = rm.size_position(SOL, 0.12, locked_reserve_lamports=int(0.5 * SOL))
    assert d.allowed and d.lamports == int(0.5 * SOL * 0.12)  # sized from equity minus the vault


# ---- self-improver -------------------------------------------------------------------
def test_ai_cannot_push_parameters_past_the_mandate():
    s = Settings(_env_file=None)
    out = clamp_proposal(s, {
        "exits.hard_stop_loss": 0.50,  # looser stop than -22%: refused
        "safety.min_liquidity_usd": 1_000,  # below the $25k floor: refused
        "safety.max_chase_pct": 0.30,  # above the 12% cap: refused
        "risk.position_size_frac": 0.5,  # not tunable at all
        "execution_mode": "LIVE",  # not tunable at all
        "exits.trailing_stop_pct": "garbage",
    }, max_step_frac=0.25)
    assert out["exits.hard_stop_loss"] == pytest.approx(0.22)
    assert out["safety.min_liquidity_usd"] == pytest.approx(25_000)
    assert out["safety.max_chase_pct"] == pytest.approx(0.12)
    assert set(out) <= set(TUNABLE)


def test_one_round_moves_a_parameter_at_most_25pct():
    s = Settings(_env_file=None)
    out = clamp_proposal(s, {"safety.min_liquidity_usd": 200_000, "exits.hard_stop_loss": 0.10}, 0.25)
    assert out["safety.min_liquidity_usd"] == pytest.approx(25_000 * 1.25)
    assert out["exits.hard_stop_loss"] == pytest.approx(0.22 * 0.75)


def test_hot_reload_applies_in_place_and_reclamps_hand_edits(tmp_path):
    s = Settings(_env_file=None)
    exits_ref = s.exits  # the exit manager holds this same object
    ov = RuntimeOverrides(tmp_path / "runtime_overrides.json", s)
    assert ov.maybe_reload() is None
    (tmp_path / "runtime_overrides.json").write_text(json.dumps(
        {"params": {"exits.moonbag_trailing_stop_pct": 0.30, "exits.hard_stop_loss": 0.9, "nope": 1},
         "demoted_whales": ["W"]}))
    applied = ov.maybe_reload()
    assert exits_ref.moonbag_trailing_stop_pct == pytest.approx(0.30)  # live object updated, no restart
    assert exits_ref.hard_stop_loss == pytest.approx(0.22)  # hand edit beyond the mandate re-clamped
    assert "nope" not in applied and ov.demoted == ["W"]
    assert ov.maybe_reload() is None  # unchanged file: no work


def test_rules_tuner_widens_trails_when_exits_leave_money_on_the_table():
    s = Settings(_env_file=None)
    regret = {"60m": {"n": 8, "avg_missed_upside": 0.6, "avg_saved_crash": 0.05, "sold_too_early_share": 0.7}}
    params, demote, why = rule_based_proposal(s, regret, {"loser": {"trades": 4, "profit_factor": 0.4}}, [])
    assert params["exits.trailing_stop_pct"] > s.exits.trailing_stop_pct and demote == ["loser"] and "widen" in why


async def test_evolve_round_writes_bounded_overrides_and_demotes(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path)
    c = cfo(tmp_path)
    for p in (-0.02, -0.03, -0.01):
        close(c, "loser", p)
    regret = RegretTracker(tmp_path / "regret.json", [15, 60])
    ov = RuntimeOverrides(tmp_path / "runtime_overrides.json", s)
    closes = [{"event": "EXIT", "reason": "hard stop at -23%"}] * 6 + [{"event": "EXIT", "reason": "trailing stop"}] * 4
    doc = await evolve(s, c, regret, ov, None, closes, tmp_path / "evolution_log.jsonl")
    assert doc["source"] == "rules" and doc["demoted_whales"] == ["loser"]
    assert doc["params"]["safety.min_liquidity_usd"] == pytest.approx(31_250)  # +25% step, not more
    ov.maybe_reload(c)
    assert s.safety.min_liquidity_usd == pytest.approx(31_250) and c.book("loser").demoted
    assert (tmp_path / "evolution_log.jsonl").read_text().count("\n") == 1


async def test_regret_measures_missed_upside_and_saved_crash(tmp_path):
    from types import SimpleNamespace

    class Jup:
        def __init__(self, out):
            self.out = out

        async def quote(self, i, o, amount, slip, **_):
            return SimpleNamespace(out_amount=int(amount * self.out))

    r = RegretTracker(tmp_path / "regret.json", [15, 60])
    pos = SimpleNamespace(id="p", mint="M", whale="W", close_reason="trailing stop (15%)", net_return=0.2)
    r.schedule(pos, exit_price=100.0, token_raw=1000)
    r.data["pending"][0]["due"] = [time.time() - 1, time.time() - 1]
    assert await r.process_due(Jup(150.0)) == 2  # price 50% above our exit afterwards
    s = r.summary()
    assert s["60m"]["avg_missed_upside"] == pytest.approx(0.5) and s["60m"]["sold_too_early_share"] == 1.0
