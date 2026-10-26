"""End-to-end SHADOW_PAPER run with fake market APIs: whale buy -> gate -> paper entry ->
scale-out -> whale starts dumping -> we exit first. Also: anti-chase, no double-dip, stop loss."""

import time

import pytest

from copybot.config import Settings
from copybot.constants import LAMPORTS_PER_SOL, TOKEN_2022_PROGRAM, USDC_MINT, WSOL_MINT
from copybot.copy_engine import CopyEngine
from copybot.dexscreener import PairInfo
from copybot.http_utils import make_client
from copybot.jupiter import NoRouteError, Quote
from copybot.report import build_report
from copybot.state import PositionStatus

from .helpers import MEME, SOL, WHALE, whale_buy_tx, whale_sell_tx

DEC = 6


class FakeMarket:
    """A constant-product-free toy market: price in lamports per raw token, flat DEX fee per leg."""

    def __init__(self, price: float, fee: float = 0.003, liquidity: float = 80_000, mcap: float = 400_000):
        self.price = price
        self.fee = fee
        self.liquidity = liquidity
        self.mcap = mcap
        self.routable = True
        self.quotes = 0

    # Jupiter
    async def quote(self, input_mint, output_mint, amount, slippage_bps, **_):
        self.quotes += 1
        if not self.routable:
            raise NoRouteError("no route")
        if output_mint == USDC_MINT:  # SOL/USD reference
            out = 100 * 10**6
        elif input_mint == WSOL_MINT:  # buying any memecoin
            out = int(amount / self.price * (1 - self.fee))
        else:  # selling any memecoin
            out = int(amount * self.price * (1 - self.fee))
        return Quote(input_mint, output_mint, amount, out, int(out * (1 - slippage_bps / 1e4)), 0.001, slippage_bps,
                     ("FakeAmm",), {})

    # DexScreener
    async def pairs_for_tokens(self, mints, **_):
        native = self.price * 10**DEC / LAMPORTS_PER_SOL
        return {m: [PairInfo("pair", "pumpswap", m, "FAKE", WSOL_MINT, native, native * 100, self.liquidity, self.mcap,
                             self.mcap, int(time.time() * 1000) - 3_600_000, 10_000, (10, 5))] for m in mints}


class FakeRpc:
    def __init__(self):
        self.txs = {}

    async def get_transaction(self, sig, retries=6):
        return self.txs.get(sig)

    async def get_account_info_parsed(self, mint):
        ext = [{"extension": "metadataPointer", "state": {}}, {"extension": "tokenMetadata", "state": {}}]
        info = {"decimals": DEC, "supply": "1000000000000000", "mintAuthority": None, "freezeAuthority": None, "extensions": ext}
        return {"owner": TOKEN_2022_PROGRAM, "data": {"parsed": {"type": "mint", "info": info}}}


@pytest.fixture
async def engine(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path, approved_wallets_path=tmp_path / "a.json", shadow_starting_sol=1.0,
                 shadow_latency_haircut_bps=75)
    market, rpc = FakeMarket(price=500.0), FakeRpc()  # 500 lamports per raw unit
    async with make_client() as client:
        eng = CopyEngine(s, client)
        eng.rpc = eng.gate.rpc = rpc
        eng.jupiter = eng.gate.jupiter = eng.gate.sol_price.jupiter = eng.exits.jupiter = eng.executor.jupiter = market
        eng.dex = eng.gate.dex = eng.exits.dex = market
        eng.market = market
        eng.fake_rpc = rpc
        yield eng


async def whale_buys(eng, sig="buy1", price=500.0, sol=2.0, before=0, wallet=WHALE, mint=MEME, block_time=None):
    tokens = int(sol * SOL / price)
    eng.fake_rpc.txs[sig] = whale_buy_tx(sig, sol_spent=int(sol * SOL), tokens=tokens, before=before, wallet=wallet,
                                         mint=mint, block_time=block_time or int(time.time()))
    await eng.on_signature(wallet, sig)
    return tokens


