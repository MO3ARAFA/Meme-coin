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
from .constants import JITO_TIP_ACCOUNTS, LAMPORTS_PER_SOL, USDC_MINT, WSOL_MINT
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
    first_buy_sol: float = 0.0  # lamports of the opening buy: the size of the signal we would copy
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
    nonscratch_median_roi: float = 0.0
    trimmed_mean_roi: float = 0.0
    median_buy_sol: float = 0.0  # baseline for live bait-size detection
    replay_trades: int = 0
    replay_win_rate: float = 0.0
    replay_profit_factor: float = 0.0
    replay_expectancy: float = 0.0  # mean net return per copied trade, after latency + fees
    token_recipients: int = 0
    counterparties: list[str] = field(default_factory=list)
    link_group: int | None = None
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
                    cyc.first_buy_sol = to_lamports(ev)
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
    counterparties: set[str] | None = None,
    token_recipients: int = 0,
) -> WalletMetrics:
    now = now or time.time()
    m = WalletMetrics(address=address, txs_scanned=txs_scanned, history_days=round(history_days, 2))
    m.counterparties = sorted(counterparties or ())
    m.token_recipients = token_recipients
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
        m.median_buy_sol = statistics.median(c.first_buy_sol for c in sold) / LAMPORTS_PER_SOL
        meaningful = [x for x in rois if abs(x) > cfg.scratch_band]
        m.nonscratch_median_roi = statistics.median(meaningful) if meaningful else 0.0
        m.trimmed_mean_roi = trimmed_mean(rois, cfg.trimmed_top_frac)
        copied = replay_copy_returns(sold, cfg, m.median_buy_sol * LAMPORTS_PER_SOL)
        m.replay_trades = len(copied)
        if copied:
            gains, losses = sum(x for x in copied if x > 0), -sum(x for x in copied if x < 0)
            m.replay_win_rate = sum(1 for x in copied if x > 0) / len(copied)
            m.replay_profit_factor = gains / losses if losses > 0 else (99.0 if gains > 0 else 0.0)
            m.replay_expectancy = statistics.fmean(copied)
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
        roi_ok = m.nonscratch_median_roi >= cfg.min_median_roi or (
            m.trimmed_mean_roi >= cfg.min_trimmed_mean_roi and m.profit_factor >= cfg.alt_min_profit_factor
        )
        if not roi_ok:
            r.append(
                f"typical trade too weak: non-scratch median ROI {m.nonscratch_median_roi:+.0%} "
                f"(< {cfg.min_median_roi:+.0%}) and trimmed mean {m.trimmed_mean_roi:+.0%} / PF {m.profit_factor:.2f} "
                f"(< {cfg.min_trimmed_mean_roi:+.0%} / {cfg.alt_min_profit_factor})"
            )
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
        if m.replay_trades < cfg.replay_min_trades:
            r.append(f"only {m.replay_trades} copyable trades to replay (< {cfg.replay_min_trades})")
        elif m.replay_profit_factor < cfg.replay_min_profit_factor or m.replay_expectancy <= cfg.replay_min_expectancy:
            r.append(
                f"edge dies under copy latency: replay PF {m.replay_profit_factor:.2f} (< {cfg.replay_min_profit_factor}), "
                f"expectancy {m.replay_expectancy:+.1%}/trade after {cfg.replay_entry_penalty:.1%} entry penalty "
                f"+ {cfg.replay_leg_fee:.1%}/leg fees"
            )
    if m.unpriced_ratio > cfg.max_unpriced_ratio:
        r.append(f"{m.unpriced_ratio:.0%} of trades paid off-wallet (bot vault) — buy signals uncopyable")
    if m.token_recipients >= cfg.max_token_recipients:
        r.append(f"shipped tokens to {m.token_recipients} different wallets without selling (feeder/sybil)")
    if m.transfer_out_ratio > cfg.max_transfer_out_ratio:
        r.append(f"{m.transfer_out_ratio:.0%} of exits were transfers to other wallets (insider/bundler)")

    m.passed = not r
    m.score = round(score_wallet(m), 2) if m.passed else 0.0
    return m


