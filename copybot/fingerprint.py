"""Execution fingerprints and timing entropy, from transactions the scorer already fetched.

Why: sybil rings stopped moving SOL between their wallets, so transfer links miss them. But
one operator running many wallets from one script leaves the same execution habits on every
wallet: the same compute-unit limit and priority price, the same top-level program sequence
(router, ATA creation, tip), the same tipping behaviour. And scripts trade on timers.

Caveat that shapes how this is used: every user of a given trading frontend shares that
frontend's defaults, so fingerprint similarity ALONE would merge thousands of independent
humans. The scorer only merges two wallets when the fingerprint matches AND they repeatedly
bought the same tokens within seconds of each other (see wallet_scorer.fingerprint_edges).
"""

from __future__ import annotations

import math
import statistics
import struct
from collections import Counter
from dataclasses import dataclass, field

from .constants import ATA_PROGRAM, COMPUTE_BUDGET_PROGRAM, JITO_TIP_ACCOUNTS, SYSTEM_PROGRAM, TOKEN_2022_PROGRAM, TOKEN_PROGRAM

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58)}
_LABELS = {
    COMPUTE_BUDGET_PROGRAM: "CB",
    ATA_PROGRAM: "ATA",
    SYSTEM_PROGRAM: "SYS",
    TOKEN_PROGRAM: "TOK",
    TOKEN_2022_PROGRAM: "TOK",
}


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58_INDEX[ch]
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + raw


@dataclass
class TxFingerprint:
    cu_limit: int | None = None
    cu_price: int | None = None  # micro-lamports per CU
    sequence: str = ""
    tipped: bool = False


def tx_fingerprint(tx: dict) -> TxFingerprint:
    fp = TxFingerprint()
    labels: list[str] = []
    for ix in tx["transaction"]["message"].get("instructions") or []:
        pid = ix.get("programId", "")
        if pid == COMPUTE_BUDGET_PROGRAM and isinstance(ix.get("data"), str):
            try:
                data = b58decode(ix["data"])
            except (KeyError, ValueError):
                data = b""
            if data[:1] == b"\x02" and len(data) >= 5:
                fp.cu_limit = struct.unpack_from("<I", data, 1)[0]
            elif data[:1] == b"\x03" and len(data) >= 9:
                fp.cu_price = struct.unpack_from("<Q", data, 1)[0]
        parsed = ix.get("parsed")
        if pid == SYSTEM_PROGRAM and isinstance(parsed, dict):
            if (parsed.get("info") or {}).get("destination") in JITO_TIP_ACCOUNTS:
                fp.tipped = True
                labels.append("TIP")
                continue
        label = _LABELS.get(pid, pid[:6])  # unknown programs (routers, AMMs) keep their identity
        if not labels or labels[-1] != label:
            labels.append(label)
    fp.sequence = ">".join(labels)
    return fp


def _bucket(v: int | None, step: int) -> str:
    return "none" if v is None else str(int(round(v / step)) * step)


@dataclass
class WalletFingerprint:
    features: Counter = field(default_factory=Counter)
    samples: int = 0

    def add(self, fp: TxFingerprint) -> None:
        self.samples += 1
        self.features[f"cul:{_bucket(fp.cu_limit, 10_000)}"] += 1
        self.features[f"cup:{fp.cu_price if fp.cu_price is not None else 'none'}"] += 1  # exact: scripts reuse one value
        self.features[f"seq:{fp.sequence}"] += 1
        self.features[f"tip:{int(fp.tipped)}"] += 1

    def top(self, n: int = 12) -> dict[str, float]:
        if not self.samples:
            return {}
        return {k: round(v / self.samples, 3) for k, v in self.features.most_common(n)}


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[k] * b[k] for k in a.keys() & b.keys())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def coefficient_of_variation(values: list[float]) -> float | None:
    """sigma / mu. Humans trade in bursts (CV well above 1); timer-driven scripts sit near 0."""
    if len(values) < 2:
        return None
    mean = statistics.fmean(values)
    if mean <= 0:
        return None
    return statistics.pstdev(values) / mean


def interval_cv(times: list[int]) -> tuple[float | None, int]:
    ordered = sorted(times)
    gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b > a]
    return coefficient_of_variation(gaps), len(gaps)


def co_buy_tokens(a: dict[str, list[int]], b: dict[str, list[int]], window_s: float) -> int:
    """Number of tokens both wallets bought within `window_s` of each other."""
    n = 0
    for mint in a.keys() & b.keys():
        if any(abs(x - y) <= window_s for x in a[mint] for y in b[mint]):
            n += 1
    return n
