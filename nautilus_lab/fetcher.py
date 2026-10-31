"""fetch-many: pull candles for dozens of pools politely, resumably, and verifiably.

Design (each point exists because the alternative wastes a 20-minute run):

* Resolution split. Per pool, the first `first_hours` of its usable history are fetched at 1 minute
  (where momentum lives) and the rest of the window at `coarse_minutes`. "First" means the start of the
  usable window: the pool's creation if it is younger than `days`, else `now - days`. The backtest reads
  only the 1-minute file (the detector needs minute samples); the coarse file is fetched, hashed and kept
  for later multi-resolution work.
* Pre-flight. One pool x one hour is fetched and validated (schema, prices, save/load round trip) before
  the batch starts. A changed endpoint fails in seconds, not at call 400.
* Pacing, not reacting. A sliding 60 s window keeps us under `max_per_min`; a 429 anyway triggers
  5/10/20/60 s backoff and is never counted as "pool failed". Persistent 429 saves state and exits 2.
* Resume. data/.fetch_state.json is rewritten atomically after every page. Re-running the same command
  continues from each pool's cursor. An empty pool is marked `empty` after ONE attempt, never retried in
  a loop; errors mark the pool `failed` and the batch moves on.
* Provenance. Finished files are registered in data/manifest.json (SHA-256); data/fetch.log keeps the
  whole story; the final report says exactly what happened.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd

from . import manifest
from .data import BAR_SECONDS, GECKO, clean, load_csv

log = logging.getLogger("nautilus_lab.fetch")

EXIT_OK, EXIT_FAILED, EXIT_RATE_LIMITED, EXIT_INTERRUPTED = 0, 1, 2, 130
BACKOFF_S = (5.0, 10.0, 20.0, 60.0)
TRANSIENT_RETRY_S = (2.0, 5.0)
PAGE_LIMIT = 1000
MAX_PAGES_PER_SEGMENT = 120
STATE_VERSION = 1


class RateLimited(Exception):
    """429 persisted through the whole backoff ladder."""


class FetchError(Exception):
    """This pool cannot be fetched (404, repeated 5xx/network error); the batch continues."""


class SchemaError(Exception):
    """The endpoint no longer looks like what the lab was written against."""


class SlidingWindowLimiter:
    """Never more than `max_calls` in any `window_s` seconds. Clock and sleep are injectable."""

    def __init__(
        self,
        max_calls: int = 28,
        window_s: float = 60.0,
        clock=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        self.max_calls, self.window_s, self.clock, self.sleep = (
            max_calls,
            window_s,
            clock,
            sleep,
        )
        self.calls: deque[float] = deque()

    def wait(self) -> None:
        while True:
            now = self.clock()
            while self.calls and now - self.calls[0] >= self.window_s:
                self.calls.popleft()
            if len(self.calls) < self.max_calls:
                self.calls.append(now)
                return
            self.sleep(max(0.0, self.calls[0] + self.window_s - now))


class Gecko:
    def __init__(
        self, client: httpx.Client, limiter: SlidingWindowLimiter, sleep=time.sleep
    ) -> None:
        self.client, self.limiter, self.sleep = client, limiter, sleep
        self.calls = 0  # every HTTP attempt, including retries: each one spends quota

    def get(self, path: str, params: dict | None = None) -> dict:
        backoffs, transient = list(BACKOFF_S), list(TRANSIENT_RETRY_S)
        while True:
            self.limiter.wait()
            self.calls += 1
            try:
                r = self.client.get(
                    f"{GECKO}{path}",
                    params=params,
                    headers={"Accept": "application/json;version=20230302"},
                )
            except httpx.TransportError as exc:
                if not transient:
                    raise FetchError(f"network error: {exc}") from exc
                self.sleep(transient.pop(0))
                continue
            body = {}
            if r.headers.get("content-type", "").startswith("application/json"):
                try:
                    body = r.json()
                except ValueError:
                    body = {}
            if (
                r.status_code == 429
                or (body.get("status") or {}).get("error_code") == 429
            ):
                if not backoffs:
                    raise RateLimited("429 persisted through 5/10/20/60 s backoff")
                wait = backoffs.pop(0)
                try:
                    wait = max(wait, float(r.headers.get("retry-after", 0)))
                except ValueError:
                    pass
                log.warning("429 on %s: backing off %.0fs", path, wait)
                self.sleep(wait)
                continue
            if r.status_code == 404:
                raise FetchError("404 not found")
            if r.status_code >= 500:
                if not transient:
                    raise FetchError(f"HTTP {r.status_code}")
                self.sleep(transient.pop(0))
                continue
            r.raise_for_status()
            return body


# ---- validation ------------------------------------------------------------------------------
def validate_ohlcv_rows(rows) -> None:
    """Raise SchemaError unless `rows` looks like GeckoTerminal's [ts, o, h, l, c, v] list."""
    if not isinstance(rows, list):
        raise SchemaError(f"ohlcv_list is {type(rows).__name__}, expected list")
    bad = 0
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 6:
            raise SchemaError(
                f"row has {len(row) if hasattr(row, '__len__') else '?'} fields, expected 6: {row!r}"
            )
        try:
            ts, o, h, low, c, v = (float(x) for x in row)
        except (TypeError, ValueError) as exc:
            raise SchemaError(f"non-numeric field in {row!r}") from exc
        if not all(math.isfinite(x) for x in (ts, o, h, low, c, v)) or ts <= 0 or v < 0:
            raise SchemaError(f"non-finite or negative field in {row!r}")
        if min(o, h, low, c) <= 0:
            bad += 1
    if rows and bad > 0.2 * len(rows):
        raise SchemaError(f"{bad}/{len(rows)} rows have non-positive prices")


