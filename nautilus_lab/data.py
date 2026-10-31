"""OHLCV data: GeckoTerminal pools -> clean 1-minute candles (USD), plus a synthetic generator.

Two correctness details that quietly ruin backtests when missed:

  * GeckoTerminal stamps a candle with its OPEN time, NautilusTrader expects the CLOSE time.
    Feeding open times would let the strategy trade on a candle before it finished (look-ahead).
    `to_nautilus_frame` shifts the index by one bar.
  * GeckoTerminal omits minutes with no trades. `fill_gaps` re-inserts them as flat zero-volume
    candles so a "5 minute window" always holds 5 minutes.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

GECKO = "https://api.geckoterminal.com/api/v2/networks/solana"
BAR_SECONDS = 60
COLUMNS = ["open", "high", "low", "close", "volume"]


def _get_json(client: httpx.Client, url: str, params: dict, *, retries: int = 4) -> dict:
    """GET with backoff on 429. The public tier is shared and tight; failing with a clear message
    beats a KeyError three layers down."""
    for attempt in range(retries + 1):
        r = client.get(url, params=params, headers={"Accept": "application/json;version=20230302"})
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        limited = r.status_code == 429 or (body.get("status") or {}).get("error_code") == 429
        if not limited:
            r.raise_for_status()
            return body
        if attempt == retries:
            raise RuntimeError("GeckoTerminal rate limit (429) persisted: wait a minute and retry, or use --csv")
        time.sleep(15.0 * (attempt + 1))
    raise AssertionError("unreachable")


def fetch_ohlcv(pool: str, days: float = 3.0, *, client: httpx.Client | None = None, pause_s: float = 2.2) -> pd.DataFrame:
    """1-minute USD candles for a pool, oldest first, indexed by candle OPEN time (UTC).

    GeckoTerminal's public tier allows ~30 calls/min and 1000 candles per call (~16.7 h), so
    `days=3` is about 5 calls. Stops early when the pool has no older history.
    """
    own = client is None
    client = client or httpx.Client(timeout=20.0)
    rows: dict[int, list[float]] = {}
    before = int(time.time())
    oldest_wanted = before - int(days * 86_400)
    try:
        while before > oldest_wanted:
            body = _get_json(
                client,
                f"{GECKO}/pools/{pool}/ohlcv/minute",
                {"aggregate": 1, "limit": 1000, "currency": "usd", "before_timestamp": before},
            )
            page = body["data"]["attributes"]["ohlcv_list"]
            if not page:
                break
            for ts, o, h, l, c, v in page:
                rows[int(ts)] = [float(o), float(h), float(l), float(c), float(v)]
            nxt = min(int(p[0]) for p in page)
            if nxt >= before:
                break
            before = nxt
            time.sleep(pause_s)
    finally:
        if own:
            client.close()
    if not rows:
        raise ValueError(f"no candles returned for pool {pool}")
    df = pd.DataFrame.from_dict(rows, orient="index", columns=COLUMNS).sort_index()
    df.index = pd.to_datetime(df.index, unit="s", utc=True)
    return clean(df)


def clean(df: pd.DataFrame, step: int = BAR_SECONDS) -> pd.DataFrame:
    """Drop impossible rows, enforce OHLC consistency, fill the no-trade minutes."""
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    df = df.copy()
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    return fill_gaps(df, step)


def fill_gaps(df: pd.DataFrame, step: int = BAR_SECONDS) -> pd.DataFrame:
    if df.empty:
        return df
    grid = pd.date_range(df.index[0], df.index[-1], freq=f"{step}s")
    out = df.reindex(grid)
    out["close"] = out["close"].ffill()
    for col in ("open", "high", "low"):
        out[col] = out[col].fillna(out["close"])
    out["volume"] = out["volume"].fillna(0.0)
    out.index.name = None
    return out


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index_label="timestamp")


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col="timestamp", parse_dates=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return clean(df[COLUMNS])


def to_nautilus_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Re-stamp candles with their CLOSE time (open + 1 bar), which is what Nautilus expects."""
    out = df.copy()
    out.index = out.index + pd.Timedelta(f"{BAR_SECONDS}s")
    # Our volume is USD; Nautilus reads it as a token count and sizes available liquidity from
    # it. Left in dollars it understates liquidity by 1/price (millions of times for a memecoin).
    out["volume"] = out["volume"] / out["close"]
    return out


def synthetic_ohlcv(seed: int = 7, minutes: int = 3 * 24 * 60, start_price: float = 1.5e-5) -> pd.DataFrame:
    """Random-walk candles with injected breakout episodes. FOR PLUMBING TESTS AND DEMOS ONLY:
    any profit it shows is a property of the generator, never evidence about real markets."""
    rng = np.random.default_rng(seed)
    drift = np.zeros(minutes)
    vol_mult = np.ones(minutes)
    i = 120
    while i < minutes - 80:
        i += int(rng.integers(90, 400))
        if i >= minutes - 80:
            break
        run = int(rng.integers(6, 16))
        kind = rng.choice(["fade", "continue", "dump"], p=[0.45, 0.3, 0.25])
        drift[i : i + run] = rng.uniform(0.008, 0.02)
        vol_mult[i : i + run + 5] = rng.uniform(2.5, 6.0)
        tail = int(rng.integers(20, 90))
        drift[i + run : i + run + tail] = {"fade": -0.004, "continue": 0.004, "dump": -0.015}[kind]
    ret = drift + rng.normal(0, 0.0035, minutes)
    close = start_price * np.exp(np.cumsum(ret))
    open_ = np.r_[start_price, close[:-1]]
    wick = np.abs(rng.normal(0, 0.0015, (2, minutes)))
    high = np.maximum(open_, close) * (1 + wick[0])
    low = np.minimum(open_, close) * (1 - wick[1])
    volume = rng.lognormal(7.5, 0.5, minutes) * vol_mult
    idx = pd.date_range("2025-01-01", periods=minutes, freq=f"{BAR_SECONDS}s", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
