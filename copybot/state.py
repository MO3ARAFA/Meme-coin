"""Crash-safe persistence: open positions, re-entry cooldowns, daily PnL, circuit breaker.

A copy bot that forgets its open positions on restart is a bag-holder. State is written
atomically (tmp file + rename) after every change, and every fill is appended to a CSV
journal that the `report` command and the LIVE-readiness gate read back.
"""

from __future__ import annotations

import csv
import json
import os
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Position(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    mint: str
    symbol: str = ""
    whale: str
    signal_signature: str
    opened_at: float
    token_program: str = ""
    decimals: int = 0

    initial_token_raw: int
    token_raw: int  # remaining
    initial_cost_lamports: int  # SOL spent including entry fees
    cost_basis_lamports: int  # cost attributed to the remaining tokens
    realized_lamports: int = 0  # SOL received from sells, net of exit fees
    fees_lamports: int = 0
    rent_lamports: int = 0  # ATA rent locked while the position is open (refunded on close)

    entry_price: float  # lamports per raw token, our fill
    whale_price: float  # lamports per raw token, the whale's fill
    # Cheap marking between Jupiter quotes: est. ratio = DexScreener priceNative * calibration.
    # Re-calibrated against every real sell quote, so it absorbs this pool's impact and fees.
    mark_calibration: float = 0.0

    peak_ratio: float = 1.0
    last_ratio: float = 1.0
    last_quote_ts: float = 0.0
    scaled_out: bool = False
    stop_ratio: float = 0.78
    no_route_since: float | None = None

    whale_peak_balance_raw: int = 0
    whale_balance_raw: int = 0

    status: PositionStatus = PositionStatus.OPEN
    closed_at: float | None = None
    close_reason: str = ""
    entry_tx: str = ""
    exit_txs: list[str] = Field(default_factory=list)

    @property
    def whale_sold_frac(self) -> float:
        if self.whale_peak_balance_raw <= 0:
            return 0.0
        return max(0.0, 1.0 - self.whale_balance_raw / self.whale_peak_balance_raw)

    @property
    def age_minutes(self) -> float:
        return (time.time() - self.opened_at) / 60.0

    @property
    def net_pnl_lamports(self) -> int:
        """Realized PnL; meaningful once CLOSED (rent is refunded on close and nets out)."""
        return self.realized_lamports - self.initial_cost_lamports

    @property
    def net_return(self) -> float:
        return self.net_pnl_lamports / self.initial_cost_lamports if self.initial_cost_lamports else 0.0


class DailyLedger(BaseModel):
    day: str = ""
    start_equity_lamports: int = 0
    realized_pnl_lamports: int = 0


class BotState(BaseModel):
    positions: dict[str, Position] = Field(default_factory=dict)
    last_entry_by_mint: dict[str, float] = Field(default_factory=dict)
    daily: DailyLedger = Field(default_factory=DailyLedger)
    halted_until: float = 0.0
    shadow_balance_lamports: int | None = None
    last_signature_by_wallet: dict[str, str] = Field(default_factory=dict)
    seen_signatures: list[str] = Field(default_factory=list)

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if p.status is PositionStatus.OPEN]


def utc_day(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), tz=timezone.utc).strftime("%Y-%m-%d")


class StateStore:
    MAX_SEEN = 5000

    def __init__(self, path: Path) -> None:
        self.path = path
        self.state = self._load()
        self._seen = set(self.state.seen_signatures)

    def _load(self) -> BotState:
        if self.path.exists():
            return BotState.model_validate_json(self.path.read_text())
        return BotState()

    def save(self) -> None:
        self.state.seen_signatures = self.state.seen_signatures[-self.MAX_SEEN :]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(self.state.model_dump_json(indent=2))
        os.replace(tmp, self.path)

    def mark_seen(self, signature: str) -> bool:
        """Returns False if the signature was already processed (websocket + backfill overlap)."""
        if signature in self._seen:
            return False
        self._seen.add(signature)
        self.state.seen_signatures.append(signature)
        if len(self.state.seen_signatures) > self.MAX_SEEN * 2:
            self.state.seen_signatures = self.state.seen_signatures[-self.MAX_SEEN :]
            self._seen = set(self.state.seen_signatures)
        return True


TRADE_FIELDS = [
    "timestamp_utc",
    "event",
    "position_id",
    "mint",
    "symbol",
    "whale",
    "reason",
    "sol_amount",
    "token_amount_ui",
    "price_lamports_per_raw",
    "whale_price_lamports_per_raw",
    "fees_sol",
    "position_net_pnl_sol",
    "position_net_return_pct",
    "hold_minutes",
    "tx",
]


class TradeJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        if not path.exists():
            with path.open("w", newline="") as f:
                csv.DictWriter(f, fieldnames=TRADE_FIELDS).writeheader()

    def append(self, row: dict) -> None:
        row = {k: row.get(k, "") for k in TRADE_FIELDS}
        row["timestamp_utc"] = row["timestamp_utc"] or datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.path.open("a", newline="") as f:
            csv.DictWriter(f, fieldnames=TRADE_FIELDS).writerow(row)

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(newline="") as f:
            return list(csv.DictReader(f))


def save_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    os.replace(tmp, path)