async def test_full_shadow_lifecycle(engine):
    eng, market = engine, engine.market
    whale_tokens = await whale_buys(eng)
    [pos] = eng.store.state.open_positions()
    assert pos.whale == WHALE and pos.token_program == TOKEN_2022_PROGRAM
    # 10% of 1 SOL, plus base fee + capped priority
    assert pos.initial_cost_lamports == pytest.approx(0.1 * SOL + 105_000, rel=1e-6)
    assert pos.whale_peak_balance_raw == whale_tokens
    assert eng._shadow_balance.lamports < 0.9 * SOL  # cost + fee + ATA rent locked

    # +60%: scale out half, stop to break-even
    market.price *= 1.6
    await eng.exits.evaluate(pos, force_quote=True)
    assert pos.scaled_out and pos.stop_ratio == pytest.approx(1.02)
    assert pos.token_raw == pytest.approx(pos.initial_token_raw / 2, abs=1)

    # whale sells 35% of its bag -> we dump 100% immediately
    eng.fake_rpc.txs["sell1"] = whale_sell_tx("sell1", sol_received=int(1.1 * SOL), tokens=int(whale_tokens * 0.35),
                                              before=whale_tokens, block_time=int(time.time()))
    await eng.on_signature(WHALE, "sell1")
    assert pos.whale_sold_frac == pytest.approx(0.35, abs=1e-3)
    await eng.exits.evaluate(pos)
    assert pos.status is PositionStatus.CLOSED and "whale" in pos.close_reason
    assert pos.net_pnl_lamports > 0

    rows = eng.journal.read()
    assert [r["event"] for r in rows] == ["ENTRY", "EXIT_PARTIAL", "EXIT"]
    rep = build_report(rows, 1.0, eng.s.live_gate)
    assert rep.trades == 1 and rep.wins == 1
    # rent refunded on close: balance = start + net pnl
    assert eng._shadow_balance.lamports == pytest.approx(SOL + pos.net_pnl_lamports, abs=2)

    # same token again within 24h: no double-dip
    await whale_buys(eng, sig="buy2", before=0)
    assert len(eng.store.state.positions) == 1


async def test_anti_chase_skips_when_price_already_pumped(engine):
    engine.market.price = 500.0 * 1.20  # copy bots already pushed it 20% above the whale's fill
    await whale_buys(engine, price=500.0)
    assert engine.store.state.open_positions() == []


async def test_illiquid_pool_and_fat_roundtrip_are_rejected(engine):
    engine.market.liquidity = 12_000
    await whale_buys(engine, sig="a")
    assert engine.store.state.open_positions() == []
    engine.market.liquidity = 80_000
    engine.market.fee = 0.04  # 4%/leg -> ~8% round trip: sell tax / honeypot-like
    await whale_buys(engine, sig="b")
    assert engine.store.state.open_positions() == []


async def test_hard_stop_and_duplicate_signature(engine):
    await whale_buys(engine, sig="x")
    await engine.on_signature(WHALE, "x")  # websocket + backfill duplicate
    [pos] = engine.store.state.open_positions()
    engine.market.price *= 0.70
    await engine.exits.evaluate(pos, force_quote=True)
    assert pos.status is PositionStatus.CLOSED and pos.close_reason.startswith("hard stop")
    assert pos.net_return < -0.22


async def test_rug_with_no_sell_route_is_written_off(engine):
    await whale_buys(engine, sig="r")
    [pos] = engine.store.state.open_positions()
    engine.market.routable = False
    await engine.exits.evaluate(pos, force_quote=True)
    assert pos.status is PositionStatus.OPEN and pos.no_route_since
    pos.no_route_since -= engine.s.exits.no_route_emergency_s + 1
    pos.last_quote_ts = 0
    await engine.exits.evaluate(pos, force_quote=True)
    assert pos.status is PositionStatus.CLOSED and "WRITE-OFF" in pos.close_reason
    assert pos.net_return == -1.0


