"""fetch-many against a fake GeckoTerminal: pacing, backoff, resume, empty/failed pools, pre-flight,
manifest. No network; no Nautilus needed."""

from datetime import datetime, timezone

import httpx
import pytest

pytest.importorskip("pandas")

from nautilus_lab import cli, manifest  # noqa: E402
from nautilus_lab.data import load_csv  # noqa: E402
from nautilus_lab.fetcher import (  # noqa: E402
    EXIT_FAILED, EXIT_INTERRUPTED, EXIT_OK, EXIT_RATE_LIMITED, Paths, SchemaError, SlidingWindowLimiter,
    run_fetch_many, validate_ohlcv_rows,
)

NOW = 1_800_000_000


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


class FakeGecko:
    def __init__(self):
        self.pools: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []
        self.limit_after: int | None = None  # every call after this many returns 429
        self.limit_n: int = 0  # ...or: exactly this many 429s, then healthy
        self.interrupt_at: int | None = None

    def add(self, addr, age_s, kind="ok"):
        self.pools[addr] = {"created": NOW - age_s, "kind": kind}

    def handler(self, request: httpx.Request) -> httpx.Response:
        n = len(self.calls) + 1
        params = dict(request.url.params)
        path = request.url.path.removeprefix("/api/v2/networks/solana")
        self.calls.append((path, params))
        if self.interrupt_at == n:
            raise KeyboardInterrupt
        if (self.limit_after is not None and n > self.limit_after) or self.limit_n > 0:
            self.limit_n = max(0, self.limit_n - 1)
            return httpx.Response(429, json={"status": {"error_code": 429}})
        addr = path.split("/")[2]
        pool = self.pools.get(addr)
        if pool is None:
            return httpx.Response(404, json={})
        if pool["kind"] == "500":
            return httpx.Response(500, json={})
        if path.endswith("/ohlcv/minute"):
            if pool["kind"] == "empty":
                return httpx.Response(200, json={"data": {"attributes": {"ohlcv_list": []}}})
            agg, before, limit = int(params["aggregate"]) * 60, int(params["before_timestamp"]), int(params["limit"])
            first = ((pool["created"] + agg - 1) // agg) * agg
            ts = [t for t in range(first, min(before, NOW), agg)][-limit:][::-1]
            width = 5 if pool["kind"] == "badschema" else 6
            rows = [[t, 1e-5, 1.1e-5, 0.9e-5, 1e-5 * (1 + (t // 60 % 7) / 100), 100.0][: width] for t in ts]
            return httpx.Response(200, json={"data": {"attributes": {"ohlcv_list": rows}}})
        attrs = {"name": f"{addr[:4]} / SOL", "pool_created_at": iso(pool["created"]), "base_token_price_usd": "0.00001"}
        return httpx.Response(200, json={"data": {"attributes": attrs}})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def ohlcv_calls(self, addr):
        return [p for path, p in self.calls if addr in path and path.endswith("/ohlcv/minute")]


class Clock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def now(self):
        return self.t

    def sleep(self, d):
        self.slept.append(d)
        self.t += d


def run(fake, paths, pools=(), clock=None, **kw):
    clock = clock or Clock()
    kw.setdefault("max_per_min", 1000)
    return run_fetch_many(list(pools), paths=paths, client=fake.client(), clock=clock.now, sleep=clock.sleep,
                          now_fn=lambda: NOW, **kw), clock


# ---- pacing -------------------------------------------------------------------------------------
def test_sliding_window_never_exceeds_the_rate():
    c = Clock()
    lim = SlidingWindowLimiter(3, 60.0, c.now, c.sleep)
    for _ in range(3):
        lim.wait()
    assert c.slept == []  # three calls fit in the window
    lim.wait()
    assert c.slept == [60.0]  # the 4th waits for the first to leave the window
    for _ in range(2):
        lim.wait()
    assert sum(c.slept) == pytest.approx(60.0) and len(lim.calls) <= 3


# ---- happy path ---------------------------------------------------------------------------------
def test_resolution_split_files_manifest_and_report(tmp_path):
    fake, paths = FakeGecko(), Paths(tmp_path / "data")
    fake.add("A" * 44, age_s=3 * 86400)  # older than the 24 h fine window -> 1m + 15m
    fake.add("B" * 44, age_s=10 * 3600)  # younger than it -> 1m only
    rep, _ = run(fake, paths, ["A" * 44, "B" * 44])
    assert rep.exit_code == EXIT_OK and (rep.done, rep.empty, rep.failed, rep.pending) == (2, 0, [], 0)
    a1, a15, b1 = paths.final("A" * 44, "1m"), paths.final("A" * 44, "15m"), paths.final("B" * 44, "1m")
    import pandas as pd

    assert len(load_csv(a1)) == 24 * 60 and len(pd.read_csv(a15)) == 2 * 24 * 4  # 15m file is not a 1m file
    assert len(load_csv(b1)) == 10 * 60 and not paths.final("B" * 44, "15m").exists()
    assert manifest.verify(a1, paths.manifest) == "ok"
    assert manifest.load(paths.manifest)["lab/" + a1.name]["sha256"] == manifest.sha256_file(a1)
    assert rep.calls < 25 and "2 pools: 2 done, 0 empty, 0 failed" in rep.render()
    assert rep.fine_pool_hours == pytest.approx(24 + 10)
    assert paths.log.exists() and "done" in paths.log.read_text()
    assert not list((paths.lab / "raw").glob("*.csv"))  # raw pages cleaned up


# ---- 429 handling and resume --------------------------------------------------------------------
def test_transient_429_backs_off_and_is_not_a_pool_failure(tmp_path):
    fake, paths = FakeGecko(), Paths(tmp_path / "data")
    fake.add("A" * 44, age_s=10 * 3600)
    fake.limit_n = 2
    rep, clock = run(fake, paths, ["A" * 44])
    assert rep.exit_code == EXIT_OK and rep.done == 1 and not rep.failed
    assert clock.slept[:2] == [5.0, 10.0]


def test_persistent_429_saves_state_exits_2_and_resume_does_not_refetch(tmp_path):
    fake, paths = FakeGecko(), Paths(tmp_path / "data")
    addr = "A" * 44
    fake.add(addr, age_s=3 * 86400)
    fake.limit_after = 4  # pre-flight (2) + metadata (1) + first 1m page (1), then 429 forever
    rep, clock = run(fake, paths, [addr])
    assert rep.exit_code == EXIT_RATE_LIMITED and rep.pending == 1 and not rep.failed
    assert [d for d in clock.slept if d >= 5][:4] == [5.0, 10.0, 20.0, 60.0]
    cursor = load_state_cursor(paths, addr)
    assert cursor is not None and "stopped" in rep.render()

    fake.limit_after = None
    seen = len(fake.calls)
    rep2, _ = run(fake, paths)  # same command, no pools: continues the saved run
    assert rep2.exit_code == EXIT_OK and rep2.done == 1
    first_resumed = fake.calls[seen]
    assert first_resumed[1]["before_timestamp"] == str(cursor)  # continued from the cursor, not from the top
    df = load_csv(paths.final(addr, "1m"))
    assert len(df) == 24 * 60 and df.index.is_unique and df.index.is_monotonic_increasing


def load_state_cursor(paths, addr):
    import json

    return json.loads(paths.state.read_text())["pools"][addr]["segments"]["1m"]["cursor"]


def test_ctrl_c_saves_state_and_resumes(tmp_path):
    fake, paths = FakeGecko(), Paths(tmp_path / "data")
    fake.add("A" * 44, age_s=3 * 86400)
    fake.interrupt_at = 5
    rep, _ = run(fake, paths, ["A" * 44])
    assert rep.exit_code == EXIT_INTERRUPTED and paths.state.exists()
    fake.interrupt_at = None
    rep2, _ = run(fake, paths)
    assert rep2.exit_code == EXIT_OK and rep2.done == 1


# ---- bad pools never loop or stop the batch --------------------------------------------------------
def test_empty_pool_is_marked_after_one_attempt_and_failed_pool_does_not_stop_the_batch(tmp_path):
    fake, paths = FakeGecko(), Paths(tmp_path / "data")
    good, empty, broken = "G" * 44, "E" * 44, "F" * 44
    fake.add(good, age_s=10 * 3600)
    fake.add(empty, age_s=10 * 3600, kind="empty")
    fake.add(broken, age_s=10 * 3600, kind="500")
    rep, clock = run(fake, paths, [good, empty, broken])
    assert (rep.done, rep.empty, len(rep.failed)) == (1, 1, 1) and rep.exit_code == EXIT_FAILED
    assert len(fake.ohlcv_calls(empty)) <= 2  # one in pre-flight, one in the batch: never a loop
    assert rep.failed[0][0] == broken and "HTTP 500" in rep.failed[0][1]
    assert "3 pools: 1 done, 1 empty, 1 failed" in rep.render() and "fetch.log" in rep.render()
    assert 2.0 in clock.slept and 5.0 in clock.slept  # transient retries on the 500s
    # re-running does not touch finished or empty pools again
    before = len(fake.calls)
    run(fake, paths)
    assert len(fake.calls) == before


# ---- pre-flight -----------------------------------------------------------------------------------
def test_preflight_catches_a_changed_schema_before_the_batch(tmp_path):
    fake, paths = FakeGecko(), Paths(tmp_path / "data")
    for i in range(5):
        fake.add(f"{i}" * 44, age_s=10 * 3600, kind="badschema")
    rep, _ = run(fake, paths, [f"{i}" * 44 for i in range(5)])
    assert rep.exit_code == EXIT_FAILED and "PRE-FLIGHT FAILED" in rep.render()
    assert len(fake.calls) <= 3 and not list(paths.lab.glob("*.csv"))


def test_preflight_only_stops_after_validating(tmp_path):
    fake, paths = FakeGecko(), Paths(tmp_path / "data")
    fake.add("A" * 44, age_s=10 * 3600)
    rep, _ = run(fake, paths, ["A" * 44], preflight_only=True)
    assert rep.exit_code == EXIT_OK and rep.pending == 1 and len(fake.calls) == 2 and rep.calls == 2
    assert any("round trip ok" in n for n in rep.notes)


def test_validate_rows_rejects_wrong_shapes():
    validate_ohlcv_rows([[1, 1.0, 1.0, 1.0, 1.0, 5.0]])
    for bad in ([[1, 1, 1, 1, 1]], [[1, "x", 1, 1, 1, 1]], [[1, 1, 1, 1, 1, -3]], "nope",
                [[1, 0, 0, 0, 0, 1]] * 5):
        with pytest.raises(SchemaError):
            validate_ohlcv_rows(bad)


# ---- manifest -------------------------------------------------------------------------------------
def test_backtest_refuses_a_csv_that_no_longer_matches_its_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake, paths = FakeGecko(), Paths(tmp_path / "data")
    fake.add("A" * 44, age_s=10 * 3600)
    run(fake, paths, ["A" * 44])
    f = paths.final("A" * 44, "1m")
    cli._check_manifest([f], ignore=False)  # untouched: fine
    f.write_text(f.read_text() + "\n")
    assert manifest.verify(f, paths.manifest) == "mismatch"
    with pytest.raises(SystemExit, match="differs from data/manifest.json"):
        cli._check_manifest([f], ignore=False)
    cli._check_manifest([f], ignore=True)  # explicit override
