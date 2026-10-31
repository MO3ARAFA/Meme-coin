"""data/manifest.json: SHA-256 of every candle CSV the lab fetched, so a backtest can say exactly
which data it ran on and refuse silently edited or truncated files."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

MANIFEST_PATH = Path("data/manifest.json")


def atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True))
    os.replace(tmp, path)  # a crash mid-write can never leave a half-written state file


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _key(path: Path, manifest_path: Path) -> str:
    p, root = Path(path).resolve(), manifest_path.resolve().parent
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()


def load(manifest_path: Path = MANIFEST_PATH) -> dict:
    return json.loads(manifest_path.read_text()) if manifest_path.exists() else {}


def register(path: Path, *, rows: int, first_ts: int, last_ts: int, step_s: int,
             manifest_path: Path = MANIFEST_PATH) -> str:
    m = load(manifest_path)
    digest = sha256_file(path)
    m[_key(path, manifest_path)] = {"sha256": digest, "rows": rows, "first_ts": first_ts, "last_ts": last_ts,
                                    "step_s": step_s, "registered_at": int(time.time())}
    atomic_write_json(manifest_path, m)
    return digest


def verify(path: Path, manifest_path: Path = MANIFEST_PATH) -> str:
    """'ok' | 'mismatch' | 'unmanifested'."""
    entry = load(manifest_path).get(_key(path, manifest_path))
    if entry is None:
        return "unmanifested"
    return "ok" if entry["sha256"] == sha256_file(path) else "mismatch"


def fingerprint(paths: list[Path], manifest_path: Path = MANIFEST_PATH) -> str:
    """Short id of exactly this set of files (hash of their hashes), printed in every report."""
    h = hashlib.sha256()
    for p in sorted(Path(x).resolve().as_posix() for x in paths):
        h.update(sha256_file(Path(p)).encode())
    return h.hexdigest()[:12]
