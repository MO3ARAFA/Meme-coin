"""The only module that ever touches a private key — and only in LIVE mode.

Hard rules enforced here:
  * SHADOW_PAPER never calls `load_signer`; the key is not read, parsed or held in memory.
  * `solders.keypair.Keypair.__repr__/__str__` print the SECRET KEY. A stray `log.info(kp)`
    or an exception traceback would leak it. `Signer` wraps the keypair and only ever
    exposes the public key and a `sign` operation.
  * Keypair files must not be readable by other users (chmod 600).
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from dotenv import dotenv_values
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction


class Signer:
    __slots__ = ("_kp", "_pubkey")

    def __init__(self, kp: Keypair) -> None:
        self._kp = kp
        self._pubkey = kp.pubkey()

    @property
    def pubkey(self) -> Pubkey:
        return self._pubkey

    def sign_versioned(self, tx: VersionedTransaction) -> VersionedTransaction:
        return VersionedTransaction(tx.message, [self._kp])

    @property
    def keypair_for_legacy_tx(self) -> Keypair:
        return self._kp

    def __repr__(self) -> str:
        return f"Signer(pubkey={self._pubkey})"

    __str__ = __repr__

    def __reduce__(self):  # never pickle a key
        raise TypeError("Signer cannot be serialized")


def _secret_setting(name: str) -> str:
    # pydantic-settings does not export .env into os.environ, so read the two secret
    # settings here, at the single place they are needed.
    value = os.environ.get(name) or dotenv_values(".env").get(name) or ""
    return value.strip()


def load_signer() -> Signer:
    """Load from KEYPAIR_PATH (Solana CLI JSON array, chmod 600) or PRIVATE_KEY (base58)."""
    path = _secret_setting("KEYPAIR_PATH")
    if path:
        p = Path(path).expanduser()
        mode = p.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise PermissionError(f"{p} is readable by group/others — run: chmod 600 {p}")
        secret = json.loads(p.read_text())
        return Signer(Keypair.from_bytes(bytes(secret)))
    b58 = _secret_setting("PRIVATE_KEY")
    if not b58:
        raise RuntimeError("LIVE mode needs KEYPAIR_PATH or PRIVATE_KEY (use a dedicated burner wallet)")
    try:
        return Signer(Keypair.from_base58_string(b58))
    except Exception:
        raise RuntimeError("PRIVATE_KEY is not a valid base58 64-byte secret key") from None
