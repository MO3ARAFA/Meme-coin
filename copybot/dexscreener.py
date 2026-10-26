"""DexScreener public API client (no key; ~300 req/min on the token endpoints).

`/tokens/v1/solana/{a,b,c...}` takes up to 30 mints per call, so one request marks every
open position at once — this is how the exit engine polls prices without hammering Jupiter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from .http_utils import RateLimiter, request_json

log = logging.getLogger(__name__)

BATCH = 30


@dataclass(frozen=True)
class PairInfo:
    pair_address: str
    dex_id: str
    base_mint: str
    base_symbol: str
    quote_mint: str
    price_native: float  # quote-token units per 1 UI base token
    price_usd: float
    liquidity_usd: float | None  # None on Pump.fun bonding-curve pairs (no AMM pool yet)
    market_cap_usd: float | None
    fdv_usd: float | None
    pair_created_at_ms: int | None
    volume_h1_usd: float
    txns_m5: tuple[int, int]  # (buys, sells)

    @property
    def is_bonding_curve(self) -> bool:
        return self.dex_id == "pumpfun"


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _parse_pair(p: dict) -> PairInfo:
    liq = (p.get("liquidity") or {}).get("usd")
    m5 = (p.get("txns") or {}).get("m5") or {}
    return PairInfo(
        pair_address=p["pairAddress"],
        dex_id=p.get("dexId", ""),
        base_mint=p["baseToken"]["address"],
        base_symbol=p["baseToken"].get("symbol", ""),
        quote_mint=p["quoteToken"]["address"],
        price_native=_f(p.get("priceNative")) or 0.0,
        price_usd=_f(p.get("priceUsd")) or 0.0,
        liquidity_usd=_f(liq),
        market_cap_usd=_f(p.get("marketCap")),
        fdv_usd=_f(p.get("fdv")),
        pair_created_at_ms=int(p["pairCreatedAt"]) if p.get("pairCreatedAt") else None,
        volume_h1_usd=_f((p.get("volume") or {}).get("h1")) or 0.0,
        txns_m5=(int(m5.get("buys", 0)), int(m5.get("sells", 0))),
    )


class DexScreenerClient:
    def __init__(self, client: httpx.AsyncClient, base_url: str, rps: float = 4.0) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.limiter = RateLimiter(rps, burst=max(2.0, rps))

    async def pairs_for_tokens(self, mints: list[str], *, timeout: float = 4.0, retries: int = 1) -> dict[str, list[PairInfo]]:
        """mint -> all its Solana pairs where it is the BASE token."""
        out: dict[str, list[PairInfo]] = {m: [] for m in mints}
        for i in range(0, len(mints), BATCH):
            chunk = mints[i : i + BATCH]
            data = await request_json(
                self.client,
                "GET",
                f"{self.base_url}/tokens/v1/solana/{','.join(chunk)}",
                limiter=self.limiter,
                timeout=timeout,
                retries=retries,
            )
            for p in data or []:
                if p.get("chainId") != "solana":
                    continue
                try:
                    pair = _parse_pair(p)
                except (KeyError, TypeError, ValueError):
                    continue
                if pair.base_mint in out:
                    out[pair.base_mint].append(pair)
        return out

    async def best_pair(self, mint: str, **kw) -> PairInfo | None:
        pairs = (await self.pairs_for_tokens([mint], **kw)).get(mint, [])
        return pick_best_pair(pairs)


def pick_best_pair(pairs: list[PairInfo]) -> PairInfo | None:
    """Most liquid pair; AMM pools beat bonding curves (which report no liquidity)."""
    if not pairs:
        return None
    return max(pairs, key=lambda p: (p.liquidity_usd or 0.0, p.volume_h1_usd))


def token_created_at_ms(pairs: list[PairInfo]) -> int | None:
    """Earliest pair creation ~= token launch (the Pump.fun curve pair is created at mint)."""
    times = [p.pair_created_at_ms for p in pairs if p.pair_created_at_ms]
    return min(times) if times else None
