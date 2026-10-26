"""Module A — smart-money wallet scorer: keep the copyable traders, reject farmers & insiders.

Data source: plain Solana RPC (`getSignaturesForAddress` + `getTransaction`), parsed with
the same venue-agnostic balance-delta parser the live bot uses — so a wallet is scored on
exactly the events the bot will later see. Works with any RPC; a free Helius key is plenty
(each tx is 1 credit). Fetched transactions are cached on disk, so re-runs are nearly free.

Trade reconstruction ("cycles"): per token, a cycle opens on the first buy from a zero
balance and closes when the holding is sold down to dust. A cycle's ROI = SOL out / SOL in − 1
across all its buys and sells (scaling in/out is handled naturally). Cycles that started
before the lookback window, are still open, or ended by moving tokens to another wallet are
excluded from ROI stats (the last kind is counted as an insider/bundler tell).
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from solders.pubkey import Pubkey

from .config import ScorerConfig, Settings
from .constants import LAMPORTS_PER_SOL, USDC_MINT, WSOL_MINT
from .dexscreener import DexScreenerClient, token_created_at_ms
from .jupiter import JupiterClient
from .solana_rpc import SolanaRpc
from .state import save_json
from .tx_parser import Side, SwapEvent, extract_swaps, extract_transfers_out

log = logging.getLogger(__name__)

DUST_FRAC = 0.01  # holding <= 1% of the cycle's peak counts as fully exited


@dataclass
class Cycle:
    mint: str
    opened_at: int
    sol_in: float = 0.0  # lamports
    sol_out: float = 0.0
    buys: int = 0
    sells: int = 0
    peak_balance: int = 0
    first_sell_at: int | None = None
    closed_at: int | None = None
    outcome: str = "open"  # open | sold | transferred | contaminated | unpriced

    @property
    def roi(self) -> float:
        return self.sol_out / self.sol_in - 1.0 if self.sol_in else 0.0

    @property
    def pnl(self) -> float:
        return self.sol_out - self.sol_in

    @property
    def hold_s(self) -> float:
        return float((self.closed_at or self.opened_at) - self.opened_at)

    @property
    def first_sell_delay_s(self) -> float:
        return float((self.first_sell_at or self.closed_at or self.opened_at) - self.opened_at)


@dataclass
class WalletMetrics:
    address: str
    txs_scanned: int = 0
    history_days: float = 0.0
    closed_trades: int = 0
    win_rate: float = 0.0
    median_roi: float = 0.0
    mean_roi: float = 0.0
    avg_hold_s: float = 0.0
    median_hold_s: float = 0.0
    flip_ratio: float = 0.0
    profit_factor: float = 0.0
    top_trade_pnl_share: float = 0.0
    sniper_ratio: float = 0.0
    transfer_out_ratio: float = 0.0
    unpriced_ratio: float = 0.0
    avg_buy_sol: float = 0.0
    trades_per_day: float = 0.0
    days_since_last_trade: float = 0.0
    total_pnl_sol: float = 0.0
    score: float = 0.0
    passed: bool = False
    rejections: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------------------
def build_cycles(
    events: list[tuple[int, int, str, object]],
    usd_per_sol: float,
) -> list[Cycle]:
    """events: (block_time, slot, kind, payload) sorted chronologically, where kind is
    'swap' (payload SwapEvent) or 'xfer' (payload (mint, amount_raw, balance_after_raw))."""
    open_cycles: dict[str, Cycle] = {}
    done: list[Cycle] = []

    def to_lamports(ev: SwapEvent) -> float:
        if ev.is_sol_quoted:
            return float(ev.quote_amount_raw)
        return ev.quote_amount_raw / 1e6 / usd_per_sol * LAMPORTS_PER_SOL  # 6-decimal stables

    for t, _slot, kind, payload in events:
        if kind == "swap":
            ev: SwapEvent = payload  # type: ignore[assignment]
            cyc = open_cycles.get(ev.mint)
            if ev.side is Side.BUY:
                if cyc is None:
                    cyc = Cycle(mint=ev.mint, opened_at=t)
                    # Already held a meaningful bag before this buy: PnL would be polluted
                    # by tokens bought outside our window.
                    if ev.token_balance_before_raw > DUST_FRAC * ev.token_balance_after_raw:
                        cyc.outcome = "contaminated"
                    open_cycles[ev.mint] = cyc
                cyc.sol_in += to_lamports(ev)
                cyc.buys += 1
                cyc.peak_balance = max(cyc.peak_balance, ev.token_balance_after_raw)
            else:
                if cyc is None:
                    continue  # selling a bag bought before the window
                cyc.sol_out += to_lamports(ev)
                cyc.sells += 1
                if cyc.first_sell_at is None:
                    cyc.first_sell_at = t
                if ev.token_balance_after_raw <= DUST_FRAC * cyc.peak_balance:
                    cyc.closed_at = t
                    if cyc.outcome == "open":
                        cyc.outcome = "sold"
                    done.append(open_cycles.pop(ev.mint))
        else:
            mint, _amount, balance_after = payload  # type: ignore[misc]
            cyc = open_cycles.get(mint)
            if cyc is None:
                continue
            if balance_after <= DUST_FRAC * cyc.peak_balance:
                cyc.closed_at = t
                if cyc.outcome == "open":
                    cyc.outcome = "transferred"
                done.append(open_cycles.pop(mint))
    return done + list(open_cycles.values())


def compute_metrics(
    address: str,
    cycles: list[Cycle],
    *,
    txs_scanned: int,
    history_days: float,
    token_created_ms: dict[str, int],
    cfg: ScorerConfig,
    now: float | None = None,
) -> WalletMetrics:
    now = now or time.time()
    m = WalletMetrics(address=address, txs_scanned=txs_scanned, history_days=round(history_days, 2))
    for c in cycles:
        if c.outcome == "sold" and (c.sol_in < cfg.min_cycle_buy_sol * LAMPORTS_PER_SOL or c.roi > cfg.max_cycle_roi):
            c.outcome = "unpriced"
    unpriced = [c for c in cycles if c.outcome == "unpriced"]
    sold = [c for c in cycles if c.outcome == "sold" and c.sol_in > 0]
    transferred = [c for c in cycles if c.outcome == "transferred"]
    m.closed_trades = len(sold)

    if sold:
        rois = [c.roi for c in sold]
        holds = [c.hold_s for c in sold]
        wins = [c for c in sold if c.pnl > 0]
        gross_win = sum(c.pnl for c in wins)
        gross_loss = -sum(c.pnl for c in sold if c.pnl < 0)
        m.win_rate = len(wins) / len(sold)
        m.median_roi = statistics.median(rois)
        m.mean_roi = statistics.fmean(rois)
        m.avg_hold_s = statistics.fmean(holds)
        m.median_hold_s = statistics.median(holds)
        m.flip_ratio = sum(1 for c in sold if c.first_sell_delay_s < cfg.flip_threshold_s) / len(sold)
        m.profit_factor = gross_win / gross_loss if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
        m.top_trade_pnl_share = max(c.pnl for c in wins) / gross_win if gross_win > 0 else 0.0
        m.avg_buy_sol = statistics.fmean(c.sol_in for c in sold) / LAMPORTS_PER_SOL
        m.total_pnl_sol = sum(c.pnl for c in sold) / LAMPORTS_PER_SOL
        last = max(c.closed_at or c.opened_at for c in sold)
        m.days_since_last_trade = (now - last) / 86400
        snipes = [
            c for c in wins
            if c.mint in token_created_ms and c.opened_at - token_created_ms[c.mint] / 1000 <= cfg.sniper_window_s
        ]
        m.sniper_ratio = len(snipes) / len(wins) if wins else 0.0
    exits = len(sold) + len(transferred) + len(unpriced)
    m.transfer_out_ratio = len(transferred) / exits if exits else 0.0
    m.unpriced_ratio = len(unpriced) / exits if exits else 0.0
    m.trades_per_day = len(sold) / max(history_days, 1.0)

    r = m.rejections
    if m.closed_trades < cfg.min_closed_trades:
        r.append(f"only {m.closed_trades} closed trades (< {cfg.min_closed_trades})")
    if history_days < cfg.min_lookback_days and txs_scanned >= cfg.max_signatures_per_wallet:
        r.append(f"hyperactive: {txs_scanned} txs in {history_days:.1f} days (bot-like)")
    if sold:
        if m.win_rate < cfg.min_win_rate:
            r.append(f"win rate {m.win_rate:.0%} < {cfg.min_win_rate:.0%}")
        if m.win_rate > cfg.max_win_rate:
            r.append(f"win rate {m.win_rate:.0%} > {cfg.max_win_rate:.0%} (MEV/insider/dev — not replicable)")
        if m.median_hold_s < cfg.flip_threshold_s or m.flip_ratio > cfg.max_flip_ratio:
            r.append(
                f"BLACKLIST copy-trader farmer: median hold {m.median_hold_s:.0f}s, "
                f"{m.flip_ratio:.0%} of trades first-sold < {cfg.flip_threshold_s:.0f}s"
            )
        if m.avg_hold_s < cfg.min_avg_hold_s:
            r.append(f"avg hold {m.avg_hold_s:.0f}s < {cfg.min_avg_hold_s:.0f}s")
        if m.median_hold_s < cfg.min_median_hold_s:
            r.append(f"median hold {m.median_hold_s:.0f}s < {cfg.min_median_hold_s:.0f}s")
        if m.median_roi < cfg.min_median_roi:
            r.append(f"median ROI {m.median_roi:+.0%} < {cfg.min_median_roi:+.0%}")
        if m.profit_factor < cfg.min_profit_factor:
            r.append(f"profit factor {m.profit_factor:.2f} < {cfg.min_profit_factor}")
        if m.top_trade_pnl_share > cfg.max_top_trade_pnl_share:
            r.append(f"one trade = {m.top_trade_pnl_share:.0%} of profit (lottery, not skill)")
        if m.sniper_ratio > cfg.max_sniper_ratio:
            r.append(f"block-0 sniper: {m.sniper_ratio:.0%} of winners bought within {cfg.sniper_window_s:.0f}s of launch")
        if m.avg_buy_sol < cfg.min_avg_buy_sol:
            r.append(f"avg buy {m.avg_buy_sol:.3f} SOL (dust/bait sizes)")
        if m.trades_per_day > cfg.max_trades_per_day:
            r.append(f"{m.trades_per_day:.0f} trades/day (bot)")
        if m.days_since_last_trade > cfg.max_days_since_last_trade:
            r.append(f"inactive for {m.days_since_last_trade:.1f} days")
    if m.unpriced_ratio > cfg.max_unpriced_ratio:
        r.append(f"{m.unpriced_ratio:.0%} of trades paid off-wallet (bot vault) — buy signals uncopyable")
    if m.transfer_out_ratio > cfg.max_transfer_out_ratio:
        r.append(f"{m.transfer_out_ratio:.0%} of exits were transfers to other wallets (insider/bundler)")

    m.passed = not r
    m.score = round(score_wallet(m), 2) if m.passed else 0.0
    return m


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_wallet(m: WalletMetrics) -> float:
    """0-100. Rewards a robust *typical* trade (median ROI) and consistency over raw PnL."""
    return 100 * (
        0.35 * _clip(m.median_roi / 0.60)
        + 0.25 * _clip((m.profit_factor - 1.0) / 3.0)
        + 0.15 * _clip((m.win_rate - 0.5) / 0.32)
        + 0.10 * _clip(m.closed_trades / 80)
        + 0.10 * _clip(m.median_hold_s / 1800)
        + 0.05 * _clip(1 - m.sniper_ratio / 0.3)
    )


# ---------------------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------------------
class WalletScorer:
    def __init__(self, settings: Settings, rpc: SolanaRpc, dex: DexScreenerClient, jupiter: JupiterClient) -> None:
        self.s = settings
        self.cfg = settings.scorer
        self.rpc = rpc
        self.dex = dex
        self.jupiter = jupiter
        self.cache_dir = settings.data_dir / "cache" / "tx"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._sem = asyncio.Semaphore(8)

    async def signatures(self, wallet: str) -> list[dict]:
        cutoff = time.time() - self.cfg.lookback_days * 86400
        out: list[dict] = []
        before = None
        while len(out) < self.cfg.max_signatures_per_wallet:
            page = await self.rpc.get_signatures_for_address(wallet, limit=1000, before=before)
            if not page:
                break
            for row in page:
                if row.get("blockTime") and row["blockTime"] < cutoff:
                    return out[: self.cfg.max_signatures_per_wallet]
                if row.get("err") is None:
                    out.append(row)
            before = page[-1]["signature"]
            if len(page) < 1000:
                break
        return out[: self.cfg.max_signatures_per_wallet]

    async def transaction(self, sig: str) -> dict | None:
        path = self.cache_dir / f"{sig}.json"
        if path.exists():
            return json.loads(path.read_text())
        async with self._sem:
            tx = await self.rpc.get_transaction(sig, retries=3)
        if tx is not None:
            path.write_text(json.dumps(tx, separators=(",", ":")))
        return tx

    async def score(self, wallet: str, usd_per_sol: float) -> WalletMetrics:
        sigs = await self.signatures(wallet)
        times = [r["blockTime"] for r in sigs if r.get("blockTime")]
        history_days = (time.time() - min(times)) / 86400 if times else 0.0
        if len(sigs) >= self.cfg.max_signatures_per_wallet and history_days < self.cfg.min_lookback_days:
            # Pools, routers and HFT bots: reject before spending thousands of RPC calls on them.
            return compute_metrics(wallet, [], txs_scanned=len(sigs), history_days=history_days,
                                   token_created_ms={}, cfg=self.cfg)
        txs = await asyncio.gather(*(self.transaction(r["signature"]) for r in sigs))
        events: list[tuple[int, int, str, object]] = []
        for tx in txs:
            if not tx or not tx.get("blockTime"):
                continue
            t, slot = int(tx["blockTime"]), int(tx.get("slot", 0))
            for ev in extract_swaps(tx, wallet):
                events.append((t, slot, "swap", ev))
            for mint, amount in extract_transfers_out(tx, wallet).items():
                after = _post_balance(tx, wallet, mint)
                events.append((t, slot, "xfer", (mint, amount, after)))
        events.sort(key=lambda e: (e[0], e[1]))
        cycles = build_cycles(events, usd_per_sol)

        winners = sorted({c.mint for c in cycles if c.outcome == "sold" and c.pnl > 0})
        created: dict[str, int] = {}
        if winners:
            try:
                pairs = await self.dex.pairs_for_tokens(winners, timeout=10.0, retries=3)
                for mint, plist in pairs.items():
                    ts = token_created_at_ms(plist)
                    if ts:
                        created[mint] = ts
            except Exception as exc:
                log.warning("token launch times unavailable (%s); sniper check skipped for %s", exc, wallet[:6])
        return compute_metrics(
            wallet, cycles, txs_scanned=len(sigs), history_days=history_days, token_created_ms=created, cfg=self.cfg
        )


def _post_balance(tx: dict, wallet: str, mint: str) -> int:
    total = 0
    for row in tx["meta"].get("postTokenBalances") or []:
        if row.get("owner") == wallet and row.get("mint") == mint:
            total += int(row["uiTokenAmount"]["amount"])
    return total


def read_seed_wallets(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — put one wallet address per line (see docs/SEED_WALLETS.md)")
    out: list[str] = []
    for line in path.read_text().splitlines():
        addr = line.split("#", 1)[0].strip()
        if not addr:
            continue
        try:
            Pubkey.from_string(addr)
        except ValueError:
            log.warning("skipping invalid address %r", addr)
            continue
        if addr not in out:
            out.append(addr)
    return out


async def run_scorer(settings: Settings, rpc: SolanaRpc, dex: DexScreenerClient, jupiter: JupiterClient) -> list[WalletMetrics]:
    wallets = read_seed_wallets(settings.seed_wallets_path)
    log.info("scoring %d candidate wallets over %d days", len(wallets), settings.scorer.lookback_days)
    q = await jupiter.quote(WSOL_MINT, USDC_MINT, LAMPORTS_PER_SOL, 50)
    usd_per_sol = q.out_amount / 1e6
    scorer = WalletScorer(settings, rpc, dex, jupiter)
    results: list[WalletMetrics] = []
    for i, w in enumerate(wallets, 1):
        try:
            m = await scorer.score(w, usd_per_sol)
        except Exception as exc:
            log.error("[%d/%d] %s failed: %s", i, len(wallets), w, exc)
            continue
        verdict = f"PASS score={m.score:.1f}" if m.passed else "REJECT: " + "; ".join(m.rejections[:3])
        log.info(
            "[%d/%d] %s… trades=%d win=%.0f%% medROI=%+.0f%% medHold=%.0fm PF=%.2f | %s",
            i, len(wallets), w[:8], m.closed_trades, m.win_rate * 100, m.median_roi * 100,
            m.median_hold_s / 60, m.profit_factor, verdict,
        )
        results.append(m)

    approved = sorted((m for m in results if m.passed), key=lambda m: m.score, reverse=True)[: settings.scorer.top_n]
    save_json(
        settings.approved_wallets_path,
        {
            "generated_at": int(time.time()),
            "lookback_days": settings.scorer.lookback_days,
            "wallets": [{"address": m.address, "score": m.score, "metrics": asdict(m)} for m in approved],
        },
    )
    save_json(settings.data_dir / "scorer_report.json", [asdict(m) for m in results])
    log.info("approved %d wallets -> %s (full report: %s)", len(approved), settings.approved_wallets_path,
             settings.data_dir / "scorer_report.json")
    return results
