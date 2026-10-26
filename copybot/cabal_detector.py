"""Coordinated-wallet detection: same-tx bundles, co-slot cabals, and holder concentration.

Three on-chain signals of coordination, cheapest first:

1. **Bundled buy** — the whale's own buy transaction also delivered the token to OTHER
   wallets (one signer buying for a ring of wallets). Free: we already have the tx.
2. **Co-slot cabal** — across many of a wallet's buys, the same external wallets keep buying
   the same tokens in the same slot (or the slot before). One coincidence is noise; the same
   partners across different tokens is a ring. RPC-heavy, so the scorer runs it on finalists.
3. **Holder concentration** — `getTokenLargestAccounts`, with pools, LP vaults, bonding curves
   (program-owned or off-curve PDA owners) and burn addresses removed first. Flags a token
   whose real top holders own too much, or whose top wallets hold suspiciously identical
   amounts (a bundler splitting supply evenly).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from solders.pubkey import Pubkey

from .constants import LAMPORTS_PER_SOL, SYSTEM_PROGRAM
from .solana_rpc import SolanaRpc
from .tx_parser import Side, SwapEvent, extract_swaps

log = logging.getLogger(__name__)

BURN_OWNERS = frozenset({"1nc1nerator11111111111111111111111111111111", "11111111111111111111111111111111"})


def bundled_recipients(tx: dict, wallet: str, mint: str) -> set[str]:
    """Other owners whose balance of `mint` grew inside `wallet`'s buy transaction."""
    meta = tx.get("meta") or {}
    pre: dict[str, int] = defaultdict(int)
    post: dict[str, int] = defaultdict(int)
    for rows, acc in ((meta.get("preTokenBalances") or [], pre), (meta.get("postTokenBalances") or [], post)):
        for row in rows:
            owner = row.get("owner")
            if row.get("mint") == mint and owner and owner != wallet:
                acc[owner] += int(row["uiTokenAmount"]["amount"])
    return {o for o, amt in post.items() if amt > pre.get(o, 0)}


# ---------------------------------------------------------------------------------------
# Co-slot cabal scan
# ---------------------------------------------------------------------------------------
@dataclass
class CabalReport:
    sampled_buys: int = 0
    co_slot_buys: int = 0  # buys that shared a slot with a RECURRING partner
    recurring_partners: list[str] = field(default_factory=list)

    @property
    def co_slot_ratio(self) -> float:
        return self.co_slot_buys / self.sampled_buys if self.sampled_buys else 0.0


async def co_slot_scan(rpc: SolanaRpc, fetch_tx, wallet: str, buys: list[SwapEvent], max_buys: int,
                       min_partner_sol: float = 0.05) -> CabalReport:
    """For each sampled buy, find other wallets that bought the same token in the same slot or
    the slot before (via the mint's signature list), then keep partners seen on >= 2 tokens.
    `fetch_tx` is the scorer's cached transaction fetcher."""
    sample = sorted(buys, key=lambda e: e.slot, reverse=True)[:max_buys]
    partners_by_buy: list[set[str]] = []
    partner_mints: dict[str, set[str]] = defaultdict(set)
    sem = asyncio.Semaphore(4)

    async def scan(ev: SwapEvent) -> set[str]:
        async with sem:
            try:
                sigs = await rpc.get_signatures_for_address(ev.mint, limit=15, before=ev.signature)
            except Exception:
                return set()
        near = [r["signature"] for r in sigs if r.get("err") is None and r.get("slot", 0) >= ev.slot - 1]
        found: set[str] = set()
        for tx in await asyncio.gather(*(fetch_tx(s) for s in near)):
            if not tx:
                continue
            keys = tx["transaction"]["message"]["accountKeys"]
            payer = keys[0]["pubkey"] if isinstance(keys[0], dict) else keys[0]
            if payer == wallet:
                continue
            for other in extract_swaps(tx, payer):
                if other.mint == ev.mint and other.side is Side.BUY and other.quote_amount_raw >= min_partner_sol * LAMPORTS_PER_SOL:
                    found.add(payer)
        return found

    results = await asyncio.gather(*(scan(ev) for ev in sample))
    for ev, found in zip(sample, results):
        partners_by_buy.append(found)
        for p in found:
            partner_mints[p].add(ev.mint)
    recurring = {p for p, mints in partner_mints.items() if len(mints) >= 2}
    report = CabalReport(sampled_buys=len(sample), recurring_partners=sorted(recurring))
    report.co_slot_buys = sum(1 for found in partners_by_buy if found & recurring)
    return report