def rows_to_frame(rows: list, step: int) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df.pop("ts").astype("int64"), unit="s", utc=True)
    return clean(df.sort_index(), step)


def parse_iso(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


# ---- state -----------------------------------------------------------------------------------
@dataclass
class Paths:
    root: Path = Path("data")

    @property
    def state(self) -> Path:
        return self.root / ".fetch_state.json"

    @property
    def log(self) -> Path:
        return self.root / "fetch.log"

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def lab(self) -> Path:
        return self.root / "lab"

    def raw(self, addr: str, tf: str) -> Path:
        return self.lab / "raw" / f"{addr}_{tf}.csv"

    def final(self, addr: str, tf: str) -> Path:
        # the 1-minute file keeps the name the rest of the lab already uses for cached pools
        return (
            self.lab / f"{addr}.csv"
            if tf == "1m"
            else self.lab / "coarse" / f"{addr}_{tf}.csv"
        )


def setup_logging(paths: Paths) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    if any(getattr(h, "_lab_fetch", False) for h in log.handlers):
        return
    fh = logging.FileHandler(paths.log)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    fh._lab_fetch = True  # type: ignore[attr-defined]
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(message)s"))
    ch._lab_fetch = True  # type: ignore[attr-defined]
    log.addHandler(fh)
    log.addHandler(ch)
    log.setLevel(logging.INFO)


def load_state(paths: Paths) -> dict:
    import json

    if paths.state.exists():
        st = json.loads(paths.state.read_text())
        if st.get("version") == STATE_VERSION:
            return st
        log.warning("ignoring fetch state with unknown version %s", st.get("version"))
    return {"version": STATE_VERSION, "preflight_ok": False, "pools": {}}


def save_state(paths: Paths, st: dict) -> None:
    manifest.atomic_write_json(paths.state, st)


def new_pool(addr: str, name: str = "") -> dict:
    return {
        "address": addr,
        "name": name,
        "status": "pending",
        "calls_made": 0,
        "timeframe": "1m",
        "last_fetched_ts": None,
        "error": "",
        "segments": None,
    }


# ---- pre-flight ------------------------------------------------------------------------------
def preflight(api: Gecko, candidates: list[str], paths: Paths, now: float) -> list[str]:
    """Fetch one hour of one pool and check everything the batch relies on. Returns notes."""
    notes: list[str] = []
    for addr in candidates[:3]:
        try:
            meta = api.get(f"/pools/{addr}")
            attrs = meta["data"]["attributes"]
        except KeyError as exc:
            raise SchemaError(
                f"/pools/{{addr}} response lacks data.attributes ({exc})"
            ) from exc
        except FetchError as exc:
            notes.append(f"{addr[:8]}: {exc}")
            continue
        page = api.get(
            f"/pools/{addr}/ohlcv/minute",
            {
                "aggregate": 1,
                "limit": 60,
                "currency": "usd",
                "before_timestamp": int(now),
            },
        )
        try:
            rows = page["data"]["attributes"]["ohlcv_list"]
        except (KeyError, TypeError) as exc:
            raise SchemaError(
                f"ohlcv response lacks data.attributes.ohlcv_list ({exc})"
            ) from exc
        validate_ohlcv_rows(rows)
        if not rows:
            notes.append(
                f"{addr[:8]}: no candles in the last hour, trying the next pool"
            )
            continue
        df = rows_to_frame(rows, BAR_SECONDS)
        tmp = paths.lab / "raw" / "_preflight.csv"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(tmp, index_label="timestamp")
        back = load_csv(tmp)
        tmp.unlink()
        if (
            len(back) != len(df)
            or not (
                (back["close"] - df["close"]).abs() <= 1e-12 + 1e-9 * df["close"]
            ).all()
        ):
            raise SchemaError("candles changed in the save/load round trip")
        try:
            quoted = float(attrs.get("base_token_price_usd") or 0)
        except (TypeError, ValueError):
            quoted = 0.0
        last = float(df["close"].iloc[-1])
        if quoted > 0 and not (0.5 <= last / quoted <= 2.0):
            notes.append(
                f"{addr[:8]}: last candle close {last:.6g} vs quoted price {quoted:.6g}: check units"
            )
        notes.append(
            f"{addr[:8]}: schema ok, {len(df)} candles, close {last:.6g}, round trip ok"
        )
        return notes
    raise SchemaError("pre-flight found no pool with candles: " + "; ".join(notes))


# ---- one pool --------------------------------------------------------------------------------
def plan_pool(
    p: dict,
    api: Gecko,
    *,
    days: float,
    first_hours: float,
    coarse_minutes: int,
    now: float,
) -> None:
    attrs = api.get(f"/pools/{p['address']}")["data"]["attributes"]
    p["name"] = attrs.get("name", p["name"])
    created = (
        parse_iso(attrs["pool_created_at"]) if attrs.get("pool_created_at") else 0.0
    )
    end = int(now)
    start = int(max(created, end - days * 86400))
    fine_end = int(min(start + first_hours * 3600, end))
    p["segments"] = {
        "1m": {
            "agg": 1,
            "step_s": 60,
            "start": start,
            "end": fine_end,
            "cursor": None,
            "done": False,
            "rows": 0,
        }
    }
    if fine_end < end:
        tf = f"{coarse_minutes}m"
        p["segments"][tf] = {
            "agg": coarse_minutes,
            "step_s": 60 * coarse_minutes,
            "start": fine_end,
            "end": end,
            "cursor": None,
            "done": False,
            "rows": 0,
        }


def fetch_segment(
    p: dict, tf: str, api: Gecko, paths: Paths, save: Callable[[], None]
) -> bool:
    """Walk one segment backwards in time. Returns False if the very first page was empty."""
    seg = p["segments"][tf]
    raw = paths.raw(p["address"], tf)
    raw.parent.mkdir(parents=True, exist_ok=True)
    if not raw.exists():
        raw.write_text("ts,open,high,low,close,volume\n")
    first_page = seg["cursor"] is None
    for _ in range(MAX_PAGES_PER_SEGMENT):
        before = seg["cursor"] if seg["cursor"] is not None else seg["end"]
        body = api.get(
            f"/pools/{p['address']}/ohlcv/minute",
            {
                "aggregate": seg["agg"],
                "limit": PAGE_LIMIT,
                "currency": "usd",
                "before_timestamp": before,
            },
        )
        rows = body["data"]["attributes"]["ohlcv_list"]
        validate_ohlcv_rows(rows)
        if not rows:
            if first_page and seg["rows"] == 0:
                return False
            seg["done"] = True
            break
        first_page = False
        keep = [r for r in rows if seg["start"] <= int(r[0]) < seg["end"]]
        with open(raw, "a") as f:
            f.writelines(
                f"{int(r[0])},{r[1]},{r[2]},{r[3]},{r[4]},{r[5]}\n" for r in keep
            )
        seg["rows"] += len(keep)
        oldest = min(int(r[0]) for r in rows)
        if oldest >= before:  # no progress: the API is repeating itself
            seg["done"] = True
            break
        seg["cursor"] = oldest
        p["last_fetched_ts"] = oldest
        save()
        if oldest <= seg["start"] or len(rows) < PAGE_LIMIT:
            seg["done"] = True
            break
    else:
        log.warning(
            "%s %s: stopped after %d pages", p["address"][:8], tf, MAX_PAGES_PER_SEGMENT
        )
        seg["done"] = True
    return True


def finalize_segment(p: dict, tf: str, paths: Paths) -> None:
    seg = p["segments"][tf]
    df = pd.read_csv(paths.raw(p["address"], tf))
    df = df.drop_duplicates("ts").sort_values("ts")
    if df.empty:
        return
    df.index = pd.to_datetime(df.pop("ts").astype("int64"), unit="s", utc=True)
    out = clean(df, seg["step_s"])
    dest = paths.final(p["address"], tf)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dest, index_label="timestamp")
    manifest.register(
        dest,
        rows=len(out),
        first_ts=int(out.index[0].timestamp()),
        last_ts=int(out.index[-1].timestamp()),
        step_s=seg["step_s"],
        manifest_path=paths.manifest,
    )
    paths.raw(p["address"], tf).unlink(missing_ok=True)