def trimmed_mean(values: list[float], top_frac: float) -> float:
    """Mean after dropping the top `top_frac` of values (the lottery tickets)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    drop = int(len(ordered) * top_frac)
    kept = ordered[: len(ordered) - drop] if drop else ordered
    return statistics.fmean(kept)


def copy_return(whale_roi: float, cfg: ScorerConfig) -> float:
    """What a whale trade returns to US: we enter `replay_entry_penalty` worse (copy latency,
    other bots ahead of us), pay our full per-leg fee cap on both legs, optional exit penalty."""
    fee = 1.0 - cfg.replay_leg_fee
    return (1.0 + whale_roi) * fee * fee * (1.0 - cfg.replay_exit_penalty) / (1.0 + cfg.replay_entry_penalty) - 1.0


def replay_copy_returns(sold: list[Cycle], cfg: ScorerConfig, median_buy_lamports: float) -> list[float]:
    """Latency-adjusted replay over the trades our live gate would actually have copied:
    opening buy >= the gate's minimum and not a bait-sized outlier for this wallet."""
    floor = max(cfg.replay_min_buy_sol * LAMPORTS_PER_SOL, cfg.bait_size_frac * median_buy_lamports)
    return [copy_return(c.roi, cfg) for c in sold if c.first_buy_sol >= floor]


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_wallet(m: WalletMetrics) -> float:
    """0-100. Ranks on what WE would earn copying (replay), then robustness and consistency."""
    return 100 * (
        0.35 * _clip(m.replay_expectancy / 0.25)
        + 0.25 * _clip((m.replay_profit_factor - 1.0) / 2.0)
        + 0.10 * _clip(m.nonscratch_median_roi / 0.60)
        + 0.10 * _clip((m.win_rate - 0.5) / 0.32)
        + 0.10 * _clip(m.replay_trades / 60)
        + 0.05 * _clip(m.median_hold_s / 1800)
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

    async def history(self, wallet: str, sigs: list[dict], usd_per_sol: float) -> tuple[list[Cycle], set[str], set[str]]:
        """Trade cycles plus link evidence: (cycles, SOL counterparties, token recipients)."""
        txs = await asyncio.gather(*(self.transaction(r["signature"]) for r in sigs))
        events: list[tuple[int, int, str, object]] = []
        sol_links: set[str] = set()
        recipients: set[str] = set()
        min_link = int(self.cfg.min_link_sol * LAMPORTS_PER_SOL)
        for tx in txs:
            if not tx or not tx.get("blockTime"):
                continue
            t, slot = int(tx["blockTime"]), int(tx.get("slot", 0))
            swaps = extract_swaps(tx, wallet)
            for ev in swaps:
                events.append((t, slot, "swap", ev))
            moved = extract_transfers_out(tx, wallet)
            for mint, amount in moved.items():
                after = _post_balance(tx, wallet, mint)
                events.append((t, slot, "xfer", (mint, amount, after)))
                recipients |= token_recipients(tx, wallet, mint)
            if not swaps:  # router fees inside swaps are not relationships
                sol_links |= sol_counterparties(tx, wallet, min_link)
        events.sort(key=lambda e: (e[0], e[1]))
        return build_cycles(events, usd_per_sol), sol_links, recipients

    async def score(self, wallet: str, usd_per_sol: float) -> WalletMetrics:
        sigs = await self.signatures(wallet)
        times = [r["blockTime"] for r in sigs if r.get("blockTime")]
        history_days = (time.time() - min(times)) / 86400 if times else 0.0
        if len(sigs) >= self.cfg.max_signatures_per_wallet and history_days < self.cfg.min_lookback_days:
            # Pools, routers and HFT bots: reject before spending thousands of RPC calls on them.
            return compute_metrics(wallet, [], txs_scanned=len(sigs), history_days=history_days,
                                   token_created_ms={}, cfg=self.cfg)
        cycles, sol_links, recipients = await self.history(wallet, sigs, usd_per_sol)

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
            wallet, cycles, txs_scanned=len(sigs), history_days=history_days, token_created_ms=created, cfg=self.cfg,
            counterparties=sol_links | recipients, token_recipients=len(recipients),
        )


def _all_instructions(tx: dict) -> list[dict]:
    out = list(tx["transaction"]["message"].get("instructions") or [])
    for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
        out.extend(inner.get("instructions") or [])
    return out


