"""`harvest` — cross-token, mid-wave discovery of candidate wallets for the scorer.

Sampling only the latest transactions of a pool mostly finds arbitrage/MEV bots, because
they dominate any short recent window. This harvester instead:

  1. discovers 50–80 established memecoins (liquidity, age 1–14 days, 24h volume) from
     GeckoTerminal's trending/top-volume pools plus DexScreener search;
  2. samples each pool's history EVENLY across several thousand signatures (mid-wave, not
     just the last minute) and records which wallets traded which tokens;
  3. pre-screens candidates cheaply: the address must be a plain system-owned wallet (pools,
     routers and program vaults are owned by programs) trading <= 80 tx/day;
  4. deep-checks the survivors' own recent history (shared tx cache with `score`) and keeps
     only wallets with REALIZED profitable exits in >= 2 different tokens;
  5. writes the top 40 to `seed_wallets.txt` for `python main.py score`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field

import httpx

from .config import Settings
from .constants import LAMPORTS_PER_SOL, NON_MEME_MINTS, STABLE_MINTS, SYSTEM_PROGRAM, USDC_MINT, WSOL_MINT
from .dexscreener import DexScreenerClient
from .http_utils import RateLimiter, request_json
from .jupiter import JupiterClient
from .solana_rpc import SolanaRpc
from .state import save_json
from .tx_parser import extract_swaps
from .wallet_scorer import WalletScorer

log = logging.getLogger(__name__)

GECKO = "https://api.geckoterminal.com/api/v2/networks/solana"
SEARCH_TERMS = (
    "pump pumpswap raydium meteora bonk cat dog pepe ai trump frog moon inu wif meme coin chad based elon "
    "grok baby king doge shib wojak monkey ape bear bull pig duck fish penguin panda tiger wolf rocket gold "
    "money cash god america china japan anime girl fart lol agent bot gpt claude sigma giga"
).split()


@dataclass
class HarvestToken:
    mint: str
    symbol: str
    pool: str
    dex: str
    liquidity_usd: float
    volume_h24_usd: float
    age_days: float


@dataclass
class Candidate:
    address: str
    tokens: dict[str, dict] = field(default_factory=dict)  # symbol -> {"buys","sells","sol"}
    tx_per_day: float = 0.0
    profitable_tokens: int = 0
    closed_trades: int = 0
    win_rate: float = 0.0
    realized_pnl_sol: float = 0.0
    status: str = "candidate"

    @property
    def sampled_sells(self) -> int:
        return sum(t["sells"] for t in self.tokens.values())

    @property
    def sampled_sol(self) -> float:
        return sum(t["sol"] for t in self.tokens.values())


# ---------------------------------------------------------------------------------------
# 1. Token discovery
# ---------------------------------------------------------------------------------------
async def discover_tokens(client: httpx.AsyncClient, settings: Settings) -> list[HarvestToken]:
    cfg = settings.harvest
    mints: set[str] = set()
    gecko = RateLimiter(0.45, burst=2)  # public tier: 30 calls/min
    for path in ("trending_pools?duration=24h", "trending_pools?duration=6h", "pools?sort=h24_volume_usd_desc"):
        for page in range(1, 11):
            sep = "&" if "?" in path else "?"
            try:
                data = await request_json(client, "GET", f"{GECKO}/{path}{sep}page={page}", limiter=gecko, retries=2)
            except Exception as exc:
                log.debug("geckoterminal %s p%d: %s", path, page, exc)
                break
            for pool in data.get("data", []):
                base = pool["relationships"]["base_token"]["data"]["id"].removeprefix("solana_")
                mints.add(base)
    dex_lim = RateLimiter(settings.dexscreener_rps, burst=2)
    for term in SEARCH_TERMS:
        try:
            data = await request_json(client, "GET", f"{settings.dexscreener_base_url}/latest/dex/search",
                                      params={"q": term}, limiter=dex_lim, retries=1)
        except Exception:
            continue
        for p in data.get("pairs") or []:
            if p.get("chainId") == "solana":
                mints.add(p["baseToken"]["address"])
    mints -= NON_MEME_MINTS
    log.info("discovery: %d candidate mints (GeckoTerminal + DexScreener)", len(mints))

    now_ms = time.time() * 1000
    tokens: list[HarvestToken] = []
    ordered = sorted(mints)
    for i in range(0, len(ordered), 30):
        chunk = ordered[i : i + 30]
        try:
            rows = await request_json(client, "GET", f"{settings.dexscreener_base_url}/tokens/v1/solana/{','.join(chunk)}",
                                      limiter=dex_lim, retries=2)
        except Exception as exc:
            log.debug("dexscreener batch failed: %s", exc)
            continue
        by_mint: dict[str, list[dict]] = defaultdict(list)
        for p in rows or []:
            if p.get("chainId") == "solana":
                by_mint[p["baseToken"]["address"]].append(p)
        for mint, pairs in by_mint.items():
            created = [p["pairCreatedAt"] for p in pairs if p.get("pairCreatedAt")]
            if not created:
                continue
            age = (now_ms - min(created)) / 86_400_000  # token launch = earliest pair
            # Our parser prices swaps in SOL/stables: sample the most liquid such pool.
            priced = [p for p in pairs if p["quoteToken"]["address"] in {WSOL_MINT, *STABLE_MINTS}
                      and (p.get("liquidity") or {}).get("usd")]
            if not priced:
                continue
            best = max(priced, key=lambda p: p["liquidity"]["usd"])
            vol = sum(float((p.get("volume") or {}).get("h24") or 0) for p in pairs)
            liq = float(best["liquidity"]["usd"])
            if liq >= cfg.min_liquidity_usd and cfg.min_age_days <= age <= cfg.max_age_days and vol >= cfg.min_volume_h24_usd:
                tokens.append(HarvestToken(mint, best["baseToken"].get("symbol", "?"), best["pairAddress"],
                                           best.get("dexId", ""), liq, vol, round(age, 1)))
    tokens.sort(key=lambda t: t.volume_h24_usd, reverse=True)
    return tokens[: cfg.max_tokens]


# ---------------------------------------------------------------------------------------
# 2. Mid-wave pool sampling
# ---------------------------------------------------------------------------------------
def evenly_spaced(items: list, n: int) -> list:
    if len(items) <= n:
        return list(items)
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


async def sample_pool(rpc: SolanaRpc, scorer: WalletScorer, token: HarvestToken, settings: Settings,
                      usd_per_sol: float) -> dict[str, dict]:
    """wallet -> {"buys","sells","sol"} for fee-paying traders of `token` across the sample."""
    cfg = settings.harvest
    sigs: list[dict] = []
    before = None
    for _ in range(cfg.signature_pages):
        page = await rpc.get_signatures_for_address(token.pool, limit=1000, before=before)
        sigs += [r for r in page if r.get("err") is None]
        if len(page) < 1000:
            break
        before = page[-1]["signature"]
    picked = evenly_spaced(sigs, cfg.sample_per_token)
    txs = await asyncio.gather(*(scorer.transaction(r["signature"]) for r in picked))
    out: dict[str, dict] = {}
    min_lamports = cfg.min_swap_sol * LAMPORTS_PER_SOL
    for tx in txs:
        if not tx:
            continue
        keys = tx["transaction"]["message"]["accountKeys"]
        payer = keys[0]["pubkey"] if isinstance(keys[0], dict) else keys[0]
        if payer == token.pool:
            continue
        for ev in extract_swaps(tx, payer):
            if ev.mint != token.mint:
                continue
            lamports = ev.quote_amount_raw if ev.is_sol_quoted else ev.quote_amount_raw / 1e6 / usd_per_sol * LAMPORTS_PER_SOL
            if lamports < min_lamports:
                continue
            row = out.setdefault(payer, {"buys": 0, "sells": 0, "sol": 0.0})
            row["buys" if ev.side.value == "BUY" else "sells"] += 1
            row["sol"] += lamports / LAMPORTS_PER_SOL
    return out


def rank_candidates(cands: dict[str, Candidate]) -> list[Candidate]:
    """Wallets seen in more tokens first, then those with sampled exits, then size."""
    return sorted(cands.values(), key=lambda c: (len(c.tokens), c.sampled_sells, c.sampled_sol), reverse=True)


# ---------------------------------------------------------------------------------------
# 3-4. Pre-screen and deep check
# ---------------------------------------------------------------------------------------
async def prescreen(rpc: SolanaRpc, cands: list[Candidate], settings: Settings) -> dict[str, list[dict]]:
    """Drop program-owned accounts (pools, vaults, routers) and hyperactive bots.
    Returns address -> recent signatures for the survivors (reused by the deep check)."""
    cfg = settings.harvest
    accounts = await rpc.get_multiple_accounts([c.address for c in cands])
    sem = asyncio.Semaphore(6)
    survivors: dict[str, list[dict]] = {}

    async def check(c: Candidate, acct: dict | None) -> None:
        if acct is None or acct.get("owner") != SYSTEM_PROGRAM or acct.get("executable"):
            c.status = "program-owned account (pool/vault/router)"
            return
        async with sem:
            sigs = await rpc.get_signatures_for_address(c.address, limit=1000)
        times = [r["blockTime"] for r in sigs if r.get("blockTime")]
        if len(sigs) < 20 or not times:
            c.status = "too little history"
            return
        span_days = max((time.time() - min(times)) / 86400, 1 / 24)
        c.tx_per_day = len(sigs) / span_days
        if c.tx_per_day > cfg.max_tx_per_day:
            c.status = f"hyperactive ({c.tx_per_day:.0f} tx/day)"
            return
        c.status = "prescreened"
        survivors[c.address] = [r for r in sigs if r.get("err") is None]

    await asyncio.gather(*(check(c, a) for c, a in zip(cands, accounts)))
    return survivors


async def deep_check(scorer: WalletScorer, c: Candidate, sigs: list[dict], settings: Settings, usd_per_sol: float) -> None:
    """Realized-profit check on the wallet's own recent history, across ALL tokens it traded."""
    scfg = settings.scorer
    cycles = (await scorer.history(c.address, sigs[: settings.harvest.deep_history_txs], usd_per_sol)).cycles
    sold = [
        cy for cy in cycles
        if cy.outcome == "sold"
        and cy.sol_in >= scfg.min_cycle_buy_sol * LAMPORTS_PER_SOL
        and cy.roi <= scfg.max_cycle_roi  # vault-funded "free" buys are not real profit
    ]
    c.closed_trades = len(sold)
    c.win_rate = sum(1 for cy in sold if cy.pnl > 0) / len(sold) if sold else 0.0
    c.realized_pnl_sol = sum(cy.pnl for cy in sold) / LAMPORTS_PER_SOL
    c.profitable_tokens = len({cy.mint for cy in sold if cy.pnl > 0})
    c.status = "deep-checked"


