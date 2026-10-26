"""Zero-trust verification of API-built swap transactions."""

import struct

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from copybot.constants import (
    COMPUTE_BUDGET_PROGRAM,
    JITO_TIP_ACCOUNTS,
    JUPITER_V6_PROGRAM,
    SYSTEM_PROGRAM,
    TOKEN_PROGRAM,
    WSOL_MINT,
)
from copybot.tx_verify import UnsafeTransactionError, ata_address, verify_swap_transaction

USER = Keypair()
U = USER.pubkey()
WSOL_ATA = ata_address(U, Pubkey.from_string(WSOL_MINT), Pubkey.from_string(TOKEN_PROGRAM))
TIP = Pubkey.from_string(next(iter(JITO_TIP_ACCOUNTS)))
P = Pubkey.from_string


def transfer(dst, lamports, src=U):
    return Instruction(P(SYSTEM_PROGRAM), struct.pack("<IQ", 2, lamports), [AccountMeta(src, True, True), AccountMeta(dst, False, True)])


def cu_limit(n):
    return Instruction(P(COMPUTE_BUDGET_PROGRAM), bytes([2]) + struct.pack("<I", n), [])


def cu_price(micro):
    return Instruction(P(COMPUTE_BUDGET_PROGRAM), bytes([3]) + struct.pack("<Q", micro), [])


def jupiter_route():
    return Instruction(P(JUPITER_V6_PROGRAM), b"\xe5\x17\xcb\x97" + bytes(20), [AccountMeta(U, True, False)])


def tx(*ixs, payer=U, signers=(USER,)):
    msg = MessageV0.try_compile(payer, list(ixs), [], Hash.default())
    return VersionedTransaction(msg, list(signers))


def check(t, max_in=10**8, max_prio=500_000):
    return verify_swap_transaction(t, U, max_input_lamports=max_in, max_priority_lamports=max_prio)


def test_normal_jupiter_shaped_swap_passes():
    v = check(tx(cu_limit(200_000), cu_price(1_000_000), transfer(WSOL_ATA, 10**8),
                 Instruction(P(TOKEN_PROGRAM), bytes([17]), [AccountMeta(WSOL_ATA, False, True)]),
                 jupiter_route(), transfer(TIP, 100_000)))
    assert v.wrap_lamports == 10**8 and v.tip_lamports == 100_000 and v.priority_fee_lamports == 200_000


def test_sol_transfer_to_stranger_is_blocked():
    with pytest.raises(UnsafeTransactionError, match="unknown account"):
        check(tx(jupiter_route(), transfer(Keypair().pubkey(), 10**9)))


def test_spl_token_transfer_or_approve_is_blocked():
    for tag in (3, 4, 6, 12):  # Transfer, Approve, SetAuthority, TransferChecked
        ix = Instruction(P(TOKEN_PROGRAM), bytes([tag]) + bytes(8),
                         [AccountMeta(WSOL_ATA, False, True), AccountMeta(Keypair().pubkey(), False, True), AccountMeta(U, True, False)])
        with pytest.raises(UnsafeTransactionError, match="SPL Token"):
            check(tx(jupiter_route(), ix))


def test_unknown_program_is_blocked():
    evil = Instruction(Keypair().pubkey(), b"\x00", [AccountMeta(U, True, True)])
    with pytest.raises(UnsafeTransactionError, match="unexpected program"):
        check(tx(jupiter_route(), evil))


def test_fee_above_cap_and_oversized_wrap_are_blocked():
    with pytest.raises(UnsafeTransactionError, match="landing fee"):
        check(tx(cu_limit(1_400_000), cu_price(10_000_000), jupiter_route()))  # 14M lamports priority
    with pytest.raises(UnsafeTransactionError, match="wraps"):
        check(tx(transfer(WSOL_ATA, 5 * 10**8), jupiter_route()), max_in=10**8)


def test_foreign_fee_payer_or_extra_signer_is_blocked():
    other = Keypair()
    with pytest.raises(UnsafeTransactionError, match="fee payer"):
        check(tx(jupiter_route(), payer=other.pubkey(), signers=(other, USER)))
    co_signed = Instruction(P(JUPITER_V6_PROGRAM), b"\x00", [AccountMeta(U, True, False), AccountMeta(other.pubkey(), True, False)])
    with pytest.raises(UnsafeTransactionError, match="signers"):
        check(tx(co_signed, signers=(USER, other)))
