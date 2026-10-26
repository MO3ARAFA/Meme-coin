"""Console + optional Telegram notifications (official Bot API over httpx, no SDK)."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger("copybot")


class Notifier:
    def __init__(self, client: httpx.AsyncClient, bot_token: str = "", chat_id: str = "") -> None:
        self.client = client
        self.bot_token = bot_token
        self.chat_id = chat_id

    async def send(self, text: str, *, level: int = logging.INFO) -> None:
        log.log(level, text)
        if not (self.bot_token and self.chat_id):
            return
        try:
            await self.client.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text[:4000], "disable_web_page_preview": True},
                timeout=5.0,
            )
        except Exception as exc:  # notifications must never break trading
            log.debug("telegram send failed: %s", exc)
