"""Jupiter Swap API client (quote + swap transaction build).

Jupiter retired the old `quote-api.jup.ag/v6` host; the same V6 quote/swap schema is now
served at `lite-api.jup.ag/swap/v1` (free, no key) and `api.jup.ag/swap/v1` (API key,
higher limits). The base URL is configurable so a future move is a one-line `.env` change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .config import PriorityMode
from .http_utils import HttpError, RateLimiter, request_json

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Quote:
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    other_amount_threshold: int  # min out after slippage
    price_impact_pct: float  # fraction, e.g. 0.004 = 0.4%
    slippage_bps: int
    route_labels: tuple[str, ...]
    raw: dict[str, Any]

    @property
    def price_in_per_out(self) -> float:
        return self.in_amount / self.out_amount if self.out_amount else float("inf")


class NoRouteError(RuntimeError):
    pass


class JupiterClient:
    def __init__(self, client: httpx.AsyncClient, base_url: str, api_key: str = "", rps: float = 1.0) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.headers = {"x-api-key": api_key} if api_key else {}
        # Burst of 2 = the gate's buy quote + dependent sell quote back to back. Larger bursts
        # draw 429s from the free tier even under its per-minute limit.
        self.limiter = RateLimiter(rps, burst=2.0)

    async def quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int,
        *,
        timeout: float = 4.0,
        retries: int = 1,
    ) -> Quote:
        if amount <= 0:
            raise ValueError("amount must be positive")
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": str(slippage_bps),
            "swapMode": "ExactIn",
            "restrictIntermediateTokens": "true",  # route only through liquid hops
        }
        try:
            data = await request_json(
                self.client,
                "GET",
                f"{self.base_url}/quote",
                params=params,
                headers=self.headers,
                limiter=self.limiter,
                timeout=timeout,
                retries=retries,
            )
        except HttpError as exc:
            if exc.status in (400, 404):
                raise NoRouteError(str(exc)) from exc
            raise
        if not data or "outAmount" not in data:
            raise NoRouteError(f"no route {input_mint}->{output_mint}: {str(data)[:200]}")
        return Quote(
            input_mint=data["inputMint"],
            output_mint=data["outputMint"],
            in_amount=int(data["inAmount"]),
            out_amount=int(data["outAmount"]),
            other_amount_threshold=int(data["otherAmountThreshold"]),
            price_impact_pct=abs(float(data.get("priceImpactPct") or 0.0)),
            slippage_bps=int(data.get("slippageBps", slippage_bps)),
            route_labels=tuple(step.get("swapInfo", {}).get("label", "?") for step in data.get("routePlan", [])),
            raw=data,
        )

    async def build_swap_transaction(
        self,
        quote: Quote,
        user_pubkey: str,
        *,
        max_priority_lamports: int,
        priority_mode: PriorityMode,
    ) -> tuple[str, int]:
        """Ask Jupiter to build an unsigned swap tx. Returns (base64 tx, lastValidBlockHeight).

        The fee we are willing to pay is passed as a hard ceiling: Jupiter picks the actual
        priority fee from recent fee markets but never exceeds `max_priority_lamports`.
        """
        if priority_mode is PriorityMode.JITO_TIP:
            prio: dict[str, Any] = {"jitoTipLamports": int(max_priority_lamports)}
        else:
            prio = {
                "priorityLevelWithMaxLamports": {
                    "maxLamports": int(max_priority_lamports),
                    "priorityLevel": "veryHigh",
                }
            }
        body = {
            "quoteResponse": quote.raw,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": prio,
        }
        data = await request_json(
            self.client,
            "POST",
            f"{self.base_url}/swap",
            json=body,
            headers=self.headers,
            limiter=self.limiter,
            timeout=8.0,
            retries=1,
        )
        if "swapTransaction" not in data:
            raise RuntimeError(f"jupiter swap build failed: {str(data)[:300]}")
        return data["swapTransaction"], int(data.get("lastValidBlockHeight", 0))