def fetch_pool(
    p: dict,
    api: Gecko,
    paths: Paths,
    save: Callable[[], None],
    *,
    days: float,
    first_hours: float,
    coarse_minutes: int,
    now: float,
) -> None:
    calls0 = api.calls
    try:
        if p["segments"] is None:
            plan_pool(
                p,
                api,
                days=days,
                first_hours=first_hours,
                coarse_minutes=coarse_minutes,
                now=now,
            )
            save()
        # fine segment first, always: the state file is key-sorted, so dict order is not time order
        for tf, seg in sorted(p["segments"].items(), key=lambda kv: kv[1]["start"]):
            if seg["done"]:
                continue
            if not fetch_segment(p, tf, api, paths, save):
                if tf == "1m":  # nothing in the minute window: dead or too new. One attempt, then empty.
                    p["status"] = "empty"
                    log.info("%s (%s): no candles in its 1m window -> empty", p["address"][:8], p["name"])
                    return
                seg["done"] = True  # the pool simply stopped trading before the coarse segment
            finalize_segment(p, tf, paths)
            save()
        p["status"] = "done"
        log.info(
            "%s (%s): done, %s",
            p["address"][:8],
            p["name"],
            ", ".join(f"{tf}={s['rows']} rows" for tf, s in p["segments"].items()),
        )
    except FetchError as exc:
        p["status"], p["error"] = "failed", str(exc)
        log.error("%s (%s): FAILED: %s", p["address"][:8], p["name"], exc)
    finally:
        p["calls_made"] += api.calls - calls0
        save()


