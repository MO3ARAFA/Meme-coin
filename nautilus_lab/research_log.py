"""Two ledgers that keep the lab honest about HOW MANY TIMES it has looked at the data.

trials.json   every distinct configuration ever evaluated on development data. The count feeds the
              Deflated Sharpe: the more settings you try, the higher the bar luck sets.
holdout.json  a frozen set of pools chosen by a hash of their address (not by results), opened at most
              once. The only test that cannot be tuned against, because it was never looked at.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .manifest import atomic_write_json

TRIALS_PATH = Path("data/trials.json")
HOLDOUT_PATH = Path("data/holdout.json")

# Configurations tried by hand before this ledger existed (delay 0/1, anti-chase, looser thresholds,
# feature screen). An honest estimate, deliberately not zero.
PRIOR_UNTRACKED_TRIALS = 5
HOLDOUT_RULE = "sha256(pool address)[:8] as int, mod 10 < 3  (about 30% of pools)"


def config_id(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:12]


def record_trial(params: dict, path: Path = TRIALS_PATH) -> int:
    """Register this configuration (once) and return the total number of trials so far."""
    ledger = json.loads(path.read_text()) if path.exists() else {"prior_untracked": PRIOR_UNTRACKED_TRIALS, "configs": {}}
    cid = config_id(params)
    if cid not in ledger["configs"]:
        ledger["configs"][cid] = {"params": params, "first_seen": int(time.time())}
        atomic_write_json(path, ledger)
    return ledger["prior_untracked"] + len(ledger["configs"])


def trial_count(path: Path = TRIALS_PATH) -> int:
    if not path.exists():
        return PRIOR_UNTRACKED_TRIALS
    ledger = json.loads(path.read_text())
    return ledger["prior_untracked"] + len(ledger["configs"])


def holdout_state(path: Path = HOLDOUT_PATH, *, contaminated: list[str] | None = None) -> dict:
    """Load the ledger, creating (freezing) it on first use. `contaminated`: address prefixes of pools
    already backtested before the freeze; they can never be holdout, whatever their hash says."""
    if path.exists():
        return json.loads(path.read_text())
    st = {"rule": HOLDOUT_RULE, "frozen_at": int(time.time()), "contaminated": sorted(contaminated or []),
          "opened_at": None, "opened_fingerprint": None}
    atomic_write_json(path, st)
    return st


def is_holdout(address: str, path: Path = HOLDOUT_PATH) -> bool:
    st = holdout_state(path)
    if any(address.startswith(c) for c in st["contaminated"]):
        return False
    return int(hashlib.sha256(address.encode()).hexdigest()[:8], 16) % 10 < 3


def open_holdout(fingerprint: str, path: Path = HOLDOUT_PATH) -> None:
    """Mark the holdout as spent. Raises if it already was: a second look is just another trial."""
    st = holdout_state(path)
    if st["opened_at"] is not None:
        raise PermissionError(
            f"holdout already opened at {time.strftime('%Y-%m-%d %H:%M', time.gmtime(st['opened_at']))} "
            f"(data {st['opened_fingerprint']}): it cannot be used for a second decision")
    st["opened_at"], st["opened_fingerprint"] = int(time.time()), fingerprint
    atomic_write_json(path, st)
