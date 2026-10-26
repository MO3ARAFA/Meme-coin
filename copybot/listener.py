"""Real-time wallet activity feed: WebSocket `logsSubscribe` with polling backfill.

Solana edge cases handled here:
  * `logsSubscribe` accepts exactly ONE address in `mentions` per subscription, so we open one
    subscription per approved wallet over a single connection.
  * Websockets drop silently (especially on free tiers). We ping, reconnect with backoff, and
    on every (re)connect backfill missed signatures with `getSignaturesForAddress(until=last)`.
  * Notifications for failed transactions are skipped; duplicates (ws + backfill) are filtered
    downstream by signature.
  * `listener_mode=poll` is a websocket-free fallback for providers without WS support.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import websockets

from .solana_rpc import SolanaRpc

log = logging.getLogger(__name__)

OnSignature = Callable[[str, str], Awaitable[None]]  # (wallet, signature)


class WalletListener:
    def __init__(
        self,
        ws_url: str,
        rpc: SolanaRpc,
        wallets: list[str],
        on_signature: OnSignature,
        last_signature: dict[str, str],
        mode: str = "ws",
        poll_interval_s: float = 2.0,
    ) -> None:
        self.ws_url = ws_url
        self.rpc = rpc
        self.wallets = wallets
        self.on_signature = on_signature
        self.last_signature = last_signature  # persisted by the engine
        self.mode = mode
        self.poll_interval_s = poll_interval_s
        self._tasks: set[asyncio.Task] = set()

    async def run(self) -> None:
        if self.mode == "poll":
            await self._poll_forever()
        else:
            await self._ws_forever()

    async def backfill(self, wallet: str, limit: int = 25) -> None:
        """Deliver signatures newer than the last one we processed, oldest first."""
        last = self.last_signature.get(wallet)
        try:
            sigs = await self.rpc.get_signatures_for_address(wallet, limit=limit, until=last)
        except Exception as exc:
            log.warning("backfill %s failed: %s", wallet[:6], exc)
            return
        if not last:
            # First run: don't replay history as fresh signals, just set the cursor.
            if sigs:
                self.last_signature[wallet] = sigs[0]["signature"]
            return
        for row in reversed(sigs):
            if row.get("err") is None:
                await self.on_signature(wallet, row["signature"])
        if sigs:
            self.last_signature[wallet] = sigs[0]["signature"]

    async def _poll_forever(self) -> None:
        for w in self.wallets:
            await self.backfill(w)
        while True:
            for w in self.wallets:
                await self.backfill(w)
            await asyncio.sleep(self.poll_interval_s)

    async def _ws_forever(self) -> None:
        delay = 1.0
        while True:
            try:
                await self._ws_session()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("websocket dropped (%s); reconnecting in %.0fs", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)

    async def _ws_session(self) -> None:
        async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20, max_size=2**22) as ws:
            pending: dict[int, str] = {}
            for i, wallet in enumerate(self.wallets, start=1):
                await ws.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": i,
                            "method": "logsSubscribe",
                            "params": [{"mentions": [wallet]}, {"commitment": "confirmed"}],
                        }
                    )
                )
                pending[i] = wallet
            sub_to_wallet: dict[int, str] = {}
            log.info("websocket connected, subscribing to %d wallets", len(self.wallets))
            # Close the gap between the last processed signature and the new subscription.
            for w in self.wallets:
                await self.backfill(w)
            async for raw in ws:
                msg = json.loads(raw)
                if "id" in msg and msg["id"] in pending:
                    if "result" in msg:
                        sub_to_wallet[int(msg["result"])] = pending.pop(msg["id"])
                    else:
                        raise RuntimeError(f"subscription rejected: {msg.get('error')}")
                    continue
                if msg.get("method") != "logsNotification":
                    continue
                params = msg["params"]
                wallet = sub_to_wallet.get(params["subscription"])
                value = params["result"]["value"]
                if wallet is None or value.get("err") is not None:
                    continue
                sig = value["signature"]
                self.last_signature[wallet] = sig
                task = asyncio.create_task(self._deliver(wallet, sig))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _deliver(self, wallet: str, sig: str) -> None:
        try:
            await self.on_signature(wallet, sig)
        except Exception:
            log.exception("handler failed for %s", sig)
