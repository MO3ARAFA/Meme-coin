"""Copy engine: listener -> parser -> safety gate -> risk -> executor -> positions -> exits.

Flow for every transaction of an approved wallet:
  1. dedupe by signature (websocket and backfill overlap);
  2. fetch + parse via balance deltas (venue-agnostic);
  3. update the whale's live holding of every token we hold from that whale
     (this is what lets the exit engine front-run the whale's exit);
  4. BUY  -> local prechecks -> size -> safety gate -> execute -> open position;
     SELL -> handled by step 3 + an immediate exit evaluation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from .config import Settings
from .constants import BASE_FEE_LAMPORTS, LAMPORTS_PER_SOL
from .dexscreener import DexScreenerClient
from .executor import BalanceRef, Executor, LiveExecutor, ShadowExecutor
from .exit_manager import ExitManager, apply_partial_exit, describe
from .jupiter import JupiterClient, NoRouteError
from .listener import WalletListener
from .notifier import Notifier
from .risk_config import RiskManager
from .ai_analyst import AIAnalyst
from .cabal_detector import bundled_recipients, holder_distribution
from .evidence import EvidenceLedger
from .safety_gate import GateResult, SafetyGate, WalletProfile
from .solana_rpc import SolanaRpc
from .state import Position, PositionStatus, StateStore, TradeJournal, save_json
from .tx_parser import Side, SwapEvent, extract_swaps, parse_balances

log = logging.getLogger(__name__)


def load_approved_wallets(path: Path) -> dict[str, WalletProfile]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run `python main.py score` first")
    data = json.loads(path.read_text())
    rows = data.get("wallets", data) if isinstance(data, dict) else data
    profiles: dict[str, WalletProfile] = {}
    for r in rows:
        if isinstance(r, dict):
            profiles[r["address"]] = WalletProfile(
                r["address"], float(r.get("median_buy_sol") or 0.0), r.get("link_group"),
                float(r.get("expected_edge_pct") or 0.0),
            )
        else:
            profiles[str(r)] = WalletProfile(str(r))
    if not profiles:
        raise ValueError(f"{path} contains no wallets")
    return profiles


def quarantine_in_file(path: Path, wallet: str, reason: str) -> None:
    """Move a wallet from `wallets` to `quarantined` so re-scoring never approves it again."""
    if not path.exists():
        return
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        data = {"wallets": data}
    keep, moved = [], None
    for r in data.get("wallets", []):
        addr = r["address"] if isinstance(r, dict) else str(r)
        if addr == wallet:
            moved = r
        else:
            keep.append(r)
    data["wallets"] = keep
    q = data.setdefault("quarantined", [])
    if not any(e.get("address") == wallet for e in q):
        score = moved.get("score") if isinstance(moved, dict) else None
        q.append({"address": wallet, "reason": reason, "at": int(time.time()), "score": score})
    save_json(path, data)


def sol(lamports: float) -> str:
    return f"{lamports / LAMPORTS_PER_SOL:.4f} SOL"


class CopyEngine:
    def __init__(self, settings: Settings, client: httpx.AsyncClient, signer=None) -> None:
        self.s = settings
        self.client = client
        self.rpc = SolanaRpc(client, settings.rpc_url, settings.rpc_rps)
        self.jupiter = JupiterClient(client, settings.jupiter_base_url, settings.jupiter_api_key, settings.jupiter_rps)
        self.dex = DexScreenerClient(client, settings.dexscreener_base_url, settings.dexscreener_rps)
        self.store = StateStore(settings.state_path)
        self.journal = TradeJournal(settings.trades_csv)
        self.notifier = Notifier(client, settings.telegram_bot_token, settings.telegram_chat_id)
        self.risk = RiskManager(settings.risk, self.store.state)
        self.gate = SafetyGate(
            settings.safety, self.rpc, self.jupiter, self.dex, self.risk, self.store.state, settings.risk.entry_slippage_bps
        )
        if settings.is_live:
            if signer is None:
                raise RuntimeError("LIVE mode requires a signer")
            self.executor: Executor = LiveExecutor(settings, self.rpc, self.jupiter, signer)
        else:
            st = self.store.state
            if st.shadow_balance_lamports is None:
                st.shadow_balance_lamports = int(settings.shadow_starting_sol * LAMPORTS_PER_SOL)
            self._shadow_balance = BalanceRef(st.shadow_balance_lamports)
            self.executor = ShadowExecutor(settings, self.jupiter, self._shadow_balance)
        self.exits = ExitManager(settings.exits, self, self.jupiter, self.dex)
        self._entry_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self.wallets: list[str] = []
        self.profiles: dict[str, WalletProfile] = {}
        self.recent_buys: dict[str, dict[str, tuple[float, int]]] = {}  # mint -> wallet -> (buy time, slot)
        self.evidence = EvidenceLedger(settings.data_dir / "evidence.jsonl")
        self.analyst = AIAnalyst(settings.llm)

    def spawn(self, coro) -> asyncio.Task:
        """Fire-and-forget with a strong reference (the event loop only keeps weak ones)."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ---- persistence -------------------------------------------------------------------
    def save(self) -> None:
        if not self.s.is_live:
            self.store.state.shadow_balance_lamports = self._shadow_balance.lamports
        self.store.save()

    def estimated_exit_fee_lamports(self) -> int:
        return BASE_FEE_LAMPORTS + self.s.shadow_assumed_priority_lamports

    # ---- signal intake -----------------------------------------------------------------
    async def on_signature(self, wallet: str, signature: str) -> None:
        if not self.store.mark_seen(signature):
            return
        tx = await self.rpc.get_transaction(signature)
        if tx is None:
            log.debug("tx %s not retrievable", signature)
            return
        self._update_whale_holdings(wallet, tx)
        for ev in extract_swaps(tx, wallet):
            if ev.side is Side.BUY:
                await self.handle_buy(ev, tx)
            else:
                log.info("whale %s SOLD %.0f%% of %s", wallet[:6], ev.sold_fraction * 100, ev.mint[:8])
        self.save()

    def _update_whale_holdings(self, wallet: str, tx: dict) -> None:
        held = [p for p in self.store.state.open_positions() if p.whale == wallet]
        if not held:
            return
        parsed = parse_balances(tx, wallet)
        if parsed is None:
            return
        for pos in held:
            if pos.mint not in parsed.token_post:
                continue
            pos.whale_balance_raw = parsed.token_post[pos.mint]
            pos.whale_peak_balance_raw = max(pos.whale_peak_balance_raw, pos.whale_balance_raw)
            if pos.whale_sold_frac >= self.s.exits.whale_sell_trigger_frac:
                self._check_fast_dump(pos, tx.get("blockTime") or time.time())
                # Front-run the rest of the whale's exit: evaluate right now, not on the next tick.
                self.spawn(self.exits.evaluate(pos))

    def _check_fast_dump(self, pos: Position, dump_time: float) -> None:
        """A whale that dumps within seconds of its own buy used its public wallet as bait.
        Two strikes and it is quarantined as a copy-trader hunter."""
        if pos.fast_dump_checked or pos.whale_entry_time is None:
            return
        pos.fast_dump_checked = True
        held = dump_time - pos.whale_entry_time
        if held > self.s.exits.fast_dump_window_s:
            return
        strikes = self.store.state.hunter_strikes.get(pos.whale, 0) + 1
        self.store.state.hunter_strikes[pos.whale] = strikes
        log.warning("whale %s dumped %.0fs after its buy (strike %d)", pos.whale[:6], held, strikes)
        if strikes >= self.s.exits.quarantine_strikes and pos.whale not in self.store.state.quarantined:
            self.store.state.quarantined.append(pos.whale)
            reason = f"{strikes} dumps within {self.s.exits.fast_dump_window_s:.0f}s of its own buy"
            quarantine_in_file(self.s.approved_wallets_path, pos.whale, reason)
            self.evidence.record("QUARANTINE", wallet=pos.whale, mint=pos.mint, strikes=strikes,
                                 held_s=round(held, 1), whale_slot=pos.whale_slot, reason=reason)
            self.spawn(self.notifier.send(f"🚫 QUARANTINED {pos.whale}: copy-trader hunter ({reason})",
                                          level=logging.WARNING))

    # ---- entries -----------------------------------------------------------------------
    def _record_buy_and_cluster(self, ev: SwapEvent) -> list[str]:
        """Remember this approved-wallet buy and return the OTHER wallets, independent of it
        (different link group), that bought the same token within the cluster window. An
        already-open position on that token is upgraded to HIGH_CONVICTION_CLUSTER."""
        now = float(ev.block_time or time.time())
        window = self.s.safety.cluster_window_s
        for mint in [m for m, b in self.recent_buys.items() if max(t for t, _ in b.values()) < now - window]:
            del self.recent_buys[mint]
        buys = self.recent_buys.setdefault(ev.mint, {})
        buys[ev.wallet] = (now, ev.slot)
        me = self.profiles.get(ev.wallet, WalletProfile(ev.wallet))
        # Independent = different link group (transfers / fingerprint) AND not in the same or an
        # adjacent slot: two wallets landing together are one bundle, not two opinions.
        others = [
            w for w, (t, slot) in buys.items()
            if now - t <= window and me.independent_of(self.profiles.get(w, WalletProfile(w)))
            and (not ev.slot or not slot or abs(ev.slot - slot) > 1)
        ]
        for pos in self.store.state.open_positions():
            if pos.mint == ev.mint and not pos.high_conviction and pos.whale in others:
                pos.high_conviction = True
                pos.tier = "CLUSTER"
                pos.cluster_wallets = sorted({pos.whale, ev.wallet})
                self.evidence.record("CLUSTER_UPGRADE", mint=pos.mint, wallets=pos.cluster_wallets, slot=ev.slot,
                                     signature=ev.signature)
                log.info("HIGH_CONVICTION_CLUSTER %s: independent wallets %s",
                         pos.symbol or pos.mint[:8], [w[:6] for w in pos.cluster_wallets])
        return others

    async def handle_buy(self, ev: SwapEvent, tx: dict | None = None) -> None:
        cluster = self._record_buy_and_cluster(ev)
        pre = self.gate.precheck(ev)
        if tx is not None and self.s.safety.reject_bundled_whale_buy:
            ring = bundled_recipients(tx, ev.wallet, ev.mint)
            if ring:
                pre.append(f"BUNDLE: the whale's buy tx also delivered tokens to {len(ring)} other wallet(s)")
        if pre:
            log.info("skip %s from %s: %s", ev.mint[:8], ev.wallet[:6], "; ".join(pre))
            self.evidence.record("ABORT", stage="precheck", wallet=ev.wallet, mint=ev.mint, slot=ev.slot,
                                 signature=ev.signature, whale_sol=ev.quote_amount_raw / LAMPORTS_PER_SOL,
                                 reasons=pre)
            return
        async with self._entry_lock:  # serialize entries: position limits and no double-dip
            free = await self.executor.free_balance_lamports()
            self.risk.roll_day(self.risk.equity_lamports(free))
            sizing = self.risk.size_position(free)
            if not sizing.allowed:
                log.info("skip %s: %s", ev.mint[:8], sizing.reason)
                return
            gate = await self.gate.evaluate(ev, sizing.lamports)
            log.info("gate %s", gate.summary())
            self.evidence.record(
                "COPY" if gate.passed else "ABORT", stage="gate", wallet=ev.wallet, mint=ev.mint, slot=ev.slot,
                signature=ev.signature, whale_sol=ev.quote_amount_raw / LAMPORTS_PER_SOL,
                imitation_drift_pct=round(gate.chase_pct * 100, 2),
                roundtrip_cost_pct=round((1 - gate.roundtrip_return) * 100, 2) if gate.roundtrip_return else None,
                edge_consumed_pct=round(gate.edge_consumed * 100, 1) if gate.edge_consumed else None,
                holder_top5_pct=round(gate.holders.top5_pct * 100, 1) if gate.holders else None,
                holder_max_pct=round(gate.holders.max_single_pct * 100, 1) if gate.holders else None,
                liquidity_usd=gate.pair.liquidity_usd if gate.pair else None,
                tier="CLUSTER" if cluster else "SOLO", latency_ms=round(gate.latency_ms), reasons=gate.reasons,
            )
            if not gate.passed:
                return
            await self._enter(ev, sizing.lamports, gate, cluster)

    async def _enter(self, ev: SwapEvent, lamports: int, gate: GateResult, cluster: list[str] | None = None) -> None:
        assert gate.buy_quote and gate.fee_budget
        fill = await self.executor.buy(ev.mint, lamports, gate.buy_quote, gate.fee_budget.max_priority_lamports)
        # The attempt counts against the 24h re-entry rule even if it failed.
        self.store.state.last_entry_by_mint[ev.mint] = time.time()
        if not fill.ok:
            await self.notifier.send(f"BUY FAILED {ev.mint[:8]}: {fill.error}", level=logging.WARNING)
            self.save()
            return
        mint_info = gate.mint_info
        symbol = gate.pair.base_symbol if gate.pair else ""
        calibration = 0.0
        if gate.pair and gate.pair.price_native > 0:
            calibration = gate.roundtrip_return / gate.pair.price_native
        pos = Position(
            mint=ev.mint,
            symbol=symbol,
            whale=ev.wallet,
            signal_signature=ev.signature,
            opened_at=time.time(),
            token_program=mint_info.program if mint_info else ev.token_program,
            decimals=mint_info.decimals if mint_info else ev.decimals,
            initial_token_raw=fill.token_raw,
            token_raw=fill.token_raw,
            initial_cost_lamports=fill.lamports,
            cost_basis_lamports=fill.lamports,
            fees_lamports=fill.fees_lamports,
            rent_lamports=fill.rent_lamports,
            entry_price=fill.lamports / fill.token_raw,
            whale_price=gate.whale_price,
            mark_calibration=calibration,
            peak_ratio=gate.roundtrip_return,
            last_ratio=gate.roundtrip_return,
            last_quote_ts=time.time(),
            stop_ratio=1 - self.s.exits.hard_stop_loss,
            whale_peak_balance_raw=ev.token_balance_after_raw,
            whale_balance_raw=ev.token_balance_after_raw,
            whale_entry_time=float(ev.block_time) if ev.block_time else time.time(),
            high_conviction=bool(cluster),
            tier="CLUSTER" if cluster else "SOLO",
            whale_slot=ev.slot,
            cluster_wallets=sorted(set(cluster) | {ev.wallet}) if cluster else [],
            entry_tx=fill.signature,
        )
        self.store.state.positions[pos.id] = pos
        self.journal.append(
            {
                "event": "ENTRY",
                "position_id": pos.id,
                "mint": pos.mint,
                "symbol": pos.symbol,
                "whale": pos.whale,
                "reason": f"{'CLUSTER ' if pos.high_conviction else ''}copy {ev.signature[:16]} "
                          f"chase={gate.chase_pct:+.2%} rt={gate.roundtrip_return - 1:+.2%}",
                "sol_amount": f"{fill.lamports / LAMPORTS_PER_SOL:.6f}",
                "token_amount_ui": f"{fill.token_raw / 10 ** pos.decimals:.6f}",
                "price_lamports_per_raw": f"{pos.entry_price:.12g}",
                "whale_price_lamports_per_raw": f"{pos.whale_price:.12g}",
                "fees_sol": f"{fill.fees_lamports / LAMPORTS_PER_SOL:.6f}",
                "tx": fill.signature,
            }
        )
        self.save()
        await self.notifier.send(
            f"{'🟢 LIVE' if self.s.is_live else '📝 SHADOW'} BUY {symbol} {ev.mint} for {sol(fill.lamports)} "
            f"(whale {ev.wallet[:6]}…, chase {gate.chase_pct:+.1%}, round-trip {gate.roundtrip_return - 1:+.2%}, "
            f"gate {gate.latency_ms:.0f}ms, {pos.tier})"
        )
        self.spawn(self.overwatch(pos, gate))

    async def overwatch(self, pos: Position, gate: GateResult) -> None:
        """Post-buy audit, off the hot path. Re-reads holders, liquidity and order flow a moment
        after the fill. Hard on-chain flags eject on their own; the AI may only eject when it is
        confident AND at least one on-chain flag backs it."""
        await asyncio.sleep(self.s.llm.overwatch_delay_s)
        if pos.status is not PositionStatus.OPEN:
            return
        cfg = self.s.safety
        hard: list[str] = []
        soft: list[str] = []
        facts: dict = {"mint": pos.mint, "symbol": pos.symbol, "tier": pos.tier, "whale": pos.whale}
        try:
            supply = gate.mint_info.supply_raw if gate.mint_info else 0
            pools = {gate.pair.pair_address} if gate.pair else set()
            holders = await holder_distribution(self.rpc, pos.mint, supply, exclude=pools,
                                                tolerance=cfg.identical_holder_tolerance, min_pct=cfg.identical_holder_min_pct)
            facts["holders_top5_pct"] = round(holders.top5_pct * 100, 1)
            facts["holder_max_pct"] = round(holders.max_single_pct * 100, 1)
            facts["top_holders"] = [(o[:8], round(p * 100, 2)) for o, p in holders.holders[:10]]
            hard += holders.problems(cfg.max_top5_holder_pct, cfg.max_single_holder_pct, cfg.identical_holder_min_count)
        except Exception as exc:
            log.debug("overwatch holders failed: %s", exc)
        try:
            pair = await self.dex.best_pair(pos.mint)
            if pair:
                facts.update(liquidity_usd=pair.liquidity_usd, m5_buys=pair.txns_m5[0], m5_sells=pair.txns_m5[1],
                             volume_h1_usd=pair.volume_h1_usd)
                if gate.pair and gate.pair.liquidity_usd and pair.liquidity_usd is not None \
                        and pair.liquidity_usd < 0.7 * gate.pair.liquidity_usd:
                    hard.append(f"liquidity fell {1 - pair.liquidity_usd / gate.pair.liquidity_usd:.0%} since entry (pull in progress)")
                buys, sells = pair.txns_m5
                if sells >= 20 and sells > 3 * max(buys, 1):
                    soft.append(f"sell pressure: {sells} sells vs {buys} buys in 5 min")
        except Exception as exc:
            log.debug("overwatch dex failed: %s", exc)
        facts["onchain_flags"] = hard + soft
        verdict = await self.analyst.overwatch(facts) if self.analyst.available else None
        trap = verdict["trap_probability"] if verdict else None
        reason = ""
        if hard:
            reason = "; ".join(hard)
        elif verdict and trap >= self.s.llm.eject_trap_probability and soft:
            reason = f"AI trap probability {trap:.0%} + {'; '.join(soft)}"
        self.evidence.record("OVERWATCH", mint=pos.mint, wallet=pos.whale, slot=pos.whale_slot,
                             signature=pos.signal_signature, flags=hard + soft, trap_probability=trap,
                             ai_rationale=(verdict or {}).get("rationale"), eject=bool(reason))
        if reason:
            pos.eject_reason = reason
            self.evidence.record("EJECT", mint=pos.mint, wallet=pos.whale, reason=reason)
            log.warning("AI_EMERGENCY_EJECT %s: %s", pos.symbol or pos.mint[:8], reason)
            await self.exits.evaluate(pos, force_quote=True)

    # ---- exits -------------------------------------------------------------------------
    async def close_or_reduce(self, pos: Position, fraction: float, reason: str, *, emergency: bool = False) -> None:
        final = fraction >= 0.999
        amount = pos.token_raw if final else int(pos.token_raw * fraction)
        if amount <= 0:
            return
        expected_out = int(max(pos.last_ratio, 0.01) * pos.cost_basis_lamports * amount / pos.token_raw)
        budget = self.risk.fee_budget(max(expected_out, 1), 0.0)
        # Exits are never blocked by the fee cap — a stop that can't fire is worse than a fee.
        max_prio = self.s.risk.max_priority_fee_lamports if emergency else max(
            budget.max_priority_lamports, self.s.risk.min_priority_fee_lamports
        )
        slippage = self.s.exits.emergency_slippage_bps if emergency else self.s.exits.exit_slippage_bps
        try:
            fill = await self.executor.sell(
                pos.mint, amount, slippage_bps=slippage, max_priority_lamports=max_prio, final=final,
                token_program=pos.token_program,
            )
        except NoRouteError:
            if emergency:
                await self._write_off(pos, reason)
            return
        except Exception as exc:
            log.warning("sell %s failed: %s", pos.mint[:8], exc)
            return
        if not fill.ok:
            await self.notifier.send(f"SELL FAILED {pos.mint[:8]} ({reason}): {fill.error}", level=logging.WARNING)
            return

        sold = min(fill.token_raw, pos.token_raw)
        cost_part = int(pos.cost_basis_lamports * sold / pos.token_raw)
        pos.realized_lamports += fill.lamports
        pos.fees_lamports += fill.fees_lamports
        pos.token_raw -= sold
        pos.cost_basis_lamports -= cost_part
        pos.exit_txs.append(fill.signature)
        self.risk.record_realized(fill.lamports - cost_part)
        if final or pos.token_raw <= 0:
            pos.token_raw = 0
            pos.cost_basis_lamports = 0
            pos.status = PositionStatus.CLOSED
            pos.closed_at = time.time()
            pos.close_reason = reason
            if fill.rent_lamports:
                pos.rent_lamports = 0
        else:
            apply_partial_exit(pos, self.s.exits)
        self.evidence.record("EXIT" if pos.status is PositionStatus.CLOSED else "EXIT_PARTIAL", mint=pos.mint,
                             wallet=pos.whale, tier=pos.tier, reason=reason, signature=fill.signature,
                             net_return_pct=round(pos.net_return * 100, 2) if pos.status is PositionStatus.CLOSED else None)
        self._journal_exit(pos, "EXIT" if pos.status is PositionStatus.CLOSED else "EXIT_PARTIAL", reason, fill.lamports,
                           sold, fill.fees_lamports, fill.signature)
        self.save()
        if pos.status is PositionStatus.CLOSED:
            await self.notifier.send(
                f"{'🔴' if pos.net_pnl_lamports < 0 else '✅'} CLOSED {pos.symbol or pos.mint[:8]} — {reason} | "
                f"net {sol(pos.net_pnl_lamports)} ({pos.net_return:+.1%}) in {pos.age_minutes:.0f}min"
            )
        else:
            await self.notifier.send(f"💰 SCALE-OUT {pos.symbol or pos.mint[:8]} — {reason} | received {sol(fill.lamports)}; stop -> break-even")
        self.check_breaker()

    async def _write_off(self, pos: Position, reason: str) -> None:
        cost = pos.cost_basis_lamports
        pos.token_raw = 0
        pos.cost_basis_lamports = 0
        pos.status = PositionStatus.CLOSED
        pos.closed_at = time.time()
        pos.close_reason = f"WRITE-OFF: {reason}"
        self.risk.record_realized(-cost)
        self._journal_exit(pos, "EXIT", pos.close_reason, 0, 0, 0, "")
        self.save()
        await self.notifier.send(f"☠️ WRITE-OFF {pos.mint[:8]}: no sell route. Net {sol(pos.net_pnl_lamports)}", level=logging.ERROR)
        self.check_breaker()

    def _journal_exit(self, pos: Position, event: str, reason: str, lamports: int, sold: int, fees: int, tx: str) -> None:
        closed = pos.status is PositionStatus.CLOSED
        self.journal.append(
            {
                "event": event,
                "position_id": pos.id,
                "mint": pos.mint,
                "symbol": pos.symbol,
                "whale": pos.whale,
                "reason": reason,
                "sol_amount": f"{lamports / LAMPORTS_PER_SOL:.6f}",
                "token_amount_ui": f"{sold / 10 ** pos.decimals:.6f}" if pos.decimals else str(sold),
                "price_lamports_per_raw": f"{lamports / sold:.12g}" if sold else "",
                "whale_price_lamports_per_raw": f"{pos.whale_price:.12g}",
                "fees_sol": f"{fees / LAMPORTS_PER_SOL:.6f}",
                "position_net_pnl_sol": f"{pos.net_pnl_lamports / LAMPORTS_PER_SOL:.6f}" if closed else "",
                "position_net_return_pct": f"{pos.net_return * 100:.2f}" if closed else "",
                "hold_minutes": f"{pos.age_minutes:.1f}",
                "tx": tx,
            }
        )

    def check_breaker(self) -> None:
        unrealized = sum(int((p.last_ratio - 1) * p.cost_basis_lamports) for p in self.store.state.open_positions())
        if self.risk.check_circuit_breaker(unrealized):
            self.save()
            self.spawn(
                self.notifier.send("⛔ CIRCUIT BREAKER: daily loss limit hit — no new entries for 24h (exits keep running)",
                                   level=logging.WARNING)
            )

    # ---- main loop ---------------------------------------------------------------------
    async def status_loop(self) -> None:
        while True:
            await asyncio.sleep(300)
            free = await self.executor.free_balance_lamports()
            opens = self.store.state.open_positions()
            log.info("status: free %s, equity %s, %d open%s", sol(free), sol(self.risk.equity_lamports(free)), len(opens),
                     "".join(f"\n  - {describe(p)}" for p in opens))

    async def run(self) -> None:
        await self.analyst.probe()
        log.info("AI overwatch: %s", self.analyst.status)
        self.profiles = load_approved_wallets(self.s.approved_wallets_path)
        self.gate.profiles = self.profiles
        self.wallets = list(self.profiles)
        free = await self.executor.free_balance_lamports()
        self.risk.roll_day(self.risk.equity_lamports(free))
        self.save()
        listener = WalletListener(
            self.s.ws_url, self.rpc, self.wallets, self.on_signature, self.store.state.last_signature_by_wallet,
            mode=self.s.listener_mode, poll_interval_s=self.s.poll_interval_s,
        )
        await self.notifier.send(
            f"copybot started in {self.s.execution_mode.value} | {len(self.wallets)} wallets | free {sol(free)} | "
            f"{len(self.store.state.open_positions())} open positions restored"
        )
        await asyncio.gather(listener.run(), self.exits.run(), self.status_loop())