async def run_harvest(settings: Settings, client: httpx.AsyncClient, rpc: SolanaRpc, dex: DexScreenerClient,
                      jupiter: JupiterClient) -> list[Candidate]:
    cfg = settings.harvest
    q = await jupiter.quote(WSOL_MINT, USDC_MINT, LAMPORTS_PER_SOL, 50)
    usd_per_sol = q.out_amount / 1e6
    scorer = WalletScorer(settings, rpc, dex, jupiter)

    tokens = await discover_tokens(client, settings)
    log.info("harvesting %d tokens (liq >= $%.0fk, age %.0f-%.0fd, vol24 >= $%.0fk)", len(tokens),
             cfg.min_liquidity_usd / 1e3, cfg.min_age_days, cfg.max_age_days, cfg.min_volume_h24_usd / 1e3)

    cands: dict[str, Candidate] = {}
    for i, tok in enumerate(tokens, 1):
        try:
            traders = await sample_pool(rpc, scorer, tok, settings, usd_per_sol)
        except Exception as exc:
            log.warning("[%d/%d] %s sampling failed: %s", i, len(tokens), tok.symbol, exc)
            continue
        for w, row in traders.items():
            cands.setdefault(w, Candidate(w)).tokens[tok.symbol] = row
        log.info("[%d/%d] %-10s %-9s liq=$%-9.0f age=%4.1fd -> %d traders", i, len(tokens), tok.symbol[:10],
                 tok.dex, tok.liquidity_usd, tok.age_days, len(traders))

    ranked = rank_candidates(cands)
    to_screen = ranked[: cfg.max_deep_checks * 4]
    log.info("%d distinct traders; pre-screening top %d", len(ranked), len(to_screen))
    survivors = await prescreen(rpc, to_screen, settings)
    deep = [c for c in to_screen if c.address in survivors][: cfg.max_deep_checks]
    log.info("%d passed pre-screen; deep-checking %d", len(survivors), len(deep))
    for i, c in enumerate(deep, 1):
        try:
            await deep_check(scorer, c, survivors[c.address], settings, usd_per_sol)
        except Exception as exc:
            c.status = f"deep check failed: {exc}"
            continue
        log.info("  [%d/%d] %s… %d tx/day, %d closed, win %.0f%%, profitable in %d tokens, pnl %+.2f SOL",
                 i, len(deep), c.address[:8], c.tx_per_day, c.closed_trades, c.win_rate * 100,
                 c.profitable_tokens, c.realized_pnl_sol)

    # Net-profitable wallets first: "profitable in 20 tokens" means little from a spray trader
    # who is net negative.
    winners = sorted((c for c in deep if c.profitable_tokens >= cfg.min_profitable_tokens),
                     key=lambda c: (c.realized_pnl_sol > 0, c.profitable_tokens, c.realized_pnl_sol),
                     reverse=True)[: cfg.top_n]
    lines = [
        f"# harvest {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}: {len(tokens)} tokens, "
        f"{len(ranked)} traders, {len(survivors)} pre-screened, {len(winners)} multi-token winners",
        "# Columns after '#': tokens with realized profit / closed trades / win rate / realized PnL / tx per day",
    ]
    lines += [
        f"{c.address}  # {c.profitable_tokens} profitable tokens, {c.closed_trades} closed, "
        f"win {c.win_rate:.0%}, {c.realized_pnl_sol:+.2f} SOL, {c.tx_per_day:.0f} tx/day"
        for c in winners
    ]
    settings.seed_wallets_path.write_text("\n".join(lines) + "\n")
    save_json(settings.data_dir / "harvest_report.json", {
        "tokens": [asdict(t) for t in tokens],
        "candidates": [asdict(c) for c in ranked[: cfg.max_deep_checks * 4]],
        "winners": [c.address for c in winners],
    })
    log.info("wrote %d multi-token winners -> %s", len(winners), settings.seed_wallets_path)
    return winners