# ---------------------------------------------------------------------------------------
# Holder distribution
# ---------------------------------------------------------------------------------------
@dataclass
class HolderReport:
    top5_pct: float = 0.0
    max_single_pct: float = 0.0
    identical_count: int = 0
    excluded_pct: float = 0.0  # supply held by pools / curves / burn (not counted)
    holders: list[tuple[str, float]] = field(default_factory=list)  # (owner, pct) real holders

    def problems(self, max_top5: float, max_single: float, min_identical: int) -> list[str]:
        out = []
        if self.top5_pct > max_top5:
            out.append(f"top-5 real holders own {self.top5_pct:.0%} of supply (> {max_top5:.0%})")
        if self.max_single_pct > max_single:
            out.append(f"one wallet owns {self.max_single_pct:.0%} of supply (> {max_single:.0%})")
        if self.identical_count >= min_identical:
            out.append(f"{self.identical_count} top wallets hold near-identical amounts (bundler split)")
        return out


def _largest_identical_group(amounts: list[int], tolerance: float) -> int:
    ordered = sorted(amounts)
    best, start = 0, 0
    for end in range(len(ordered)):
        while ordered[end] > 0 and (ordered[end] - ordered[start]) / ordered[end] > tolerance:
            start += 1
        best = max(best, end - start + 1)
    return best


async def holder_distribution(rpc: SolanaRpc, mint: str, supply_raw: int, *, exclude: set[str] = frozenset(),
                              tolerance: float = 0.002, min_pct: float = 0.005) -> HolderReport:
    largest = await rpc.get_token_largest_accounts(mint)
    if not largest or supply_raw <= 0:
        return HolderReport()
    token_accounts = [row["address"] for row in largest]
    parsed = await rpc.get_multiple_accounts_parsed(token_accounts)
    owner_of: dict[str, str] = {}
    for addr, acct in zip(token_accounts, parsed):
        try:
            owner_of[addr] = acct["data"]["parsed"]["info"]["owner"]
        except (TypeError, KeyError):
            pass
    owners = sorted(set(owner_of.values()))
    owner_accts = await rpc.get_multiple_accounts(owners) if owners else []
    real_wallet: dict[str, bool] = {}
    for owner, acct in zip(owners, owner_accts):
        if owner in BURN_OWNERS or owner in exclude:
            real_wallet[owner] = False
            continue
        try:
            on_curve = Pubkey.from_string(owner).is_on_curve()
        except ValueError:
            on_curve = False
        system_owned = acct is None or acct.get("owner") == SYSTEM_PROGRAM
        # PDAs (pools, curves, vault authorities) are off-curve or owned by a program.
        real_wallet[owner] = on_curve and system_owned
    report = HolderReport()
    by_owner: dict[str, int] = defaultdict(int)
    for row in largest:
        owner = owner_of.get(row["address"])
        if owner is None:
            continue
        amount = int(row["amount"])
        if real_wallet.get(owner):
            by_owner[owner] += amount
        else:
            report.excluded_pct += amount / supply_raw
    ranked = sorted(by_owner.items(), key=lambda kv: kv[1], reverse=True)
    report.holders = [(o, a / supply_raw) for o, a in ranked]
    report.top5_pct = sum(p for _, p in report.holders[:5])
    report.max_single_pct = report.holders[0][1] if report.holders else 0.0
    sizeable = [a for _, a in ranked if a / supply_raw >= min_pct]
    report.identical_count = _largest_identical_group(sizeable, tolerance) if len(sizeable) >= 2 else 0
    return report
