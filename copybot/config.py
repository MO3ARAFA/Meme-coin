"""Central configuration.

Every threshold from the engineering mandate lives here, typed and validated by pydantic.
Values come from environment variables / `.env` (prefix-free, case-insensitive), so nothing
needs to be edited in code. Secrets (PRIVATE_KEY) are NOT read here: see `wallet_vault.py`.
"""

from __future__ import annotations

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
    min_avg_buy_sol: float = 0.1
    max_trades_per_day: float = 40.0  # above this it is a bot, not a trader
    max_days_since_last_trade: float = 4.0
    top_n: int = 5


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
    min_whale_buy_sol: float = 0.25  # ignore dust buys (often bait)
    gate_latency_budget_ms: int = 300  # target; logged when exceeded
    gate_hard_timeout_ms: int = 2500  # abort the copy if checks take longer than this


class ExitConfig(BaseModel):
    """Module C thresholds: our independent exit engine. Ratios are NET of fees and impact."""

    whale_sell_trigger_frac: float = 0.30
    scale_out_profit: float = 0.45
    scale_out_fraction: float = 0.50
    breakeven_stop_profit: float = 0.02
    hard_stop_loss: float = 0.22
    trailing_activation_profit: float = 0.25
    trailing_stop_pct: float = 0.15
    time_decay_minutes: float = 45.0
    time_decay_min_profit: float = 0.15
    max_hold_minutes: float = 240.0  # absolute cap: never bag-hold a memecoin overnight
    poll_interval_s: float = 2.0  # cheap DexScreener mark polling
    quote_refresh_s: float = 12.0  # executable Jupiter sell quote refresh per position
    no_route_emergency_s: float = 90.0  # no sell route this long => treat as rugged
    exit_slippage_bps: int = 300
    emergency_slippage_bps: int = 1500


class RiskConfig(BaseModel):
    """Module D: $100 micro-capital sizing, fee guard, circuit breaker."""

    position_size_frac: float = 0.10
    max_open_positions: int = 3
    max_leg_cost_pct: float = 0.012  # DEX fee + price impact + network fee, per leg
    min_priority_fee_lamports: int = 10_000
    max_priority_fee_lamports: int = 2_000_000
    priority_mode: PriorityMode = PriorityMode.PRIORITY_FEE
    daily_loss_limit_frac: float = 0.15
    halt_hours: float = 24.0
    sol_reserve: float = 0.02  # never trade below this: rent + fees for exits
    entry_slippage_bps: int = 200


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
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    exits: ExitConfig = Field(default_factory=ExitConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    live_gate: LiveGateConfig = Field(default_factory=LiveGateConfig)

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


def load_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
