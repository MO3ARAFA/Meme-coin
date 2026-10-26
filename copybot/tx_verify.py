"""Zero-trust verification of a swap transaction built by a remote API, BEFORE we sign it.

We sign a transaction that someone else's server assembled. If that server (or a DNS/TLS
MITM, or a malicious proxy) returned a drain transaction, signing it would empty the wallet.
So we decode the message and refuse to sign unless:

  * we are the fee payer and the ONLY required signer;
  * every top-level program is in a short allow-list (Jupiter, ComputeBudget, System,
    SPL Token / Token-2022, Associated Token Account, Memo);
  * System transfers only go to OUR wrapped-SOL account (bounded by the swap input) or to a
    Jito tip account (bounded by the tip cap);
  * SPL Token instructions are limited to SyncNative and CloseAccount-back-to-us
    (no Transfer / Approve / SetAuthority at top level);
  * the compute-budget priority fee does not exceed our fee cap.

Program IDs cannot come from address lookup tables, so the static key list is sufficient to
identify programs. Any instruction we cannot fully attribute fails closed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from .constants import (
    ATA_PROGRAM,
    COMPUTE_BUDGET_PROGRAM,
    JITO_TIP_ACCOUNTS,
    SWAP_TX_PROGRAM_ALLOWLIST,
    SYSTEM_PROGRAM,
    TOKEN_2022_PROGRAM,
    TOKEN_PROGRAM,
    WSOL_MINT,
)


class UnsafeTransactionError(RuntimeError):
    pass


def ata_address(owner: Pubkey, mint: Pubkey, token_program: Pubkey) -> Pubkey:
    return Pubkey.find_program_address(
        [bytes(owner), bytes(token_program), bytes(mint)], Pubkey.from_string(ATA_PROGRAM)
    )[0]


@dataclass(frozen=True)
class VerifiedSwap:
    priority_fee_lamports: int
    tip_lamports: int
    wrap_lamports: int


def verify_swap_transaction(
    tx: VersionedTransaction,
    user: Pubkey,
    *,
    max_input_lamports: int,
    max_priority_lamports: int,
) -> VerifiedSwap:
    msg = tx.message
    keys = list(msg.account_keys)
    n_static = len(keys)
    if not keys or keys[0] != user:
        raise UnsafeTransactionError("fee payer is not our wallet")
    if msg.header.num_required_signatures != 1:
        raise UnsafeTransactionError(f"{msg.header.num_required_signatures} signers required, expected only us")

    wsol_ata = ata_address(user, Pubkey.from_string(WSOL_MINT), Pubkey.from_string(TOKEN_PROGRAM))
    allowed_programs = {Pubkey.from_string(p) for p in SWAP_TX_PROGRAM_ALLOWLIST}
    tips = {Pubkey.from_string(t) for t in JITO_TIP_ACCOUNTS}

    cu_limit = 200_000 * max(1, len(msg.instructions))  # runtime default if not set
    cu_price_micro = 0
    tip_total = 0
    wrap_total = 0

    def key_at(i: int) -> Pubkey:
        if i >= n_static:
            raise UnsafeTransactionError("instruction references a lookup-table account we cannot attribute")
        return keys[i]

    for ix in msg.instructions:
        program = key_at(ix.program_id_index)
        if program not in allowed_programs:
            raise UnsafeTransactionError(f"unexpected program {program}")
        data = bytes(ix.data)
        accts = list(ix.accounts)
        pstr = str(program)

        if pstr == COMPUTE_BUDGET_PROGRAM:
            if data[:1] == b"\x02" and len(data) >= 5:
                cu_limit = struct.unpack_from("<I", data, 1)[0]
            elif data[:1] == b"\x03" and len(data) >= 9:
                cu_price_micro = struct.unpack_from("<Q", data, 1)[0]
        elif pstr == SYSTEM_PROGRAM:
            tag = struct.unpack_from("<I", data, 0)[0] if len(data) >= 4 else -1
            if tag != 2 or len(data) < 12 or len(accts) < 2:
                raise UnsafeTransactionError(f"unexpected System instruction (tag {tag})")
            src, dst = key_at(accts[0]), key_at(accts[1])
            lamports = struct.unpack_from("<Q", data, 4)[0]
            if src != user:
                raise UnsafeTransactionError("System transfer from a foreign account")
            if dst == wsol_ata:
                wrap_total += lamports
            elif dst in tips:
                tip_total += lamports
            else:
                raise UnsafeTransactionError(f"SOL transfer to unknown account {dst}")
        elif pstr in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            tag = data[0] if data else -1
            if tag == 17:  # SyncNative
                continue
            if tag == 9 and len(accts) >= 3:  # CloseAccount(account, destination, owner)
                if key_at(accts[1]) != user:
                    raise UnsafeTransactionError("CloseAccount refunds rent to someone else")
                continue
            raise UnsafeTransactionError(f"unexpected SPL Token instruction tag {tag}")
        elif pstr == ATA_PROGRAM:
            if data not in (b"", b"\x01"):  # Create / CreateIdempotent only
                raise UnsafeTransactionError("unexpected ATA instruction")
        # Jupiter + Memo: allowed as-is. Jupiter's route moves only accounts we own via CPI;
        # the simulation balance check in the executor bounds what it can spend.

    priority = (cu_price_micro * cu_limit + 999_999) // 1_000_000
    if priority + tip_total > max_priority_lamports * 1.05 + 1_000:
        raise UnsafeTransactionError(
            f"landing fee {priority + tip_total} lamports exceeds cap {max_priority_lamports}"
        )
    if wrap_total > max_input_lamports * 1.01 + 1_000:
        raise UnsafeTransactionError(f"wraps {wrap_total} lamports, more than the quoted input {max_input_lamports}")
    return VerifiedSwap(priority_fee_lamports=priority, tip_lamports=tip_total, wrap_lamports=wrap_total)