# ---------------------------------------------------------------------------------------
# Co-buyer graph discovery (`harvest --co-buyers`)
# ---------------------------------------------------------------------------------------
async def co_buyers_of(rpc: SolanaRpc, scorer: WalletScorer, seed: str, settings: Settings,
                       usd_per_sol: float) -> dict[str, dict]:
    """Wallets that bought the seed's profitable tokens up to `window_s` BEFORE the seed did.

    Only leaders count. Wallets buying right AFTER a tracked whale are mostly copy-bots — the
    opposite of what we want — and wallets in the seed's own slot (or the one before) are
    bundle partners, which the cabal check exists to reject.
    """
    scfg, hcfg = settings.scorer, settings.harvest
    max_trades, window_s, sample = hcfg.co_buyer_trades, hcfg.co_buyer_window_s, hcfg.co_buyer_sample
    hist = await scorer.history(seed, await scorer.signatures(seed), usd_per_sol)
    winners = sorted(
        (c for c in hist.cycles if c.outcome == "sold" and c.pnl > 0 and c.first_buy_sig
         and c.sol_in >= scfg.min_cycle_buy_sol * LAMPORTS_PER_SOL and c.roi <= scfg.max_cycle_roi),
        key=lambda c: c.pnl, reverse=True,
    )[:max_trades]
    min_lamports = settings.harvest.min_swap_sol * LAMPORTS_PER_SOL
    found: dict[str, dict] = {}
    for cyc in winners:
        try:
            rows = await rpc.get_signatures_for_address(cyc.mint, limit=500, before=cyc.first_buy_sig)
        except Exception as exc:
            log.debug("co-buyer sigs %s: %s", cyc.mint[:6], exc)
            continue
        window = [r for r in rows if r.get("err") is None and r.get("blockTime")
                  and r["blockTime"] >= cyc.opened_at - window_s and r.get("slot", 0) < cyc.first_buy_slot - 1]
        txs = await asyncio.gather(*(scorer.transaction(r["signature"]) for r in evenly_spaced(window, sample)))
        for tx in txs:
            if not tx:
                continue
            keys = tx["transaction"]["message"]["accountKeys"]
            payer = keys[0]["pubkey"] if isinstance(keys[0], dict) else keys[0]
            if payer == seed:
                continue
            for ev in extract_swaps(tx, payer):
                lamports = ev.quote_amount_raw if ev.is_sol_quoted else ev.quote_amount_raw / 1e6 / usd_per_sol * LAMPORTS_PER_SOL
                if ev.mint == cyc.mint and ev.side.value == "BUY" and lamports >= min_lamports:
                    row = found.setdefault(payer, {})
                    lead = cyc.opened_at - int(tx["blockTime"])
                    row[cyc.mint] = {"buys": 1, "sells": 0, "sol": lamports / LAMPORTS_PER_SOL, "lead_s": lead}
        log.info("  seed %s… token %s… (+%.2f SOL): %d leader buys in the %.0f min before",
                 seed[:6], cyc.mint[:6], cyc.pnl / LAMPORTS_PER_SOL, len(window), window_s / 60)
    return found


