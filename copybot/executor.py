"""Module E — trade execution: SHADOW_PAPER (default, no key) and LIVE (signs with solders).

Both executors implement the same interface, so every other module is identical in both
modes. That is what makes shadow results a meaningful predictor of live results.

Shadow fills are deliberately pessimistic: they use a REAL Jupiter quote fetched at decision
time, then subtract a latency haircut (our tx would land a few hundred ms after the quote),
plus base + priority fees and token-account rent, exactly as a live trade would pay.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction, VersionedTransaction

from .config import Settings
from .constants import BASE_FEE_LAMPORTS, TOKEN_ACCOUNT_RENT_LAMPORTS, WSOL_MINT
from .jupiter import JupiterClient, Quote
from .solana_rpc import SolanaRpc
from .tx_parser import extract_swaps, parse_balances
from .tx_verify import ata_address, verify_swap_transaction
from .wallet_vault import Signer

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Fill:
    ok: bool
    token_raw: int = 0  # tokens received (buy) or sold (sell)
    lamports: int = 0  # SOL spent incl. fees (buy) or received net of fees (sell)
    fees_lamports: int = 0
    rent_lamports: int = 0  # buy: rent locked in a new token account; final sell: rent refunded
    signature: str = ""
    error: str = ""


class Executor(Protocol):
    async def free_balance_lamports(self) -> int: ...

    async def buy(self, mint: str, lamports: int, quote: Quote, max_priority_lamports: int) -> Fill: ...

    async def sell(
        self, mint: str, token_raw: int, *, slippage_bps: int, max_priority_lamports: int, final: bool, token_program: str
    ) -> Fill: ...


class ShadowExecutor:
    """Paper trading against live quotes. Needs no private key."""

    def __init__(self, settings: Settings, jupiter: JupiterClient, balance_ref: "BalanceRef") -> None:
        self.s = settings
        self.jupiter = jupiter
        self.balance = balance_ref

    def _haircut(self, amount: int) -> int:
        return int(amount * (1 - self.s.shadow_latency_haircut_bps / 10_000))

    def _fee(self, max_priority: int) -> int:
        return BASE_FEE_LAMPORTS + min(self.s.shadow_assumed_priority_lamports, max_priority)

    async def free_balance_lamports(self) -> int:
        return self.balance.lamports

    async def buy(self, mint: str, lamports: int, quote: Quote, max_priority_lamports: int) -> Fill:
        if quote.in_amount != lamports:
            quote = await self.jupiter.quote(WSOL_MINT, mint, lamports, self.s.risk.entry_slippage_bps)
        tokens = self._haircut(quote.out_amount)
        if tokens < quote.other_amount_threshold:
            # Our simulated landing price breaches the slippage limit: a live tx would revert.
            fee = BASE_FEE_LAMPORTS
            self.balance.lamports -= fee
            return Fill(False, fees_lamports=fee, error="simulated slippage breach (tx would fail)")
        fee = self._fee(max_priority_lamports)
        rent = TOKEN_ACCOUNT_RENT_LAMPORTS
        self.balance.lamports -= lamports + fee + rent
        return Fill(True, token_raw=tokens, lamports=lamports + fee, fees_lamports=fee, rent_lamports=rent,
                    signature=f"shadow-{int(time.time() * 1000)}")

    async def sell(self, mint, token_raw, *, slippage_bps, max_priority_lamports, final, token_program) -> Fill:
        q = await self.jupiter.quote(mint, WSOL_MINT, token_raw, slippage_bps)
        out = self._haircut(q.out_amount)
        fee = self._fee(max_priority_lamports)
        rent = TOKEN_ACCOUNT_RENT_LAMPORTS if final else 0
        proceeds = max(out - fee, 0)
        self.balance.lamports += proceeds + rent
        return Fill(True, token_raw=token_raw, lamports=proceeds, fees_lamports=fee, rent_lamports=rent,
                    signature=f"shadow-{int(time.time() * 1000)}")


@dataclass
class BalanceRef:
    lamports: int


class LiveExecutor:
    """Signs Jupiter-built transactions after zero-trust verification and a simulation check."""

    CONFIRM_TIMEOUT_S = 60

    def __init__(self, settings: Settings, rpc: SolanaRpc, jupiter: JupiterClient, signer: Signer) -> None:
        self.s = settings
        self.rpc = rpc
        self.jupiter = jupiter
        self.signer = signer
        self.owner = str(signer.pubkey)

    async def free_balance_lamports(self) -> int:
        return await self.rpc.get_balance(self.owner)

    async def _swap(self, quote: Quote, max_priority: int, max_input_lamports: int) -> tuple[str, dict | None, str]:
        tx_b64, last_valid = await self.jupiter.build_swap_transaction(
            quote, self.owner, max_priority_lamports=max_priority, priority_mode=self.s.risk.priority_mode
        )
        unsigned = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
        verify_swap_transaction(
            unsigned, self.signer.pubkey, max_input_lamports=max_input_lamports, max_priority_lamports=max_priority
        )
        signed = self.signer.sign_versioned(unsigned)
        raw_b64 = base64.b64encode(bytes(signed)).decode()
        if self.s.live_simulate_before_send:
            await self._simulation_guard(raw_b64, max_input_lamports + max_priority)
        sig = await self.rpc.send_raw_transaction(raw_b64)
        err = await self._confirm(sig, raw_b64, last_valid)
        if err:
            return sig, None, err
        tx = await self.rpc.get_transaction(sig, retries=10)
        return sig, tx, "" if tx else "confirmed but transaction not retrievable"

    async def _simulation_guard(self, raw_b64: str, max_spend_lamports: int) -> None:
        """Refuse to send if simulation shows the wallet losing more SOL than this trade may cost.
        Allowance: input + landing fee + base fee + two token-account rents (output ATA, wSOL ATA)."""
        before = await self.rpc.get_balance(self.owner)
        after, err = await self.rpc.simulate_lamports_after(raw_b64, self.owner)
        if err:
            raise RuntimeError(f"simulation failed: {err}")
        if after is None:
            raise RuntimeError("simulation returned no account state")
        allowance = max_spend_lamports + BASE_FEE_LAMPORTS + 2 * TOKEN_ACCOUNT_RENT_LAMPORTS + 50_000
        if before - after > allowance:
            raise RuntimeError(f"simulation: wallet would lose {before - after} lamports (> {allowance} allowed)")

    async def _confirm(self, sig: str, raw_b64: str, last_valid_block_height: int) -> str:
        """Rebroadcast every 2s until confirmed, failed, or the blockhash expires."""
        deadline = time.time() + self.CONFIRM_TIMEOUT_S
        while time.time() < deadline:
            await asyncio.sleep(2.0)
            status = (await self.rpc.get_signature_statuses([sig]))[0]
            if status:
                if status.get("err"):
                    return f"transaction failed on-chain: {status['err']}"
                if status.get("confirmationStatus") in ("confirmed", "finalized"):
                    return ""
            if last_valid_block_height and await self.rpc.get_block_height() > last_valid_block_height:
                return "blockhash expired before confirmation"
            try:
                await self.rpc.send_raw_transaction(raw_b64, skip_preflight=True)
            except Exception as exc:
                log.debug("rebroadcast failed: %s", exc)
        return "confirmation timeout"

    async def buy(self, mint: str, lamports: int, quote: Quote, max_priority_lamports: int) -> Fill:
        try:
            sig, tx, err = await self._swap(quote, max_priority_lamports, lamports)
        except Exception as exc:
            return Fill(False, error=f"buy failed before landing: {exc}")
        if err:
            return Fill(False, signature=sig, error=err)
        return self._fill_from_tx(tx, sig, mint, buying=True)

    async def sell(self, mint, token_raw, *, slippage_bps, max_priority_lamports, final, token_program) -> Fill:
        quote = await self.jupiter.quote(mint, WSOL_MINT, token_raw, slippage_bps)  # NoRouteError propagates
        try:
            sig, tx, err = await self._swap(quote, max_priority_lamports, 0)
        except Exception as exc:
            return Fill(False, error=f"sell failed before landing: {exc}")
        if err:
            return Fill(False, signature=sig, error=err)
        fill = self._fill_from_tx(tx, sig, mint, buying=False)
        if fill.ok and final:
            rent = await self.close_token_account(mint, token_program)
            fill = Fill(True, fill.token_raw, fill.lamports, fill.fees_lamports, rent, fill.signature)
        return fill

    def _fill_from_tx(self, tx: dict, sig: str, mint: str, *, buying: bool) -> Fill:
        events = [e for e in extract_swaps(tx, self.owner) if e.mint == mint]
        if not events:
            return Fill(False, signature=sig, error="landed, but no swap of this token found in tx")
        ev = events[0]
        parsed = parse_balances(tx, self.owner)
        # Network fee (base + priority) plus any Jito tip: the full cost of landing.
        fee = int(tx["meta"]["fee"]) + (parsed.tips_lamports if parsed else 0)
        if buying:
            return Fill(True, ev.token_amount_raw, ev.quote_amount_raw + fee, fee, TOKEN_ACCOUNT_RENT_LAMPORTS, sig)
        return Fill(True, ev.token_amount_raw, ev.quote_amount_raw - fee, fee, 0, sig)

    async def close_token_account(self, mint: str, token_program: str) -> int:
        """Reclaim ~0.002 SOL rent after a full exit. Burns dust first is NOT done: if a dust
        balance remains, closing fails harmlessly and we keep the account."""
        program = Pubkey.from_string(token_program or "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        ata = ata_address(self.signer.pubkey, Pubkey.from_string(mint), program)
        try:
            accounts = await self.rpc.get_token_accounts(self.owner, mint)
            target = next((a for a in accounts if a["pubkey"] == str(ata)), None)
            if not target or int(target["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) != 0:
                return 0
            rent = int(target["account"]["lamports"])
            ix = Instruction(
                program,
                bytes([9]),  # CloseAccount
                [AccountMeta(ata, False, True), AccountMeta(self.signer.pubkey, False, True),
                 AccountMeta(self.signer.pubkey, True, False)],
            )
            blockhash, last_valid = await self.rpc.get_latest_blockhash()
            bh = Hash.from_string(blockhash)
            msg = Message.new_with_blockhash([ix], self.signer.pubkey, bh)
            tx = Transaction([self.signer.keypair_for_legacy_tx], msg, bh)
            raw_b64 = base64.b64encode(bytes(tx)).decode()
            sig = await self.rpc.send_raw_transaction(raw_b64)
            err = await self._confirm(sig, raw_b64, last_valid)
            return 0 if err else rent
        except Exception as exc:
            log.warning("closing token account for %s failed: %s", mint, exc)
            return 0