def sol_counterparties(tx: dict, wallet: str, min_lamports: int) -> set[str]:
    """Wallets that sent SOL to / received SOL from `wallet` directly (funding links)."""
    out: set[str] = set()
    for ix in _all_instructions(tx):
        parsed = ix.get("parsed") if isinstance(ix, dict) else None
        if ix.get("program") != "system" or not isinstance(parsed, dict) or parsed.get("type") != "transfer":
            continue
        info = parsed.get("info") or {}
        if int(info.get("lamports", 0)) < min_lamports:
            continue
        src, dst = info.get("source"), info.get("destination")
        other = dst if src == wallet else src if dst == wallet else None
        if other and other not in JITO_TIP_ACCOUNTS:
            out.add(other)
    return out


def token_recipients(tx: dict, wallet: str, mint: str) -> set[str]:
    """Owners whose balance of `mint` grew in a tx where `wallet` shipped it out."""
    meta = tx["meta"]
    pre: dict[str, int] = {}
    post: dict[str, int] = {}
    for rows, acc in ((meta.get("preTokenBalances") or [], pre), (meta.get("postTokenBalances") or [], post)):
        for row in rows:
            if row.get("mint") == mint and row.get("owner") and row["owner"] != wallet:
                acc[row["owner"]] = acc.get(row["owner"], 0) + int(row["uiTokenAmount"]["amount"])
    return {o for o, amt in post.items() if amt > pre.get(o, 0)}


def link_groups(metrics: list[WalletMetrics]) -> dict[str, int]:
    """Union-find over direct SOL/token links between scored wallets. Wallets in one group are
    treated as one operator: only one may be approved, and they never count as independent
    confirmation for each other in cluster consensus."""
    addrs = {m.address for m in metrics}
    parent = {a: a for a in addrs}

    def find(a: str) -> str:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for m in metrics:
        for other in m.counterparties:
            if other in addrs:
                parent[find(m.address)] = find(other)
    roots = sorted({find(a) for a in addrs})
    ids = {r: i for i, r in enumerate(roots)}
    return {a: ids[find(a)] for a in addrs}


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


def read_quarantined(path: Path) -> list[dict]:
    """Wallets the live engine quarantined as copy-trader hunters survive every re-score."""
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data.get("quarantined", []) if isinstance(data, dict) else []


def select_approved(results: list[WalletMetrics], top_n: int, quarantined: set[str]) -> list[WalletMetrics]:
    """Best passing wallet per link group (one operator = one slot), never a quarantined one."""
    groups = link_groups(results)
    for m in results:
        m.link_group = groups.get(m.address)
    # A quarantined hunter taints its whole link group: its sibling wallets are the same operator.
    tainted = {groups[a] for a in quarantined if a in groups}
    approved: list[WalletMetrics] = []
    taken: dict[int, str] = {}
    for m in sorted((m for m in results if m.passed), key=lambda m: m.score, reverse=True):
        if m.address in quarantined or m.link_group in tainted:
            m.passed = False
            m.rejections.append("quarantined copy-trader hunter (or linked to one)")
            continue
        if m.link_group in taken:
            m.passed = False
            m.rejections.append(f"same operator as approved {taken[m.link_group][:8]}… (direct SOL/token links)")
            continue
        taken[m.link_group] = m.address
        approved.append(m)
    return approved[:top_n]


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
            "[%d/%d] %s… trades=%d win=%.0f%% nsMedROI=%+.0f%% medHold=%.0fm PF=%.2f | replay n=%d PF=%.2f exp=%+.1f%% | %s",
            i, len(wallets), w[:8], m.closed_trades, m.win_rate * 100, m.nonscratch_median_roi * 100,
            m.median_hold_s / 60, m.profit_factor, m.replay_trades, m.replay_profit_factor,
            m.replay_expectancy * 100, verdict,
        )
        results.append(m)

    quarantined = read_quarantined(settings.approved_wallets_path)
    approved = select_approved(results, settings.scorer.top_n, {q["address"] for q in quarantined})
    save_json(
        settings.approved_wallets_path,
        {
            "generated_at": int(time.time()),
            "lookback_days": settings.scorer.lookback_days,
            "wallets": [
                {
                    "address": m.address,
                    "score": m.score,
                    "median_buy_sol": round(m.median_buy_sol, 4),
                    "link_group": m.link_group,
                    "metrics": asdict(m),
                }
                for m in approved
            ],
            "quarantined": quarantined,
        },
    )
    save_json(settings.data_dir / "scorer_report.json", [asdict(m) for m in results])
    log.info("approved %d wallets -> %s (full report: %s)", len(approved), settings.approved_wallets_path,
             settings.data_dir / "scorer_report.json")
    return results
