"""Optional AI forensics with Claude: a second opinion on wallets and fresh positions.

Design rules (the model is an analyst, not a trader):
  * NEVER in the pre-buy hot path. Calls run in `score` and in a background task after a
    fill; the safety gate never waits on a model.
  * VETO ONLY. The judge can reject a wallet the quantitative filters approved, or flag a
    position; it can never approve a wallet the numbers rejected.
  * An eject needs on-chain evidence too: the executor never sells on a model's opinion alone.
  * Fail-safe: no key, no SDK, a dead key or a timeout simply turns the layer off; the bot
    keeps running on its quantitative rules.

Uses the official `anthropic` SDK (optional dependency: `pip install -r requirements-ai.txt`),
pointed at `LLM__BASE_URL` when set (any Anthropic-compatible endpoint).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .config import LLMConfig

log = logging.getLogger(__name__)

JUDGE_SYSTEM = """You are an on-chain forensic analyst for a Solana memecoin copy-trading system.
You review one candidate wallet that already passed quantitative filters. Your job is to spot
adversarial behaviour the numbers may hide: copy-trader farming (baiting followers then dumping),
insider/dev or bundler activity, sybil coordination, scripted bots, or an edge that a follower
2 slots late cannot capture. Be skeptical but fair: a consistent discretionary swing trader with
real holds and many tokens is exactly what we want to keep.

Answer with ONLY a JSON object, no prose, with these keys:
{"verdict": "APPROVE" | "REJECT",
 "adversarial_risk_score": integer 0-100 (0 = clean independent trader, 100 = certain hunter/cabal),
 "archetype": short label, e.g. "swing trader", "runner hunter", "scalper", "farmer", "insider",
 "red_flags": [short strings],
 "exit_overrides": {"trailing_stop_pct": number or null, "time_decay_minutes": number or null},
 "rationale": one or two sentences}"""

OVERWATCH_SYSTEM = """You are a real-time risk analyst watching a Solana memecoin position that was
opened seconds ago by copying a tracked wallet. Given on-chain holder distribution, liquidity and
order-flow facts, estimate the probability that this is a coordinated bull trap (a ring pumping
the token so copy-traders become exit liquidity). Answer with ONLY a JSON object:
{"trap_probability": number 0-1, "red_flags": [short strings], "rationale": one sentence}"""


def _extract_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


class AIAnalyst:
    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self.model: str | None = None
        self.status = "not probed"
        self._client = None
        self._sdk = None

    @property
    def available(self) -> bool:
        return self.model is not None

    async def probe(self) -> str | None:
        """Find the first model this key can use. A rejected key stops the probe immediately."""
        if not self.cfg.enabled:
            self.status = "disabled (no LLM__API_KEY)"
            return None
        try:
            import anthropic
        except ImportError:
            self.status = "anthropic SDK not installed (pip install -r requirements-ai.txt)"
            return None
        self._sdk = anthropic
        self._client = anthropic.AsyncAnthropic(
            api_key=self.cfg.api_key, base_url=self.cfg.base_url or None, timeout=self.cfg.timeout_s, max_retries=1
        )
        candidates = [self.cfg.model] if self.cfg.model else list(self.cfg.probe_models)
        for model in candidates:
            try:
                await self._client.messages.create(
                    model=model, max_tokens=256, messages=[{"role": "user", "content": "Reply with the word OK."}]
                )
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
                self.status = f"key rejected by endpoint ({exc.status_code}): {str(exc)[:160]}"
                return None
            except (anthropic.NotFoundError, anthropic.BadRequestError):
                continue  # this model is not served here; try the next one
            except anthropic.APIConnectionError as exc:
                self.status = f"endpoint unreachable: {exc}"
                return None
            except anthropic.APIStatusError as exc:
                self.status = f"endpoint error {exc.status_code}: {str(exc)[:160]}"
                return None
            self.model = model
            self.status = f"ok ({model})"
            return model
        self.status = f"none of the probed models is served: {candidates}"
        return None

    async def _ask(self, system: str, payload: dict[str, Any], max_tokens: int = 2000) -> dict | None:
        if not self.available:
            return None
        try:
            resp = await self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
            )
        except Exception as exc:  # any API problem = no opinion, never a crash
            log.warning("AI request failed: %s", exc)
            return None
        if getattr(resp, "stop_reason", None) == "refusal":
            return None
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return _extract_json(text)

    async def judge_wallet(self, metrics: dict[str, Any]) -> dict | None:
        out = await self._ask(JUDGE_SYSTEM, {"wallet_metrics": metrics})
        if not out or out.get("verdict") not in ("APPROVE", "REJECT"):
            return None
        try:
            out["adversarial_risk_score"] = max(0, min(100, int(out.get("adversarial_risk_score", 50))))
        except (TypeError, ValueError):
            out["adversarial_risk_score"] = 50
        return out

    async def overwatch(self, facts: dict[str, Any]) -> dict | None:
        out = await self._ask(OVERWATCH_SYSTEM, {"position": facts}, max_tokens=800)
        if not out:
            return None
        try:
            out["trap_probability"] = max(0.0, min(1.0, float(out.get("trap_probability", 0))))
        except (TypeError, ValueError):
            return None
        return out


def wallet_brief(m: dict[str, Any]) -> dict[str, Any]:
    """The facts the judge sees: metrics only, no keys, no PII beyond the public address."""
    keys = (
        "address", "closed_trades", "win_rate", "median_roi", "nonscratch_median_roi", "trimmed_mean_roi",
        "profit_factor", "median_hold_s", "avg_hold_s", "flip_ratio", "sniper_ratio", "transfer_out_ratio",
        "unpriced_ratio", "trades_per_day", "total_pnl_sol", "median_buy_sol", "replay_trades",
        "replay_win_rate", "replay_profit_factor", "replay_expectancy", "expected_edge_pct", "timing_cv",
        "hold_cv", "bundled_buy_ratio", "co_slot_ratio", "fingerprint", "token_recipients", "top_trade_pnl_share",
    )
    return {k: m.get(k) for k in keys}
