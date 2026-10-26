"""Pillar 2 — social, narrative and new-token radar; auto-expanding whale universe.

Feeds (all free, all verified reachable): DexScreener `token-boosts/latest`, `token-boosts/top`,
`community-takeovers/latest`, `token-profiles/latest` (which carry the token's X/Telegram/
website links), and GeckoTerminal's PumpSwap pools — a Pump.fun token that migrated is a new
PumpSwap pool, so this stands in for Pump.fun's own feeds (Cloudflare-blocked to scripts).

Social legitimacy, before any AI:
  * a real X account link beats a link to someone else's tweet (`/status/...`), a Telegram and
    a website add weight, a community takeover is a positive sign;
  * **recycled links**: a URL already seen on a DIFFERENT token (stored in radar_state.json)
    is the classic relaunch-scam tell and sinks the score.
When the AI endpoint is up it also scores narrative strength; otherwise heuristics alone decide.

Universe expansion: for qualifying tokens (1 h-7 d old, >= $35k liquidity), sample the pool's
history, deep-check its profitable traders on their OWN history (realized profit in >= 2 tokens),
and append the winners to `data/score_queue.txt` for `python main.py score --with-queue`.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .config import Settings
from .constants import NON_MEME_MINTS, STABLE_MINTS, WSOL_MINT
from .http_utils import RateLimiter, request_json

log = logging.getLogger(__name__)

DEX = "https://api.dexscreener.com"
GECKO = "https://api.geckoterminal.com/api/v2/networks/solana"

NARRATIVE_SYSTEM = """You assess the social legitimacy and narrative strength of a new Solana memecoin
from its name, description and links. Recycled or impersonating links, copy-paste descriptions,
links to unrelated celebrity tweets, and generic hype with no community are red flags. A distinct,
timely narrative with a real community account is a green flag. Answer with ONLY a JSON object:
{"narrative_score": integer 0-100, "recycled_or_scam": true|false, "narrative": "<short label>",
 "reason": "<one sentence>"}"""


@dataclass
class RadarToken:
    mint: str
    symbol: str = ""
    description: str = ""
    sources: set[str] = field(default_factory=set)
    links: list[dict] = field(default_factory=list)
    liquidity_usd: float = 0.0
    age_hours: float = 0.0
    pool: str = ""
    dex: str = ""
    volume_h24_usd: float = 0.0
    social_score: int = 0
    social_notes: list[str] = field(default_factory=list)
    ai_score: int | None = None
    ai_narrative: str = ""

    @property
    def final_score(self) -> int:
        """The AI can lower a token's score but only nudge it up (average), never inflate it."""
        if self.ai_score is None:
            return self.social_score
        if self.ai_score < self.social_score:
            return self.ai_score
        return (self.social_score + self.ai_score) // 2


def _norm_link(url: str) -> str:
    p = urlparse(url.strip().lower())
    return (p.netloc.removeprefix("www.") + p.path.rstrip("/")) if p.netloc else url.strip().lower()


def social_legitimacy(tok: RadarToken, link_index: dict[str, list[str]]) -> tuple[int, list[str]]:
    """Heuristic 0-100 legitimacy score with reasons. `link_index` maps normalized link -> mints."""
    score, notes = 0, []
    kinds = {(l.get("type") or l.get("label") or "").lower(): l.get("url", "") for l in tok.links}
    twitter = next((u for k, u in kinds.items() if k in ("twitter", "x")), "")
    if twitter:
        if "/status/" in twitter:
            score += 5
            notes.append("X link is a tweet, not a project account")
        else:
            score += 30
            notes.append("has X account")
    if any(k == "telegram" for k in kinds):
        score += 20
        notes.append("has Telegram")
    if any(k in ("website", "web") for k in kinds):
        score += 15
        notes.append("has website")
    if "cto" in tok.sources:
        score += 15
        notes.append("community takeover")
    if tok.sources & {"boost", "boost_top"}:
        score += 5
    if len(tok.description) >= 40:
        score += 10
    recycled = [l["url"] for l in tok.links if l.get("url") and any(m != tok.mint for m in link_index.get(_norm_link(l["url"]), []))]
    if recycled:
        score -= 60
        notes.append(f"RECYCLED link(s) used by other tokens: {recycled[:2]}")
    return max(0, min(100, score)), notes


