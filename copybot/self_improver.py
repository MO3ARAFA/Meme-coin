"""Pillar 4 — self-evolving brain: post-exit regret analysis and bounded auto-tuning.

Loop:
  1. **Regret.** 15 and 60 minutes after every close, re-quote the exact token amount we sold.
     Price above our exit = *missed upside* (sold too early); below = *saved crash* (good exit).
  2. **Tune.** Every 10 closed trades or 12 hours, the CFO ledger + regret summary go to the AI
     endpoint, which proposes new values for a short whitelist of parameters and whale
     demotions. Without a reachable AI, a transparent rule-based tuner runs instead.
  3. **Hot reload.** Proposals are clamped and written to `data/runtime_overrides.json`; the
     running engine re-reads that file every few seconds and applies it in place — no restart.

Safety rails, enforced in code (the model cannot argue past them):
  * only whitelisted parameters; each has hard bounds whose risky side IS the mandate value
    (e.g. the stop can tighten from -22% but never loosen past it, the liquidity floor can rise
    but never drop below $25k, the chase cap can tighten but never exceed 12%);
  * one round moves a parameter by at most `max_step_frac` (25%);
  * whales can be DEMOTED (probation sizing) but never promoted; position size, execution
    mode, keys and endpoints are not tunable at all.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .constants import WSOL_MINT

log = logging.getLogger(__name__)

# name -> (min, max). The risky side of every range equals the mandate default.
TUNABLE: dict[str, tuple[float, float]] = {
    "exits.hard_stop_loss": (0.10, 0.22),
    "exits.trailing_stop_pct": (0.08, 0.25),
    "exits.moonbag_trailing_stop_pct": (0.15, 0.40),
    "exits.cluster_trailing_stop_pct": (0.20, 0.45),
    "exits.time_decay_minutes": (20.0, 90.0),
    "exits.scale_out_profit": (0.30, 0.80),
    "safety.min_liquidity_usd": (25_000.0, 200_000.0),
    "safety.max_chase_pct": (0.04, 0.12),
    "safety.max_edge_consumed": (0.40, 0.80),
    "shield.max_exit_liquidity_risk": (35.0, 60.0),
}


def get_param(settings: Settings, name: str) -> float:
    section, field_name = name.split(".")
    return getattr(getattr(settings, section), field_name)


def set_param(settings: Settings, name: str, value: float) -> None:
    section, field_name = name.split(".")
    obj = getattr(settings, section)
    current = getattr(obj, field_name)
    setattr(obj, field_name, type(current)(value))  # in place: every holder of this config object sees it


def clamp_proposal(settings: Settings, proposed: dict[str, Any], max_step_frac: float,
                   base: dict[str, float] | None = None) -> dict[str, float]:
    """Keep only whitelisted, numeric, bounded values; limit each move to max_step_frac of the
    current value (or of `base`, the pre-override defaults, when given)."""
    out: dict[str, float] = {}
    for name, value in (proposed or {}).items():
        if name not in TUNABLE:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        lo, hi = TUNABLE[name]
        current = float((base or {}).get(name, get_param(settings, name)))
        step = abs(current) * max_step_frac
        value = min(max(value, current - step), current + step)
        out[name] = round(min(max(value, lo), hi), 6)
    return out


# ---------------------------------------------------------------------------------------
# Regret
# ---------------------------------------------------------------------------------------
class RegretTracker:
    def __init__(self, path: Path, checks_min: list[int]) -> None:
        self.path = path
        self.checks_min = checks_min
        self.data: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {"pending": [], "done": []}

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        os.replace(tmp, self.path)

    def schedule(self, pos, *, exit_price: float, token_raw: int) -> None:
        if exit_price <= 0 or token_raw <= 0:
            return
        now = time.time()
        self.data["pending"].append({
            "position_id": pos.id, "mint": pos.mint, "whale": pos.whale, "reason": pos.close_reason,
            "net_return": round(pos.net_return, 4), "exit_price": exit_price, "token_raw": int(token_raw),
            "closed_at": now, "due": [now + m * 60 for m in self.checks_min], "results": {},
        })
        self.save()

    async def process_due(self, jupiter) -> int:
        """Re-quote positions whose 15/60-min checkpoints are due. Returns checks completed."""
        now, n = time.time(), 0
        still: list[dict] = []
        for item in self.data["pending"]:
            for minutes, due in zip(self.checks_min, item["due"]):
                key = str(minutes)
                if key in item["results"] or now < due:
                    continue
                try:
                    q = await jupiter.quote(item["mint"], WSOL_MINT, item["token_raw"], 500, retries=1)
                    ratio = (q.out_amount / item["token_raw"]) / item["exit_price"]
                except Exception:
                    ratio = 0.0 if now - due > 3600 else None  # no route for an hour = it crashed
                if ratio is None:
                    continue
                item["results"][key] = {"ratio": round(ratio, 4), "missed_upside": round(max(0.0, ratio - 1), 4),
                                        "saved_crash": round(max(0.0, 1 - ratio), 4)}
                n += 1
            (self.data["done"] if len(item["results"]) == len(self.checks_min) else still).append(item)
        self.data["pending"] = still
        self.data["done"] = self.data["done"][-500:]
        if n:
            self.save()
        return n

    def summary(self, last: int = 50) -> dict[str, Any]:
        out: dict[str, Any] = {}
        done = self.data["done"][-last:]
        for m in self.checks_min:
            rows = [d["results"][str(m)] for d in done if str(m) in d["results"]]
            if rows:
                out[f"{m}m"] = {
                    "n": len(rows),
                    "avg_missed_upside": round(statistics.fmean(r["missed_upside"] for r in rows), 4),
                    "avg_saved_crash": round(statistics.fmean(r["saved_crash"] for r in rows), 4),
                    "sold_too_early_share": round(sum(1 for r in rows if r["ratio"] > 1.10) / len(rows), 3),
                }
        by_reason: dict[str, list[float]] = {}
        for d in done:
            r60 = d["results"].get(str(self.checks_min[-1]))
            if r60:
                bucket = d["reason"].split(":")[0].split(" (")[0][:24]
                by_reason.setdefault(bucket, []).append(r60["ratio"])
        out["post_exit_ratio_by_exit_reason"] = {k: round(statistics.fmean(v), 3) for k, v in by_reason.items()}
        return out


# ---------------------------------------------------------------------------------------
# Overrides file + hot reload
# ---------------------------------------------------------------------------------------
class RuntimeOverrides:
    def __init__(self, path: Path, settings: Settings) -> None:
        self.path = path
        self.settings = settings
        self.defaults = {name: float(get_param(settings, name)) for name in TUNABLE}
        self._mtime = 0.0
        self.demoted: list[str] = []

    def write(self, params: dict[str, float], demoted: list[str], source: str, rationale: str) -> dict:
        doc = {"version": int(time.time()), "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "source": source, "params": params, "demoted_whales": demoted, "rationale": rationale}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=2))
        os.replace(tmp, self.path)
        return doc

    def maybe_reload(self, cfo=None) -> dict[str, float] | None:
        """Apply the overrides file if it changed since the last look. Values are re-clamped to
        the hard bounds on load, so a hand-edited file cannot break the rails either."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            return None
        if mtime == self._mtime:
            return None
        self._mtime = mtime
        try:
            doc = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            log.warning("runtime_overrides.json unreadable, ignored: %s", exc)
            return None
        applied = {}
        for name, value in (doc.get("params") or {}).items():
            if name in TUNABLE:
                lo, hi = TUNABLE[name]
                try:
                    v = min(max(float(value), lo), hi)
                except (TypeError, ValueError):
                    continue
                set_param(self.settings, name, v)
                applied[name] = v
        self.demoted = [w for w in doc.get("demoted_whales") or [] if isinstance(w, str)]
        if cfo is not None:
            for w in self.demoted:
                cfo.book(w).demoted = True
        log.info("hot-reloaded runtime overrides v%s (%s): %s", doc.get("version"), doc.get("source"), applied)
        return applied