async def run_co_buyer_harvest(settings: Settings, rpc: SolanaRpc, dex: DexScreenerClient, jupiter: JupiterClient,
                               seeds: list[str]) -> list[Candidate]:
    cfg = settings.harvest
    q = await jupiter.quote(WSOL_MINT, USDC_MINT, LAMPORTS_PER_SOL, 50)
    usd_per_sol = q.out_amount / 1e6
    scorer = WalletScorer(settings, rpc, dex, jupiter)
    cands: dict[str, Candidate] = {}
    for seed in seeds:
        log.info("co-buyer discovery around %s…", seed[:8])
        for wallet, tokens in (await co_buyers_of(rpc, scorer, seed, settings, usd_per_sol)).items():
            cands.setdefault(wallet, Candidate(wallet)).tokens.update(tokens)
    # Leaders on >= 2 of the seed's winners first, then the largest single-token leaders; the
    # deep check verifies multi-token profit on each wallet's own history either way.
    ranked = rank_candidates(cands)
    to_screen = ranked[: cfg.max_deep_checks * 2]
    log.info("%d co-buyers found (%d on >= 2 winning tokens); pre-screening %d",
             len(cands), sum(1 for c in cands.values() if len(c.tokens) >= 2), len(to_screen))
    survivors = await prescreen(rpc, to_screen, settings)
    deep = [c for c in to_screen if c.address in survivors][: cfg.max_deep_checks]
    for i, c in enumerate(deep, 1):
        try:
            await deep_check(scorer, c, survivors[c.address], settings, usd_per_sol)
        except Exception as exc:
            c.status = f"deep check failed: {exc}"
            continue
        log.info("  [%d/%d] %s… co-bought %d winners, %d closed, win %.0f%%, profitable in %d tokens, pnl %+.2f SOL",
                 i, len(deep), c.address[:8], len(c.tokens), c.closed_trades, c.win_rate * 100,
                 c.profitable_tokens, c.realized_pnl_sol)
    winners = sorted((c for c in deep if c.profitable_tokens >= cfg.min_profitable_tokens),
                     key=lambda c: (c.realized_pnl_sol > 0, len(c.tokens), c.realized_pnl_sol), reverse=True)[: cfg.top_n]
    lines = [f"# co-buyer harvest {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} around {len(seeds)} seed(s): "
             f"{len(cands)} leaders, {len(survivors)} pre-screened, {len(winners)} multi-token winners"]
    lines += [f"{s}  # seed (already approved)" for s in seeds]
    lines += [f"{c.address}  # led seed on {len(c.tokens)} winners; {c.profitable_tokens} profitable tokens, "
              f"{c.closed_trades} closed, win {c.win_rate:.0%}, {c.realized_pnl_sol:+.2f} SOL" for c in winners]
    settings.seed_wallets_path.write_text("\n".join(lines) + "\n")
    save_json(settings.data_dir / "co_buyer_report.json", {
        "seeds": seeds, "candidates": [asdict(c) for c in ranked[: cfg.max_deep_checks * 2]],
        "winners": [c.address for c in winners],
    })
    log.info("wrote %d seeds + %d co-buyer winners -> %s", len(seeds), len(winners), settings.seed_wallets_path)
    return winners
