"""Explainable on-chain evidence ledger.

Every consequential decision — COPY, ABORT, EXIT, EJECT, QUARANTINE — is appended to
`data/evidence.jsonl` with the verifiable facts behind it (slot, signature, wallet, mint,
imitation cost, holder concentration, reason), so any decision can be audited on-chain later.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class EvidenceLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, decision: str, **facts: Any) -> None:
        row = {"ts": int(time.time()), "decision": decision}
        row.update({k: v for k, v in facts.items() if v is not None})
        with self.path.open("a") as f:
            f.write(json.dumps(row, default=str, separators=(",", ":")) + "\n")