# ---------------------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------------------
EVOLVE_SYSTEM = """You are the risk and exit tuner of a Solana memecoin copy-trading bot. You receive
its accounting ledger, per-whale results, post-exit regret (price 15/60 minutes after each exit vs
our exit price, by exit reason), the current tunable parameters and their hard bounds. Propose
small, evidence-based adjustments. Prefer doing nothing over overfitting to a few trades.
Answer with ONLY a JSON object:
{"params": {"<name>": number, ...}, "demote_whales": ["<address>", ...], "rationale": "<two sentences>"}"""


def rule_based_proposal(settings: Settings, regret: dict, whales: dict[str, Any], closes: list[dict]) -> tuple[dict, list[str], str]:
    """Transparent fallback when no AI endpoint is reachable."""
    params: dict[str, float] = {}
    notes: list[str] = []
    r60 = regret.get(f"{settings.evolve.regret_checks_min[-1]}m")
    if r60 and r60["n"] >= 5:
        if r60["avg_missed_upside"] > 0.30 and r60["avg_missed_upside"] > 2 * r60["avg_saved_crash"]:
            for name in ("exits.trailing_stop_pct", "exits.moonbag_trailing_stop_pct"):
                params[name] = get_param(settings, name) * 1.2
            notes.append(f"exits left {r60['avg_missed_upside']:.0%} on the table after 60 min: widen trails")
        elif r60["avg_saved_crash"] > 0.30 and r60["avg_saved_crash"] > 2 * r60["avg_missed_upside"]:
            notes.append("exits are dodging crashes well: keep exit settings")
    recent = closes[-20:]
    if len(recent) >= 8:
        stops = [c for c in recent if "hard stop" in c.get("reason", "") or "WRITE-OFF" in c.get("reason", "")]
        if len(stops) / len(recent) >= 0.4:
            params["safety.min_liquidity_usd"] = get_param(settings, "safety.min_liquidity_usd") * 1.25
            params["safety.max_chase_pct"] = get_param(settings, "safety.max_chase_pct") * 0.8
            notes.append(f"{len(stops)}/{len(recent)} recent exits were stops/rugs: demand deeper pools, chase less")
    demote = [w for w, b in whales.items() if b.get("trades", 0) >= 3 and b.get("profit_factor", 0) < 1.0]
    if demote:
        notes.append(f"demote {len(demote)} whale(s) with PF < 1 over >= 3 trades")
    return params, demote, "; ".join(notes) or "no change: not enough evidence"