class SocialRadar:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.s = settings
        self.client = client
        self.state_path = settings.data_dir / "radar_state.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {"links": {}, "seen": {}}
        self.dex_lim = RateLimiter(settings.dexscreener_rps, burst=2)
        self.gecko_lim = RateLimiter(0.45, burst=2)

    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=1))

    async def _get(self, url: str, limiter: RateLimiter) -> object:
        try:
            return await request_json(self.client, "GET", url, limiter=limiter, retries=1,
                                      headers={"accept": "application/json"})
        except Exception as exc:
            log.debug("radar feed %s failed: %s", url, exc)
            return None

    async def poll_feeds(self) -> dict[str, RadarToken]:
        toks: dict[str, RadarToken] = {}

        def add(mint: str, source: str, row: dict | None = None) -> None:
            if not mint or mint in NON_MEME_MINTS:
                return
            t = toks.setdefault(mint, RadarToken(mint))
            t.sources.add(source)
            if row:
                t.links = t.links or list(row.get("links") or [])
                t.description = t.description or str(row.get("description") or "")[:500]

        for path, source in (("/token-boosts/latest/v1", "boost"), ("/token-boosts/top/v1", "boost_top"),
                             ("/community-takeovers/latest/v1", "cto"), ("/token-profiles/latest/v1", "profile")):
            for row in (await self._get(DEX + path, self.dex_lim)) or []:
                if isinstance(row, dict) and row.get("chainId") == "solana":
                    add(row.get("tokenAddress", ""), source, row)
        for page in (1, 2):
            data = await self._get(f"{GECKO}/dexes/pumpswap/pools?page={page}", self.gecko_lim) or {}
            for pool in data.get("data", []) if isinstance(data, dict) else []:
                add(pool["relationships"]["base_token"]["data"]["id"].removeprefix("solana_"), "migrated")
        return toks

    async def qualify(self, toks: dict[str, RadarToken]) -> list[RadarToken]:
        cfg = self.s.radar
        mints = list(toks)
        now_ms = time.time() * 1000
        out: list[RadarToken] = []
        for i in range(0, len(mints), 30):
            rows = await self._get(f"{DEX}/tokens/v1/solana/{','.join(mints[i:i + 30])}", self.dex_lim) or []
            by_mint: dict[str, list[dict]] = {}
            for p in rows:
                if isinstance(p, dict) and p.get("chainId") == "solana":
                    by_mint.setdefault(p["baseToken"]["address"], []).append(p)
            for mint, pairs in by_mint.items():
                t = toks.get(mint)
                created = [p["pairCreatedAt"] for p in pairs if p.get("pairCreatedAt")]
                priced = [p for p in pairs if p["quoteToken"]["address"] in {WSOL_MINT, *STABLE_MINTS}
                          and (p.get("liquidity") or {}).get("usd")]
                if t is None or not created or not priced:
                    continue
                best = max(priced, key=lambda p: p["liquidity"]["usd"])
                t.symbol = best["baseToken"].get("symbol", "")
                t.age_hours = (now_ms - min(created)) / 3_600_000
                t.liquidity_usd = float(best["liquidity"]["usd"])
                t.pool, t.dex = best["pairAddress"], best.get("dexId", "")
                t.volume_h24_usd = sum(float((p.get("volume") or {}).get("h24") or 0) for p in pairs)
                info_links = []
                for p in pairs:
                    info = p.get("info") or {}
                    info_links += [{"type": s.get("type"), "url": s.get("url")} for s in info.get("socials") or []]
                    info_links += [{"label": "website", "url": w.get("url")} for w in info.get("websites") or []]
                t.links = t.links or info_links
                if cfg.min_age_hours <= t.age_hours <= cfg.max_age_days * 24 and t.liquidity_usd >= cfg.min_liquidity_usd:
                    out.append(t)
        return out

    def score_social(self, toks: list[RadarToken]) -> None:
        index: dict[str, list[str]] = self.state["links"]
        for t in toks:
            t.social_score, t.social_notes = social_legitimacy(t, index)
        for t in toks:  # remember links AFTER scoring, so a token never flags itself
            for l in t.links:
                if l.get("url"):
                    mints = index.setdefault(_norm_link(l["url"]), [])
                    if t.mint not in mints:
                        mints.append(t.mint)
            self.state["seen"][t.mint] = int(time.time())

    async def score_narrative(self, toks: list[RadarToken], analyst) -> None:
        if analyst is None or not analyst.available:
            return
        for t in toks:
            out = await analyst.ask(NARRATIVE_SYSTEM, {"symbol": t.symbol, "description": t.description,
                                                       "links": t.links, "sources": sorted(t.sources)}, max_tokens=600)
            if out and isinstance(out.get("narrative_score"), (int, float)):
                t.ai_score = 0 if out.get("recycled_or_scam") else int(max(0, min(100, out["narrative_score"])))
                t.ai_narrative = str(out.get("narrative", ""))[:60]


