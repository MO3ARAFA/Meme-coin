"""Central configuration.

Every threshold from the engineering mandate lives here, typed and validated by pydantic.
Values come from environment variables / `.env` (prefix-free, case-insensitive), so nothing
needs to be edited in code. Secrets (PRIVATE_KEY) are NOT read here: see `wallet_vault.py`.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionMode(str, Enum):
    SHADOW_PAPER = "SHADOW_PAPER"
    LIVE = "LIVE"


class PriorityMode(str, Enum):
    """How the swap pays to land: a capped priority fee, or a capped Jito tip."""

    PRIORITY_FEE = "PRIORITY_FEE"
    JITO_TIP = "JITO_TIP"


class ScorerConfig(BaseModel):
    """Module A thresholds: which wallets are copy-safe."""

    lookback_days: int = 30
    min_lookback_days: int = 14
    max_signatures_per_wallet: int = 1500
    min_closed_trades: int = 20
    min_win_rate: float = 0.55
    # The mandate has a gap (accept <=82%, reject >85%). We close it: anything above 82%
    # is rejected — a higher win rate on memecoins is a latency/insider edge we can't copy.
    max_win_rate: float = 0.82
    min_avg_hold_s: float = 300.0
    min_median_hold_s: float = 300.0
    # Hard blacklist: farmers/bots that flip in under two minutes.
    flip_threshold_s: float = 120.0
    max_flip_ratio: float = 0.30  # share of trades whose FIRST sell came < flip_threshold_s after the buy
    min_median_roi: float = 0.15
    # Extra robustness on top of the mandate:
    min_profit_factor: float = 1.5  # gross profit / gross loss
    max_top_trade_pnl_share: float = 0.50  # one lottery ticket can't be >50% of total profit
    sniper_window_s: float = 2.0  # buy within ~5 slots of pool creation counts as block-0/1
    max_sniper_ratio: float = 0.30
    max_transfer_out_ratio: float = 0.25  # tokens moved to other wallets instead of sold (insider/bundler tell)
    # Buys paid from a trading-bot vault (not the wallet) look nearly free in balance deltas,
    # then the sell looks like a 1000x. Such cycles are excluded as "unpriced"; a wallet that
    # trades mostly this way can't be copied (its buy signals carry no usable price).
    min_cycle_buy_sol: float = 0.01
    max_cycle_roi: float = 20.0
    max_unpriced_ratio: float = 0.25
    min_avg_buy_sol: float = 0.1
    # Scratch-aware ROI: discretionary pros scratch dead trades at ~0%, which drags the plain
    # median down. Pass if the median of NON-scratch trades clears min_median_roi, or if the
    # trimmed mean (top outliers removed) and profit factor are both strong.
    scratch_band: float = 0.03
    trimmed_top_frac: float = 0.05
    min_trimmed_mean_roi: float = 0.12
    alt_min_profit_factor: float = 1.6
    # Latency-adjusted copy replay: re-price every copyable historical trade as WE would
    # have filled it (entry worse by the penalty, our fee cap paid on both legs). The edge
    # must survive this, equal-weighted like our fixed position sizing.
    # Convex imitation penalty: a follower pays more the bigger the whale's own buy was.
    #   entry penalty = base + min(cap, whale_buy_sol * per_sol)   (+ our fee cap on both legs)
    replay_entry_penalty: float = 0.015  # base copy latency
    replay_penalty_per_sol: float = 0.008
    replay_penalty_cap: float = 0.06
    replay_leg_fee: float = 0.012
    replay_exit_penalty: float = 0.0
    replay_min_buy_sol: float = 0.25  # buys the live gate would skip anyway are not replayed
    # Our exit engine force-closes at EXITS__MAX_HOLD_MINUTES: whale gains realized after that
    # were never available to us, so those trades are not replayed.
    replay_max_hold_minutes: float = 240.0
    # Moonbag replay: mirrors the live exit engine. Trades whose copied return reached the
    # scale-out level sell half there and ride the rest to the whale's exit (no time cap);
    # losses are capped near our hard stop.
    replay_scale_out: float = 0.45
    replay_loss_floor: float = -0.30  # hard stop -22% plus slippage
    # Anti-farm: scripted wallets trade on timers (low coefficient of variation of gaps).
    min_timing_cv: float = 0.35
    timing_cv_min_samples: int = 30
    # Fingerprint sybil merge: near-identical execution fingerprint AND co-buying the same
    # tokens within the window, on >= this many tokens. Fingerprint alone is not enough:
    # thousands of independent users share the defaults of one trading frontend.
    fingerprint_similarity: float = 0.90
    co_buy_window_s: float = 60.0
    co_buy_min_tokens: int = 2
    # Co-slot cabal detection (finalists only; RPC heavy)
    cabal_sample_buys: int = 40
    max_co_slot_ratio: float = 0.25
    max_bundled_buy_ratio: float = 0.20  # buys whose tx also delivered the token to other wallets
    replay_min_trades: int = 15
    replay_min_profit_factor: float = 1.35
    replay_min_expectancy: float = 0.0
    # Adversarial checks
    bait_size_frac: float = 0.30  # buy < 30% of the wallet's median buy = possible bait
    max_token_recipients: int = 3  # tokens shipped to >= this many wallets = feeder/sybil
    min_link_sol: float = 0.05  # direct SOL transfers >= this between candidates link them
    max_trades_per_day: float = 40.0  # above this it is a bot, not a trader
    max_days_since_last_trade: float = 4.0
    top_n: int = 5


class HarvestConfig(BaseModel):
    """`harvest`: cross-token mid-wave discovery of candidate wallets for the scorer."""

    min_liquidity_usd: float = 40_000
    min_age_days: float = 1.0
    max_age_days: float = 14.0
    min_volume_h24_usd: float = 100_000
    max_tokens: int = 80
    signature_pages: int = 8  # 1000 pool signatures per page; sampled evenly = mid-wave, not just the latest
    sample_per_token: int = 120
    min_swap_sol: float = 0.25
    max_deep_checks: int = 80
    max_tx_per_day: float = 80.0
    deep_history_txs: int = 250
    min_profitable_tokens: int = 2
    top_n: int = 40
    co_buyer_trades: int = 30  # seed's most profitable trades to mine for leaders
    co_buyer_sample: int = 150  # transactions sampled per trade window
    co_buyer_window_s: float = 900.0


class SafetyConfig(BaseModel):
    """Module B thresholds: the pre-buy gate."""

    min_liquidity_usd: float = 25_000
    min_market_cap_usd: float = 60_000
    max_chase_pct: float = 0.12  # skip if our fill is >12% worse than the whale's
    max_price_impact_pct: float = 0.01
    # Buy-then-sell quote round trip. Catches sell taxes, honeypots and fat DEX fees in one number.
    max_roundtrip_loss_pct: float = 0.05
    reentry_cooldown_s: int = 24 * 3600
    max_signal_age_s: float = 25.0  # whale tx older than this (e.g. after a reconnect) is stale
    bait_size_frac: float = 0.30  # whale buy < 30% of its median buy size = inducement bait -> abort
    cluster_window_s: float = 600.0  # 2+ independent approved wallets buying within this = cluster
    # Holder distribution (getTokenLargestAccounts, runs in parallel with the other checks).
    # Pools, LP vaults, bonding curves and burn addresses are excluded before measuring.
    holder_check: bool = True
    max_top5_holder_pct: float = 0.35
    max_single_holder_pct: float = 0.12
    identical_holder_tolerance: float = 0.002  # amounts within 0.2% of each other ...
    identical_holder_min_count: int = 4  # ... held by >= 4 top wallets = bundler split (3 gave false positives on 45 live tokens)
    identical_holder_min_pct: float = 0.005  # each of those >= 0.5% of supply
    # Per-wallet imitation budget: abort if (our price drift vs the whale + round-trip cost)
    # eats this fraction of the wallet's historical raw edge.
    max_edge_consumed: float = 0.65
    reject_bundled_whale_buy: bool = True  # whale's buy tx also delivered tokens to other wallets
    min_whale_buy_sol: float = 0.25  # ignore dust buys (often bait)
    gate_latency_budget_ms: int = 300  # target; logged when exceeded
    gate_hard_timeout_ms: int = 2500  # abort the copy if checks take longer than this


class ExitConfig(BaseModel):
    """Module C thresholds: our independent exit engine. Ratios are NET of fees and impact."""

    whale_sell_trigger_frac: float = 0.30
    scale_out_profit: float = 0.45
    scale_out_fraction: float = 0.50
    moonbag_floor_profit: float = 0.15  # after the scale-out, the runner never gives back below +15%
    hard_stop_loss: float = 0.22
    trailing_activation_profit: float = 0.25
    trailing_stop_pct: float = 0.15
    time_decay_minutes: float = 45.0
    time_decay_min_profit: float = 0.15
    max_hold_minutes: float = 240.0  # cap for UNSCALED positions only; a de-risked moonbag runs uncapped
    moonbag_trailing_stop_pct: float = 0.25  # runner trail after the scale-out
    cluster_trailing_stop_pct: float = 0.30  # runner trail for a HIGH_CONVICTION_CLUSTER
    # Auto-quarantine: a wallet that dumps this fast after its own buy, this many times, is
    # hunting copy-traders and is removed from the approved list.
    fast_dump_window_s: float = 90.0
    quarantine_strikes: int = 2
    poll_interval_s: float = 2.0  # cheap DexScreener mark polling
    quote_refresh_s: float = 12.0  # executable Jupiter sell quote refresh per position
    no_route_emergency_s: float = 90.0  # no sell route this long => treat as rugged
    exit_slippage_bps: int = 300
    emergency_slippage_bps: int = 1500


class RiskConfig(BaseModel):
    """Module D: $100 micro-capital sizing, fee guard, circuit breaker."""

    position_size_frac: float = 0.10
    max_open_positions: int = 3
    # A moonbag has already returned its capital and sits above a +15% floor: it is not risk.
    # Counting it toward the limit would let one uncapped runner block new entries for days.
    moonbags_count_toward_limit: bool = False
    max_leg_cost_pct: float = 0.012  # DEX fee + price impact + network fee, per leg
    min_priority_fee_lamports: int = 10_000
    max_priority_fee_lamports: int = 2_000_000
    priority_mode: PriorityMode = PriorityMode.PRIORITY_FEE
    daily_loss_limit_frac: float = 0.15
    halt_hours: float = 24.0
    sol_reserve: float = 0.02  # never trade below this: rent + fees for exits
    entry_slippage_bps: int = 200


class LLMConfig(BaseModel):
    """Optional AI forensics (Anthropic-compatible endpoint). Never in the pre-buy hot path;
    every call is async, time-boxed and fail-safe: if the model is unreachable the bot runs
    on its quantitative rules alone."""

    base_url: str = ""  # empty = Anthropic API
    api_key: str = ""
    model: str = ""  # empty = auto-probe `probe_models` in order
    probe_models: list[str] = Field(default_factory=lambda: [
        "claude-sonnet-5-5", "claude-opus-5-5", "claude-sonnet-5", "claude-sonnet-4-6",
        "claude-sonnet-4-20250514", "claude-3-7-sonnet-latest", "claude-3-5-sonnet-latest",
    ])
    timeout_s: float = 45.0
    max_risk_score: int = 30  # AI risk above this vetoes an approval (veto only, never approves)
    eject_trap_probability: float = 0.75  # needs an on-chain red flag too
    overwatch_delay_s: float = 2.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def sdk_base_url(self) -> str:
        """The SDK appends /v1/messages itself: accept routers configured as '.../v1'. Never
        None: the SDK would then read ANTHROPIC_BASE_URL from the process environment, which
        could route this key somewhere the operator did not configure."""
        url = self.base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[: -len("/v1")]
        return url or "https://api.anthropic.com"


class ShieldConfig(BaseModel):
    """Pillar 1 — pre-trade kill switch: "am I the exit liquidity?"."""

    min_net_ev: float = 0.0  # veto if expected net profit after all frictions is <= this
    slippage_reserve_pct: float = 0.005  # extra adverse fill we budget beyond the quote
    max_exit_liquidity_risk: int = 60  # composite 0-100; >= this is a hard veto
    rugcheck: bool = True  # public RugCheck summary, in parallel; fails OPEN (on-chain checks stay primary)
    rugcheck_timeout_s: float = 1.2
    rugcheck_max_normalised: int = 60  # their 0-100 risk scale


class RadarConfig(BaseModel):
    """Pillar 2 — social / narrative / new-token radar."""

    min_liquidity_usd: float = 35_000
    min_age_hours: float = 1.0
    max_age_days: float = 7.0
    max_tokens_per_pass: int = 15
    min_narrative_score: int = 50  # AI score 0-100 when the AI endpoint is up
    poll_interval_s: float = 300.0


class TreasuryConfig(BaseModel):
    """Pillar 3 — autonomous CFO: meritocracy sizing and high-water-mark profit lock."""

    merit_size_frac: float = 0.12
    base_size_frac: float = 0.10
    probation_size_frac: float = 0.05
    merit_min_trades: int = 3
    merit_profit_factor: float = 1.5
    probation_losses: int = 2  # consecutive losses on one whale -> probation until it wins again
    hwm_step: float = 0.20  # every +20% of equity ...
    lock_fraction: float = 0.50  # ... locks 50% of those gains into an untouchable reserve


class EvolveConfig(BaseModel):
    """Pillar 4 — self-improver: regret analysis and bounded auto-tuning."""

    every_trades: int = 10
    every_hours: float = 12.0
    regret_checks_min: list[int] = Field(default_factory=lambda: [15, 60])
    max_step_frac: float = 0.25  # one tuning round can move a parameter by at most 25%
    reload_interval_s: float = 10.0


class LiveGateConfig(BaseModel):
    """What shadow mode must prove before LIVE is allowed to start."""

    min_shadow_trades: int = 50
    min_profit_factor: float = 1.3
    min_expectancy_pct: float = 0.02  # average net return per trade
    max_drawdown_pct: float = 0.20


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    execution_mode: ExecutionMode = ExecutionMode.SHADOW_PAPER

    # Endpoints. Use a Helius/QuickNode/Triton URL for anything beyond testing:
    # the public endpoint rate-limits hard and its websocket drops subscriptions.
    rpc_url: str = "https://api.mainnet-beta.solana.com"
    ws_url: str = ""  # derived from rpc_url if empty
    rpc_rps: float = 8.0
    jupiter_base_url: str = "https://lite-api.jup.ag/swap/v1"
    jupiter_api_key: str = ""
    jupiter_rps: float = 0.8  # lite-api 429s on bursts; raise with an API key
    dexscreener_base_url: str = "https://api.dexscreener.com"
    dexscreener_rps: float = 4.0

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    data_dir: Path = Path("data")
    approved_wallets_path: Path = Path("approved_wallets.json")
    seed_wallets_path: Path = Path("seed_wallets.txt")

    shadow_starting_sol: float = 1.0  # ~$100 at ~$100/SOL; set to your real budget
    # In shadow mode we can't know where our tx would have landed. We assume it lands this
    # much worse than the quote we fetched — pessimism here protects the LIVE decision.
    shadow_latency_haircut_bps: int = 75
    shadow_assumed_priority_lamports: int = 100_000

    # LIVE: simulate every signed swap and refuse to send if it would cost more SOL than
    # the trade + fee cap. Costs one RPC call (~100ms); keep it on.
    live_simulate_before_send: bool = True

    listener_mode: str = "ws"  # "ws" or "poll"
    poll_interval_s: float = 2.0

    scorer: ScorerConfig = Field(default_factory=ScorerConfig)
    harvest: HarvestConfig = Field(default_factory=HarvestConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    exits: ExitConfig = Field(default_factory=ExitConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    live_gate: LiveGateConfig = Field(default_factory=LiveGateConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    shield: ShieldConfig = Field(default_factory=ShieldConfig)
    radar: RadarConfig = Field(default_factory=RadarConfig)
    treasury: TreasuryConfig = Field(default_factory=TreasuryConfig)
    evolve: EvolveConfig = Field(default_factory=EvolveConfig)

    @field_validator("listener_mode")
    @classmethod
    def _listener_mode(cls, v: str) -> str:
        v = v.lower()
        if v not in {"ws", "poll"}:
            raise ValueError("listener_mode must be 'ws' or 'poll'")
        return v

    @model_validator(mode="after")
    def _derive(self) -> "Settings":
        if not self.ws_url:
            if self.rpc_url.startswith("https://"):
                self.ws_url = "wss://" + self.rpc_url[len("https://") :]
            elif self.rpc_url.startswith("http://"):
                self.ws_url = "ws://" + self.rpc_url[len("http://") :]
        if self.jupiter_api_key and "lite-api.jup.ag" in self.jupiter_base_url:
            # Keyed requests go to the higher-limit host.
            self.jupiter_base_url = "https://api.jup.ag/swap/v1"
        return self

    @property
    def is_live(self) -> bool:
        return self.execution_mode is ExecutionMode.LIVE

    @property
    def trades_csv(self) -> Path:
        name = "live_trades.csv" if self.is_live else "shadow_trades.csv"
        return self.data_dir / name

    @property
    def state_path(self) -> Path:
        name = "live_state.json" if self.is_live else "shadow_state.json"
        return self.data_dir / name


def _anthropic_aliases() -> tuple[str, str, str]:
    """(api_key, base_url, model) from the standard Anthropic variable names. Key and URL are
    always taken from the SAME source (.env first, then the process environment), so a key is
    never paired with a base URL set somewhere else."""
    from dotenv import dotenv_values

    for source in (dotenv_values(".env"), os.environ):
        key = (source.get("ANTHROPIC_API_KEY") or "").strip()
        if key:
            return key, (source.get("ANTHROPIC_BASE_URL") or "").strip(), (source.get("MODEL_ID") or "").strip()
    return "", "", ""


def load_settings() -> Settings:
    settings = Settings()
    # Accept the standard Anthropic variable names as aliases for the LLM__ settings.
    llm = settings.llm
    if not llm.api_key:
        llm.api_key, alias_url, alias_model = _anthropic_aliases()
        llm.base_url = llm.base_url or alias_url
        llm.model = llm.model or alias_model
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