async def evolve(settings: Settings, cfo, regret: RegretTracker, overrides: RuntimeOverrides, analyst,
                 closes: list[dict], log_path: Path) -> dict:
    whales = {w: {"trades": b.trades, "wins": b.wins, "losses": b.losses, "profit_factor": round(b.profit_factor, 3),
                  "realized_sol": b.realized_lamports / 1e9, "consecutive_losses": b.consecutive_losses}
              for w, b in cfo.state.whales.items()}
    regret_summary = regret.summary()
    current = {name: get_param(settings, name) for name in TUNABLE}
    source, params, demote, rationale = "rules", {}, [], ""
    if analyst is not None and analyst.available:
        out = await analyst.ask(EVOLVE_SYSTEM, {
            "ledger": cfo.state.model_dump(exclude={"whales", "lock_events"}), "whales": whales,
            "regret": regret_summary, "recent_closes": closes[-30:],
            "params": current, "bounds": {k: list(v) for k, v in TUNABLE.items()},
        }, max_tokens=3000)
        if out:
            source = f"ai:{analyst.model}"
            params, demote, rationale = out.get("params") or {}, out.get("demote_whales") or [], str(out.get("rationale", ""))
    if source == "rules":
        params, demote, rationale = rule_based_proposal(settings, regret_summary, whales, closes)
    clamped = clamp_proposal(settings, params, settings.evolve.max_step_frac)
    known = set(cfo.state.whales)
    demote = sorted({w for w in demote if isinstance(w, str) and w in known} | set(overrides.demoted))
    merged = {**current, **clamped}
    changed = {k: v for k, v in merged.items() if abs(v - overrides.defaults[k]) > 1e-12}
    doc = overrides.write(changed, demote, source, rationale[:600])
    with log_path.open("a") as f:
        f.write(json.dumps({"ts": int(time.time()), "source": source, "proposed": params, "applied": clamped,
                            "demoted": demote, "rationale": rationale[:600], "regret": regret_summary}) + "\n")
    return doc