async def test_state_survives_restart(engine, tmp_path):
    await whale_buys(engine, sig="p")
    pid = engine.store.state.open_positions()[0].id
    async with make_client() as client:
        again = CopyEngine(engine.s, client)
    assert [p.id for p in again.store.state.open_positions()] == [pid]
    assert again._shadow_balance.lamports == engine._shadow_balance.lamports


# ---- adversarial intelligence ------------------------------------------------------
WHALE2 = "Wha1e2222222222222222222222222222222222222"
MEME2 = "MemeMint222222222222222222222222222222pump"


def profiles(eng, **kw):
    from copybot.safety_gate import WalletProfile

    eng.profiles = {w: WalletProfile(w, *v) for w, v in kw.items()}
    eng.gate.profiles = eng.profiles


async def test_bait_sized_buy_is_aborted(engine):
    profiles(engine, **{WHALE: (3.0, 0)})
    await whale_buys(engine, sig="bait", sol=0.5)  # 0.5 SOL vs a 3 SOL median: < 30%
    assert engine.store.state.open_positions() == []
    await whale_buys(engine, sig="real", sol=2.5)
    assert len(engine.store.state.open_positions()) == 1


async def test_independent_cluster_tags_position_and_widens_runner_trail(engine):
    profiles(engine, **{WHALE: (2.0, 0), WHALE2: (2.0, 1)})
    await whale_buys(engine, sig="w1")
    [pos] = engine.store.state.open_positions()
    assert not pos.high_conviction
    await whale_buys(engine, sig="w2", wallet=WHALE2)  # second, independent wallet within 10 min
    assert pos.high_conviction and set(pos.cluster_wallets) == {WHALE, WHALE2}
    assert len(engine.store.state.open_positions()) == 1  # consensus never doubles the position

    from copybot.exit_manager import Action, decide_exit

    pos.scaled_out, pos.stop_ratio, pos.peak_ratio = True, 1.02, 2.0
    cfg = engine.s.exits
    assert decide_exit(pos, 1.65, time.time(), cfg).action is Action.HOLD  # -17.5% from peak: inside 25% trail
    assert "25%" in decide_exit(pos, 1.49, time.time(), cfg).reason
    pos.high_conviction = False
    assert decide_exit(pos, 1.65, time.time(), cfg).action is Action.SELL  # normal 15% trail


async def test_linked_wallets_do_not_count_as_consensus(engine):
    profiles(engine, **{WHALE: (2.0, 7), WHALE2: (2.0, 7)})  # same link group = same operator
    await whale_buys(engine, sig="l1")
    await whale_buys(engine, sig="l2", wallet=WHALE2)
    [pos] = engine.store.state.open_positions()
    assert not pos.high_conviction


async def test_two_fast_dumps_quarantine_the_wallet(engine):
    import json

    engine.s.approved_wallets_path.write_text(json.dumps({"wallets": [{"address": WHALE, "score": 70}]}))
    for n, mint in enumerate((MEME, MEME2)):
        t0 = int(time.time())
        tokens = await whale_buys(engine, sig=f"fb{n}", mint=mint, block_time=t0)
        engine.fake_rpc.txs[f"fd{n}"] = whale_sell_tx(f"fd{n}", sol_received=SOL, tokens=tokens // 2, before=tokens,
                                                      mint=mint, block_time=t0 + 40)  # dumped 40 s after buying
        await engine.on_signature(WHALE, f"fd{n}")
        for task in list(engine._tasks):
            await task
    assert engine.store.state.hunter_strikes[WHALE] == 2
    assert WHALE in engine.store.state.quarantined
    data = json.loads(engine.s.approved_wallets_path.read_text())
    assert data["wallets"] == [] and data["quarantined"][0]["address"] == WHALE
    assert all(p.status is PositionStatus.CLOSED for p in engine.store.state.positions.values())
    MEME3 = "MemeMint333333333333333333333333333333pump"
    await whale_buys(engine, sig="after", mint=MEME3)
    assert engine.store.state.open_positions() == []  # signals from a quarantined wallet are ignored
