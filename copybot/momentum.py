"""Momentum signal source: breakout detection on liquid, already-launched memecoins.

Two parts, kept apart so the interesting one is a pure function you can test and reason about:

  * `detect_momentum(samples, cfg, now)` - pure. Given a token's recent price/flow samples,
    says whether it is in a controlled breakout and, if not, exactly why not.
  * `MomentumScanner` - I/O. Discovers a universe of liquid memecoins, polls DexScreener in
    batches (one request prices 30 mints), feeds the detector and hands signals to a callback.

A signal is only a candidate. The engine runs it through the same safety gate, kill switch, fee
guard, sizing, circuit breaker and exit engine as a copied whale buy (see
`CopyEngine.handle_momentum`). What this module never does is chase launches: tokens younger
than `min_age_hours` are excluded, and verticals above `max_return` are refused.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from .config import MomentumConfig, Settings
from .constants import NON_MEME_MINTS, WSOL_MINT
from .dexscreener import DexScreenerClient, PairInfo, pick_best_pair

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Sample:
    ts: float
    price_native: float  # SOL per 1 UI token on the best pair
    # Flow and liquidity are optional so the same detector can run on plain OHLCV candles
    # (nautilus_lab backtests). When None the matching checks are skipped, never faked.
    buys_m5: int | None = None
    sells_m5: int | None = None
    liquidity_usd: float | None = None
    volume_h1_usd: float = 0.0


@dataclass(frozen=True)
class MomentumSignal:
    mint: str
    symbol: str
    ts: float
    price_native: float  # SOL per UI token at signal time: the anti-chase reference
    window_return: float
    up_step_frac: float
    pullback_from_high: float
    buys_m5: int | None
    buy_ratio: float | None
    liquidity_usd: float | None

    def summary(self) -> str:
        flow = "" if self.buys_m5 is None else f" buys5m={self.buys_m5} ratio={self.buy_ratio:.0%}"
        liq = "" if self.liquidity_usd is None else f" liq=${self.liquidity_usd:,.0f}"
        return (
            f"{self.symbol or self.mint[:6]} ret={self.window_return:+.1%} "
            f"ups={self.up_step_frac:.0%} pullback={self.pullback_from_high:.1%}{flow}{liq}"
        )


@dataclass
class Verdict:
    """Detector output. `reasons` is non-empty exactly when `signal` is None."""

    signal: MomentumSignal | None = None
    reasons: list[str] = field(default_factory=list)


def detect_momentum(
    mint: str,
    symbol: str,
    samples: list[Sample],
    cfg: MomentumConfig,
    now: float | None = None,
) -> Verdict:
    """Pure breakout test over the trailing `cfg.window_s` seconds of samples (oldest first)."""
    now = now if now is not None else time.time()
    v = Verdict()
    window = [s for s in samples if now - s.ts <= cfg.window_s and s.price_native > 0]
    if len(window) < cfg.min_samples:
        v.reasons.append(
            f"warming up: {len(window)}/{cfg.min_samples} samples in the last {cfg.window_s:.0f}s"
        )
        return v
    # The window must actually span most of its length, or "5-minute return" is a lie.
    if window[-1].ts - window[0].ts < 0.6 * cfg.window_s:
        v.reasons.append("samples span < 60% of the window")
        return v
    first, last = window[0], window[-1]
    ret = last.price_native / first.price_native - 1.0
    steps = [b.price_native - a.price_native for a, b in zip(window, window[1:])]
    up_frac = sum(1 for d in steps if d > 0) / len(steps)
    high = max(s.price_native for s in window)
    pullback = 1.0 - last.price_native / high
    has_flow = last.buys_m5 is not None and last.sells_m5 is not None
    total = (last.buys_m5 + last.sells_m5) if has_flow else 0
    ratio = (last.buys_m5 / total if total else 0.0) if has_flow else None

    if ret < cfg.min_return:
        v.reasons.append(f"return {ret:+.1%} < {cfg.min_return:+.0%}")
    if ret > cfg.max_return:
        v.reasons.append(
            f"return {ret:+.1%} > {cfg.max_return:+.0%}: vertical, buying the top"
        )
    if up_frac < cfg.min_up_step_frac:
        v.reasons.append(
            f"only {up_frac:.0%} of steps rose (< {cfg.min_up_step_frac:.0%}): one spike, not a trend"
        )
    if pullback > cfg.max_pullback_from_high:
        v.reasons.append(
            f"{pullback:.1%} below the window high (> {cfg.max_pullback_from_high:.0%}): already fading"
        )
    if has_flow:
        if last.buys_m5 < cfg.min_buys_m5:
            v.reasons.append(f"only {last.buys_m5} buys in 5 min (< {cfg.min_buys_m5})")
        if ratio < cfg.min_buy_ratio:
            v.reasons.append(f"buy ratio {ratio:.0%} < {cfg.min_buy_ratio:.0%}")
    if last.liquidity_usd is not None and last.liquidity_usd < cfg.min_liquidity_usd:
        v.reasons.append(f"liquidity ${last.liquidity_usd:,.0f} < ${cfg.min_liquidity_usd:,.0f}")
    if not v.reasons:
        v.signal = MomentumSignal(
            mint,
            symbol,
            now,
            last.price_native,
            ret,
            up_frac,
            pullback,
            last.buys_m5,
            ratio,
            last.liquidity_usd,
        )
    return v


def sample_from_pair(pair: PairInfo, now: float) -> Sample:
    return Sample(
        now,
        pair.price_native,
        pair.txns_m5[0],
        pair.txns_m5[1],
        pair.liquidity_usd or 0.0,
        pair.volume_h1_usd,
    )


def eligible_pair(
    pairs: list[PairInfo], cfg: MomentumConfig, now: float
) -> PairInfo | None:
    """Best SOL-quoted AMM pair that is old enough (never a launch) and not ancient."""
    pair = pick_best_pair(
        [
            p
            for p in pairs
            if p.quote_mint == WSOL_MINT and p.liquidity_usd and p.price_native > 0
        ]
    )
    if pair is None or pair.is_bonding_curve or not pair.pair_created_at_ms:
        return None
    age_h = (now * 1000 - pair.pair_created_at_ms) / 3_600_000
    if age_h < cfg.min_age_hours or age_h > cfg.max_age_days * 24:
        return None
    return pair


OnSignal = Callable[[MomentumSignal], Awaitable[None]]


class MomentumScanner:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        dex: DexScreenerClient,
        on_signal: OnSignal,
        discover: Callable[[], Awaitable[list[str]]] | None = None,
    ) -> None:
        self.s = settings
        self.cfg = settings.momentum
        self.client = client
        self.dex = dex
        self.on_signal = on_signal
        self._discover = discover or self._discover_default
        self.universe: list[str] = []
        self.history: dict[str, deque[Sample]] = {}
        self.symbols: dict[str, str] = {}
        self.cooldown_until: dict[str, float] = {}
        self._universe_ts = 0.0

    async def _discover_default(self) -> list[str]:
        from .harvester import discover_tokens  # lazy: pulls in the whole harvester

        tokens = await discover_tokens(self.client, self.s)
        return [t.mint for t in tokens if t.mint not in NON_MEME_MINTS]

    async def refresh_universe(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        mints = (await self._discover())[: self.cfg.max_universe]
        if mints:  # keep the old universe if discovery came back empty (API hiccup)
            self.universe = mints
            for m in list(self.history):
                if m not in mints:
                    del self.history[m]
        self._universe_ts = now
        log.info("momentum universe: %d tokens", len(self.universe))

    async def scan_once(self, now: float | None = None) -> list[MomentumSignal]:
        """One poll over the whole universe. Returns the signals that fired (already dispatched)."""
        now = now if now is not None else time.time()
        if not self.universe or now - self._universe_ts >= self.cfg.universe_refresh_s:
            await self.refresh_universe(now)
        if not self.universe:
            return []
        by_mint = await self.dex.pairs_for_tokens(self.universe)
        fired: list[MomentumSignal] = []
        for mint, pairs in by_mint.items():
            pair = eligible_pair(pairs, self.cfg, now)
            if pair is None:
                self.history.pop(mint, None)
                continue
            self.symbols[mint] = pair.base_symbol
            hist = self.history.setdefault(mint, deque(maxlen=self.cfg.history_len))
            hist.append(sample_from_pair(pair, now))
            if now < self.cooldown_until.get(mint, 0.0):
                continue
            verdict = detect_momentum(mint, pair.base_symbol, list(hist), self.cfg, now)
            if verdict.signal is None:
                continue
            self.cooldown_until[mint] = now + self.cfg.cooldown_s
            fired.append(verdict.signal)
            log.info("MOMENTUM %s", verdict.signal.summary())
            try:
                await self.on_signal(verdict.signal)
            except Exception:  # one bad entry must never kill the scanner
                log.exception("momentum handler failed for %s", mint)
        return fired

    async def run(self) -> None:
        while True:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("momentum scan failed: %s", exc)
            await asyncio.sleep(self.cfg.poll_interval_s)
