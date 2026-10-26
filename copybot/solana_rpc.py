"""Minimal, auditable Solana JSON-RPC client over httpx.

We deliberately do not depend on a large SDK for RPC: every method used by the bot is right
here, so a reviewer can see exactly what leaves the machine.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
from typing import Any

import httpx

from .http_utils import HttpError, RateLimiter, request_json

log = logging.getLogger(__name__)


class RpcError(RuntimeError):
    def __init__(self, method: str, error: Any) -> None:
        super().__init__(f"RPC {method} error: {error}")
        self.error = error


_VERSION_RE = re.compile(r'"maxSupportedTransactionVersion":\s*(\d+)')


def _requested_version(error: Any) -> int | None:
    """Parse the version a -32015 'Transaction version (N) is not supported' error asks for."""
    if not isinstance(error, dict) or error.get("code") != -32015:
        return None
    m = _VERSION_RE.search(str(error.get("message", "")))
    return int(m.group(1)) if m else None


class SolanaRpc:
    def __init__(self, client: httpx.AsyncClient, url: str, rps: float = 8.0) -> None:
        self.client = client
        self.url = url
        self.limiter = RateLimiter(rps, burst=max(2.0, rps))
        self._ids = itertools.count(1)
        self.max_tx_version = 1

    async def call(self, method: str, params: list[Any] | None = None, *, timeout: float = 15.0) -> Any:
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or []}
        data = await request_json(
            self.client, "POST", self.url, json=payload, limiter=self.limiter, timeout=timeout
        )
        if "error" in data:
            err = data["error"]
            # -32429 / 429-ish JSON errors from some providers mean "rate limited": back off once.
            if isinstance(err, dict) and err.get("code") in (-32429, 429):
                self.limiter.penalize(1.0)
            raise RpcError(method, err)
        return data.get("result")

    async def get_transaction(self, signature: str, *, retries: int = 6) -> dict | None:
        """Fetch a parsed transaction. Right after a websocket notification the RPC node may
        not have it indexed yet, so a `None` result is retried with a short backoff.

        Transaction versions: mainnet now carries **v1** transactions. Asking with
        `maxSupportedTransactionVersion: 0` (what most copy-bot code does) makes the node
        refuse them with error -32015, so those whale trades are silently missed. We ask
        for the newest version we know and, if the node reports an even newer one, upgrade
        on the fly — the jsonParsed balance fields the parser needs are version-independent.
        """
        delay = 0.25
        for attempt in range(retries):
            params = [
                signature,
                {"encoding": "jsonParsed", "maxSupportedTransactionVersion": self.max_tx_version, "commitment": "confirmed"},
            ]
            try:
                tx = await self.call("getTransaction", params)
            except RpcError as exc:
                newer = _requested_version(exc.error)
                if newer is not None and newer > self.max_tx_version:
                    log.warning("RPC reports transaction version %d; upgrading request version", newer)
                    self.max_tx_version = newer
                    continue
                log.debug("getTransaction %s attempt %d failed: %s", signature, attempt, exc)
                tx = None
            except HttpError as exc:
                log.debug("getTransaction %s attempt %d failed: %s", signature, attempt, exc)
                tx = None
            if tx is not None:
                return tx
            await asyncio.sleep(delay)
            delay = min(delay * 2, 3.0)
        return None

    async def get_signatures_for_address(
        self,
        address: str,
        *,
        limit: int = 1000,
        before: str | None = None,
        until: str | None = None,
    ) -> list[dict]:
        opts: dict[str, Any] = {"limit": min(limit, 1000), "commitment": "confirmed"}
        if before:
            opts["before"] = before
        if until:
            opts["until"] = until
        return await self.call("getSignaturesForAddress", [address, opts]) or []

    async def get_account_info_parsed(self, address: str) -> dict | None:
        res = await self.call("getAccountInfo", [address, {"encoding": "jsonParsed", "commitment": "confirmed"}])
        return res.get("value") if res else None

    async def get_balance(self, address: str) -> int:
        res = await self.call("getBalance", [address, {"commitment": "confirmed"}])
        return int(res["value"])

    async def get_token_balance_raw(self, owner: str, mint: str) -> int:
        """Sum of the owner's token accounts for `mint`, in raw base units."""
        res = await self.call(
            "getTokenAccountsByOwner",
            [owner, {"mint": mint}, {"encoding": "jsonParsed", "commitment": "confirmed"}],
        )
        total = 0
        for acc in (res or {}).get("value", []):
            info = acc["account"]["data"]["parsed"]["info"]
            total += int(info["tokenAmount"]["amount"])
        return total

    async def get_token_accounts(self, owner: str, mint: str) -> list[dict]:
        res = await self.call(
            "getTokenAccountsByOwner",
            [owner, {"mint": mint}, {"encoding": "jsonParsed", "commitment": "confirmed"}],
        )
        return (res or {}).get("value", [])

    async def get_latest_blockhash(self) -> tuple[str, int]:
        res = await self.call("getLatestBlockhash", [{"commitment": "confirmed"}])
        v = res["value"]
        return v["blockhash"], int(v["lastValidBlockHeight"])

    async def get_block_height(self) -> int:
        return int(await self.call("getBlockHeight", [{"commitment": "confirmed"}]))

    async def send_raw_transaction(self, tx_b64: str, *, skip_preflight: bool = False) -> str:
        return await self.call(
            "sendTransaction",
            [
                tx_b64,
                {
                    "encoding": "base64",
                    "skipPreflight": skip_preflight,
                    "preflightCommitment": "confirmed",
                    "maxRetries": 0,  # we rebroadcast ourselves until blockhash expiry
                },
            ],
        )

    async def simulate_lamports_after(self, tx_b64: str, address: str) -> tuple[int | None, str | None]:
        """Simulate a signed tx and return (lamports of `address` afterwards, error)."""
        res = await self.call(
            "simulateTransaction",
            [
                tx_b64,
                {
                    "encoding": "base64",
                    "sigVerify": False,
                    "commitment": "confirmed",
                    "accounts": {"encoding": "base64", "addresses": [address]},
                },
            ],
        )
        value = res["value"]
        if value.get("err") is not None:
            return None, str(value["err"])
        accounts = value.get("accounts") or [None]
        return (int(accounts[0]["lamports"]) if accounts[0] else None), None

    async def get_signature_statuses(self, signatures: list[str]) -> list[dict | None]:
        res = await self.call("getSignatureStatuses", [signatures, {"searchTransactionHistory": False}])
        return res["value"]

    async def get_slot(self) -> int:
        return int(await self.call("getSlot", [{"commitment": "confirmed"}]))