# ---- batch -----------------------------------------------------------------------------------
@dataclass
class Report:
    total: int = 0
    done: int = 0
    empty: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    pending: int = 0
    calls: int = 0
    exit_code: int = EXIT_OK
    stopped_by: str = ""
    notes: list[str] = field(default_factory=list)
    fine_pool_hours: float = 0.0

    def render(self) -> str:
        lines = [
            f"{self.total} pools: {self.done} done, {self.empty} empty, {len(self.failed)} failed, "
            f"{self.pending} not yet fetched   ({self.calls} API calls)"
        ]
        for addr, err in self.failed:
            lines.append(f"  FAILED {addr[:10]}...: {err}  (see data/fetch.log)")
        if self.stopped_by:
            lines.append(
                f"  stopped: {self.stopped_by}. Run the same command again to continue; finished pools are kept."
            )
        if self.done:
            lines.append(
                f"  usable for a minute-resolution backtest: {self.fine_pool_hours / 24:.1f} token-days "
                f"across {self.done} pools"
            )
        lines += [f"  note: {n}" for n in self.notes]
        return "\n".join(lines)


def run_fetch_many(
    pools: list[str],
    *,
    paths: Paths | None = None,
    days: float = 14.0,
    first_hours: float = 24.0,
    coarse_minutes: int = 15,
    max_per_min: int = 28,
    preflight_only: bool = False,
    retry_failed: bool = False,
    client: httpx.Client | None = None,
    clock=time.monotonic,
    sleep=time.sleep,
    now_fn: Callable[[], float] = time.time,
) -> Report:
    paths = paths or Paths()
    setup_logging(paths)
    st = load_state(paths)
    for addr in pools:
        st["pools"].setdefault(addr, new_pool(addr))
    if retry_failed:
        for p in st["pools"].values():
            if p["status"] == "failed":
                p["status"], p["error"] = "pending", ""
    own = client is None
    client = client or httpx.Client(timeout=30.0)
    api = Gecko(client, SlidingWindowLimiter(max_per_min, 60.0, clock, sleep), sleep)
    report = Report()
    save = lambda: save_state(paths, st)  # noqa: E731
    try:
        todo = [
            a for a, p in st["pools"].items() if p["status"] in {"pending", "partial"}
        ]
        try:
            if not st["preflight_ok"] and todo:
                for line in preflight(api, todo, paths, now_fn()):
                    log.info("pre-flight %s", line)
                    report.notes.append(f"pre-flight {line}")
                st["preflight_ok"] = True
                save()
            if preflight_only:
                report.stopped_by = "pre-flight only"
            else:
                for addr in todo:
                    p = st["pools"][addr]
                    p["status"] = "partial"
                    fetch_pool(
                        p,
                        api,
                        paths,
                        save,
                        days=days,
                        first_hours=first_hours,
                        coarse_minutes=coarse_minutes,
                        now=now_fn() if p["segments"] is None else 0,
                    )
                    if (
                        p["status"] == "partial"
                    ):  # fetch_pool returns early only on exceptions we handle
                        p["status"] = "pending"
        except RateLimited as exc:
            report.exit_code, report.stopped_by = (
                EXIT_RATE_LIMITED,
                f"rate limited ({exc})",
            )
            log.error("rate limited: %s", exc)
        except KeyboardInterrupt:
            report.exit_code, report.stopped_by = EXIT_INTERRUPTED, "interrupted"
            log.warning("interrupted: state saved")
        except SchemaError as exc:
            report.exit_code, report.stopped_by = (
                EXIT_FAILED,
                f"PRE-FLIGHT FAILED: {exc}",
            )
            log.error("schema check failed: %s", exc)
    finally:
        for p in st["pools"].values():
            if p["status"] == "partial":
                p["status"] = "pending"  # in-flight pool: resumes from its cursor
        save()
        if own:
            client.close()
    report.total = len(st["pools"])
    for addr, p in st["pools"].items():
        if p["status"] == "done":
            report.done += 1
            seg = p["segments"]["1m"]
            report.fine_pool_hours += (seg["end"] - seg["start"]) / 3600
        elif p["status"] == "empty":
            report.empty += 1
        elif p["status"] == "failed":
            report.failed.append((addr, p["error"]))
        else:
            report.pending += 1
    report.calls = api.calls  # this run, pre-flight included (per-pool totals live in the state file)
    if report.exit_code == EXIT_OK and report.failed:
        report.exit_code = EXIT_FAILED
    if report.exit_code == EXIT_OK and report.pending and not preflight_only:
        report.exit_code = EXIT_FAILED
    log.info("%s", report.render())
    return report
