"""Module B — pre-buy token safety & anti-exit-liquidity gate.

Runs on every whale BUY before we copy it. Independent checks run concurrently
(DexScreener, mint account, Jupiter buy quote), then a dependent Jupiter SELL quote for the
exact amount we would receive. The copy is aborted if ANY check fails.

The buy->sell round trip is the most powerful single check here: it measures what we would
actually get back if we exited immediately — DEX fees on both legs, price impact on both
legs, and any transfer tax or sell restriction. Honeypots fail it by construction.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from .config import SafetyConfig
from .constants import LAMPORTS_PER_SOL, NON_MEME_MINTS, USDC_MINT, WSOL_MINT
from .dexscreener import DexScreenerClient, PairInfo, pick_best_pair
from .jupiter import JupiterClient, NoRouteError, Quote
from .risk_config import FeeBudget, RiskManager, per_leg_cost_from_roundtrip
from .solana_rpc import SolanaRpc
from .state import BotState
from .token_security import MintInfo, inspect_mint
from .tx_parser import Side, SwapEvent

log = logging.getLogger(__name__)


@dataclass
class GateResult:
    passed: bool
    mint: str
    reasons: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    pair: PairInfo | None = None
    mint_info: MintInfo | None = None
    buy_quote: Quote | None = None
    sell_quote: Quote | None = None
    whale_price: float = 0.0  # lamports per raw token
    our_price: float = 0.0
    chase_pct: float = 0.0
    roundtrip_return: float = 0.0
    fee_budget: FeeBudget | None = None

    def summary(self) -> str:
        head = "PASS" if self.passed else "ABORT"
        parts = [f"{head} {self.mint[:8]}… in {self.latency_ms:.0f}ms"]
        if self.pair:
            parts.append(
                f"liq=${(self.pair.liquidity_usd or 0):,.0f} mcap=${(self.pair.market_cap_usd or self.pair.fdv_usd or 0):,.0f} dex={self.pair.dex_id}"
            )
        if self.our_price and self.whale_price:
            parts.append(f"chase={self.chase_pct:+.1%}")
        if self.roundtrip_return:
            parts.append(f"roundtrip={self.roundtrip_return - 1:+.2%}")
        if self.reasons:
            parts.append("reasons: " + "; ".join(self.reasons))
        return " | ".join(parts)


class SolPriceCache:
    """SOL/USD from a live Jupiter quote, cached briefly. Needed only for USDC-paid whale buys."""

    def __init__(self, jupiter: JupiterClient, ttl_s: float = 60.0) -> None:
        self.jupiter = jupiter
        self.ttl_s = ttl_s
        self._value: float | None = None
        self._ts = 0.0

    async def usd_per_sol(self) -> float:
        if self._value is None or time.time() - self._ts > self.ttl_s:
            q = await self.jupiter.quote(WSOL_MINT, USDC_MINT, LAMPORTS_PER_SOL, 50)
            self._value = q.out_amount / 1e6
            self._ts = time.time()
        return self._value


class SafetyGate:
    def __init__(
        self,
        cfg: SafetyConfig,
        rpc: SolanaRpc,
        jupiter: JupiterClient,
        dex: DexScreenerClient,
        risk: RiskManager,
        state: BotState,
        entry_slippage_bps: int,
    ) -> None:
        self.cfg = cfg
        self.rpc = rpc
        self.jupiter = jupiter
        self.dex = dex
        self.risk = risk
        self.state = state
        self.entry_slippage_bps = entry_slippage_bps
        self.sol_price = SolPriceCache(jupiter)
        self._mint_cache: dict[str, MintInfo] = {}

    async def mint_info(self, mint: str) -> MintInfo:
        cached = self._mint_cache.get(mint)
        if cached is not None:
            return cached
        info = inspect_mint(mint, await self.rpc.get_account_info_parsed(mint))
        if info.immutable:
            self._mint_cache[mint] = info  # revoked authorities can never come back
        return info

    async def whale_price_lamports(self, ev: SwapEvent) -> float:
        """Whale fill in lamports per raw token, converting stablecoin-paid buys via SOL/USD."""
        if ev.is_sol_quoted:
            return ev.price_quote_per_raw
        usd_per_raw = ev.price_quote_per_raw / 1e6  # USDC/USDT have 6 decimals
        return usd_per_raw / await self.sol_price.usd_per_sol() * LAMPORTS_PER_SOL

    def precheck(self, ev: SwapEvent, now: float | None = None) -> list[str]:
        """Free, local checks — run before spending any API calls."""
        now = now or time.time()
        reasons: list[str] = []
        if ev.side is not Side.BUY:
            reasons.append("not a buy")
        if ev.mint in NON_MEME_MINTS:
            reasons.append("not a memecoin (quote/LST/major)")
        last = self.state.last_entry_by_mint.get(ev.mint)
        if last is not None and now - last < self.cfg.reentry_cooldown_s:
            reasons.append(f"no double-dip: entered {(now - last) / 3600:.1f}h ago")
        if any(p.mint == ev.mint for p in self.state.open_positions()):
            reasons.append("already holding this token")
        if ev.block_time and now - ev.block_time > self.cfg.max_signal_age_s:
            reasons.append(f"stale signal ({now - ev.block_time:.0f}s old)")
        if ev.is_sol_quoted and ev.quote_amount_raw < self.cfg.min_whale_buy_sol * LAMPORTS_PER_SOL:
            reasons.append(f"whale buy too small ({ev.quote_amount_raw / LAMPORTS_PER_SOL:.3f} SOL)")
        return reasons

    async def evaluate(self, ev: SwapEvent, size_lamports: int) -> GateResult:
        t0 = time.perf_counter()
        res = GateResult(passed=False, mint=ev.mint)
        res.reasons = self.precheck(ev)
        if res.reasons:
            res.latency_ms = (time.perf_counter() - t0) * 1000
            return res
        try:
            await asyncio.wait_for(self._remote_checks(ev, size_lamports, res), self.cfg.gate_hard_timeout_ms / 1000)
        except asyncio.TimeoutError:
            res.reasons.append(f"gate timeout > {self.cfg.gate_hard_timeout_ms}ms (price data too slow to trust)")
        except Exception as exc:  # fail closed: any unexpected error aborts the buy
            log.exception("safety gate error for %s", ev.mint)
            res.reasons.append(f"gate error: {exc}")
        res.latency_ms = (time.perf_counter() - t0) * 1000
        res.passed = not res.reasons
        if res.latency_ms > self.cfg.gate_latency_budget_ms:
            log.debug("gate latency %.0fms over %dms budget", res.latency_ms, self.cfg.gate_latency_budget_ms)
        return res

    async def _remote_checks(self, ev: SwapEvent, size_lamports: int, res: GateResult) -> None:
        cfg = self.cfg
        pairs_t = asyncio.create_task(self.dex.pairs_for_tokens([ev.mint]))
        mint_t = asyncio.create_task(self.mint_info(ev.mint))
        buy_t = asyncio.create_task(self.jupiter.quote(WSOL_MINT, ev.mint, size_lamports, self.entry_slippage_bps))
        whale_px_t = asyncio.create_task(self.whale_price_lamports(ev))
        pairs_r, mint_r, buy_r, whale_r = await asyncio.gather(pairs_t, mint_t, buy_t, whale_px_t, return_exceptions=True)

        # 1. Liquidity & market cap
        if isinstance(pairs_r, Exception):
            res.reasons.append(f"dexscreener unavailable: {pairs_r}")
        else:
            pair = pick_best_pair(pairs_r.get(ev.mint, []))
            res.pair = pair
            if pair is None:
                res.reasons.append("no DexScreener pair")
            else:
                if pair.liquidity_usd is None:
                    res.reasons.append(f"no measurable pool liquidity ({pair.dex_id} bonding curve)")
                elif pair.liquidity_usd < cfg.min_liquidity_usd:
                    res.reasons.append(f"liquidity ${pair.liquidity_usd:,.0f} < ${cfg.min_liquidity_usd:,.0f}")
                mcap = pair.market_cap_usd or pair.fdv_usd or 0.0
                if mcap < cfg.min_market_cap_usd:
                    res.reasons.append(f"market cap ${mcap:,.0f} < ${cfg.min_market_cap_usd:,.0f}")

        # 2. Contract security
        if isinstance(mint_r, Exception):
            res.reasons.append(f"mint lookup failed: {mint_r}")
        else:
            res.mint_info = mint_r
            res.reasons.extend(mint_r.problems)

        # 3. Executable price, anti-chase, price impact
        if isinstance(whale_r, Exception):
            res.reasons.append(f"whale price unavailable: {whale_r}")
        else:
            res.whale_price = whale_r
        if isinstance(buy_r, NoRouteError):
            res.reasons.append("no Jupiter buy route")
            return
        if isinstance(buy_r, Exception):
            res.reasons.append(f"buy quote failed: {buy_r}")
            return
        res.buy_quote = buy_r
        res.our_price = buy_r.price_in_per_out
        if res.whale_price > 0:
            res.chase_pct = res.our_price / res.whale_price - 1.0
            if res.chase_pct > cfg.max_chase_pct:
                res.reasons.append(f"chasing: our fill {res.chase_pct:+.1%} vs whale (max {cfg.max_chase_pct:.0%})")
        if buy_r.price_impact_pct > cfg.max_price_impact_pct:
            res.reasons.append(f"price impact {buy_r.price_impact_pct:.2%} > {cfg.max_price_impact_pct:.2%}")

        if res.reasons:
            return  # don't spend a sell quote on a token we already rejected

        # 4. Round trip: can we get out, and what does it cost?
        try:
            sell = await self.jupiter.quote(ev.mint, WSOL_MINT, buy_r.out_amount, self.entry_slippage_bps)
        except NoRouteError:
            res.reasons.append("no Jupiter SELL route (possible honeypot)")
            return
        res.sell_quote = sell
        res.roundtrip_return = sell.out_amount / buy_r.in_amount
        loss = 1.0 - res.roundtrip_return
        if loss > cfg.max_roundtrip_loss_pct:
            res.reasons.append(f"round-trip loss {loss:.2%} > {cfg.max_roundtrip_loss_pct:.2%} (tax/fees/impact)")
            return

        # 5. Fee guard (Module D): DEX fee + impact + network fee <= cap, per leg
        budget = self.risk.fee_budget(size_lamports, per_leg_cost_from_roundtrip(res.roundtrip_return))
        res.fee_budget = budget
        if not budget.allowed:
            res.reasons.append(budget.reason)