def append_queue(path: Path, wallets: list[str], note: str) -> int:
    existing = set()
    if path.exists():
        existing = {line.split("#")[0].strip() for line in path.read_text().splitlines()}
    new = [w for w in wallets if w not in existing]
    if new:
        with path.open("a") as f:
            f.writelines(f"{w}  # {note}\n" for w in new)
    return len(new)


async def run_radar(settings: Settings, client: httpx.AsyncClient, rpc, dex, jupiter, analyst, *,
                    expand: bool) -> list[RadarToken]:
    from .harvester import Candidate, HarvestToken, deep_check, prescreen, sample_pool
    from .wallet_scorer import WalletScorer

    radar = SocialRadar(settings, client)
    raw = await radar.poll_feeds()
    qualified = await radar.qualify(raw)
    radar.score_social(qualified)
    await radar.score_narrative(qualified, analyst)
    min_score = settings.radar.min_narrative_score
    ranked = sorted(qualified, key=lambda t: (t.final_score, t.volume_h24_usd), reverse=True)
    radar.save()
    (settings.data_dir / "radar_report.json").write_text(json.dumps(
        [{**asdict(t), "sources": sorted(t.sources), "final_score": t.final_score} for t in ranked], indent=1, default=str))
    log.info("radar: %d feed tokens, %d qualify (1h-%.0fd, liq >= $%.0fk)", len(raw), len(qualified),
             settings.radar.max_age_days, settings.radar.min_liquidity_usd / 1e3)
    for t in ranked:
        log.info("  %-10s score=%3d%s age=%5.1fh liq=$%-9.0f %s | %s", t.symbol[:10], t.final_score,
                 f" (AI {t.ai_score} {t.ai_narrative})" if t.ai_score is not None else "", t.age_hours, t.liquidity_usd,
                 ",".join(sorted(t.sources)), "; ".join(t.social_notes))
    if not expand:
        return ranked
    picks = [t for t in ranked if t.final_score >= min_score][: settings.radar.max_tokens_per_pass]
    if not picks:
        log.info("radar: nothing above social score %d to expand", min_score)
        return ranked
    q = await jupiter.quote(WSOL_MINT, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", 1_000_000_000, 50)
    usd_per_sol = q.out_amount / 1e6
    scorer = WalletScorer(settings, rpc, dex, jupiter)
    cands: dict[str, Candidate] = {}
    for t in picks:
        ht = HarvestToken(t.mint, t.symbol, t.pool, t.dex, t.liquidity_usd, t.volume_h24_usd, round(t.age_hours / 24, 2))
        for w, row in (await sample_pool(rpc, scorer, ht, settings, usd_per_sol)).items():
            cands.setdefault(w, Candidate(w)).tokens[t.symbol] = row
    ranked_c = sorted(cands.values(), key=lambda c: (len(c.tokens), c.sampled_sells, c.sampled_sol), reverse=True)
    to_screen = ranked_c[: settings.harvest.max_deep_checks * 2]
    survivors = await prescreen(rpc, to_screen, settings)
    winners = []
    for c in [c for c in to_screen if c.address in survivors][: settings.harvest.max_deep_checks]:
        try:
            await deep_check(scorer, c, survivors[c.address], settings, usd_per_sol)
        except Exception:
            continue
        if c.profitable_tokens >= settings.harvest.min_profitable_tokens and c.realized_pnl_sol > 0:
            winners.append(c.address)
    added = append_queue(settings.data_dir / "score_queue.txt", winners,
                         f"radar {time.strftime('%Y-%m-%d')}: early profitable trader of {len(picks)} trending tokens")
    log.info("radar expansion: %d traders sampled, %d pre-screened, %d winners, %d new in score queue",
             len(cands), len(survivors), len(winners), added)
    return ranked
