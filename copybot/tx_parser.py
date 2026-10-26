"""Venue-agnostic swap extraction from a parsed Solana transaction.

Naive copy bots decode Raydium/Pump.fun/Jupiter instructions one by one and break every time
a venue ships a new program (PumpSwap, Meteora DAMM v2, Photon/Axiom/BullX routers...).
We instead read what the chain *settled*: the wallet's token and SOL balance deltas in
`meta.pre/postTokenBalances` and `meta.pre/postBalances`. That works for every DEX, router
and aggregator, present and future.

Units: all token amounts stay in RAW base units (integers). A price is "lamports per raw
token unit" — comparing two prices of the same mint therefore never needs decimals, which
removes the classic decimal-mismatch bug class entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .constants import JITO_TIP_ACCOUNTS, NON_MEME_MINTS, STABLE_MINTS, WSOL_MINT


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class SwapEvent:
    signature: str
    slot: int
    block_time: int | None
    wallet: str
    side: Side
    mint: str
    token_amount_raw: int  # absolute amount of `mint` bought or sold
    decimals: int
    quote_mint: str  # WSOL_MINT for SOL-paid trades, or a stablecoin mint
    quote_amount_raw: int  # lamports (SOL) or stable base units paid / received
    token_balance_before_raw: int  # wallet's holdings of `mint` before the tx
    token_balance_after_raw: int  # ... and after (lets us measure "% of position sold")
    fee_lamports: int
    token_program: str = ""

    @property
    def price_quote_per_raw(self) -> float:
        """Quote units per raw token unit (lamports/raw for SOL-quoted trades)."""
        return self.quote_amount_raw / self.token_amount_raw if self.token_amount_raw else 0.0

    @property
    def is_sol_quoted(self) -> bool:
        return self.quote_mint == WSOL_MINT

    @property
    def sold_fraction(self) -> float:
        """For a sell: fraction of the wallet's pre-trade holding that was sold."""
        if self.token_balance_before_raw <= 0:
            return 1.0
        return min(1.0, self.token_amount_raw / self.token_balance_before_raw)


@dataclass
class _TokenAcct:
    index: int
    mint: str
    owner: str
    program: str
    decimals: int
    pre_raw: int = 0
    post_raw: int = 0
    present_pre: bool = False
    present_post: bool = False


@dataclass
class ParsedBalances:
    """Intermediate result, exposed for tests and for the wallet scorer."""

    token_deltas: dict[str, int] = field(default_factory=dict)  # mint -> raw delta (non-quote mints)
    token_pre: dict[str, int] = field(default_factory=dict)
    token_post: dict[str, int] = field(default_factory=dict)
    decimals: dict[str, int] = field(default_factory=dict)
    programs: dict[str, str] = field(default_factory=dict)
    sol_delta_lamports: int = 0  # SOL-equivalent change from trading (fees, tips, rent excluded)
    stable_deltas: dict[str, int] = field(default_factory=dict)
    fee_lamports: int = 0
    tips_lamports: int = 0


def _account_keys(tx: dict) -> list[str]:
    keys = tx["transaction"]["message"]["accountKeys"]
    out = [k["pubkey"] if isinstance(k, dict) else k for k in keys]
    # With `json` (not jsonParsed) encoding, v0 lookup-table addresses live in meta.loadedAddresses.
    if keys and not isinstance(keys[0], dict):
        loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
        out += loaded.get("writable", []) + loaded.get("readonly", [])
    return out


def parse_balances(tx: dict, wallet: str) -> ParsedBalances | None:
    meta = tx.get("meta")
    if not meta or meta.get("err") is not None:
        return None  # failed transactions move nothing but fees
    keys = _account_keys(tx)
    pre_bal: list[int] = meta["preBalances"]
    post_bal: list[int] = meta["postBalances"]

    accts: dict[int, _TokenAcct] = {}
    for which, rows in (("pre", meta.get("preTokenBalances") or []), ("post", meta.get("postTokenBalances") or [])):
        for row in rows:
            if row.get("owner") != wallet:
                continue
            idx = row["accountIndex"]
            ui = row["uiTokenAmount"]
            acct = accts.get(idx)
            if acct is None:
                acct = _TokenAcct(
                    index=idx,
                    mint=row["mint"],
                    owner=wallet,
                    program=row.get("programId", ""),
                    decimals=int(ui["decimals"]),
                )
                accts[idx] = acct
            if which == "pre":
                acct.pre_raw = int(ui["amount"])
                acct.present_pre = True
            else:
                acct.post_raw = int(ui["amount"])
                acct.present_post = True

    out = ParsedBalances()

    try:
        wallet_idx = keys.index(wallet)
    except ValueError:
        return None
    native_delta = post_bal[wallet_idx] - pre_bal[wallet_idx]
    fee = int(meta.get("fee", 0))
    is_fee_payer = wallet_idx == 0
    out.fee_lamports = fee if is_fee_payer else 0

    # Jito tips the wallet paid are a landing cost, not part of the trade price.
    tips = 0
    if is_fee_payer:
        for i, k in enumerate(keys):
            if k in JITO_TIP_ACCOUNTS and i < len(pre_bal):
                tips += max(0, post_bal[i] - pre_bal[i])
    out.tips_lamports = tips

    # Lamports that moved into / out of the wallet's own token accounts: wrapped SOL (always
    # the wallet's money) and rent for new ATAs (refunded when closed). Adding them back makes
    # the SOL figure reflect only what was paid to / received from the market. Rent is only
    # attributed to the wallet when it pays the fees: in relayed transactions (trading-bot
    # relayers) the relayer usually funds the rent, and the error of ignoring a refund is
    # bounded by one account's rent (~0.002 SOL).
    own_token_lamports = 0
    for acct in accts.values():
        if acct.index >= len(pre_bal):
            continue
        if acct.mint == WSOL_MINT or is_fee_payer:
            own_token_lamports += post_bal[acct.index] - pre_bal[acct.index]

    out.sol_delta_lamports = native_delta + out.fee_lamports + tips + own_token_lamports

    for acct in accts.values():
        if acct.mint == WSOL_MINT:
            continue  # already counted through account lamports
        delta = acct.post_raw - acct.pre_raw
        if acct.mint in STABLE_MINTS:
            out.stable_deltas[acct.mint] = out.stable_deltas.get(acct.mint, 0) + delta
            continue
        out.token_deltas[acct.mint] = out.token_deltas.get(acct.mint, 0) + delta
        out.token_pre[acct.mint] = out.token_pre.get(acct.mint, 0) + acct.pre_raw
        out.token_post[acct.mint] = out.token_post.get(acct.mint, 0) + acct.post_raw
        out.decimals[acct.mint] = acct.decimals
        out.programs[acct.mint] = acct.program
    return out


# Ignore SOL movements smaller than this when classifying (rounding from rent etc.).
_MIN_QUOTE_LAMPORTS = 10_000


def extract_swaps(tx: dict, wallet: str) -> list[SwapEvent]:
    """Return the memecoin buys/sells `wallet` made in `tx` (usually 0 or 1 event)."""
    parsed = parse_balances(tx, wallet)
    if parsed is None:
        return []
    signature = tx["transaction"]["signatures"][0]
    slot = int(tx.get("slot", 0))
    block_time = tx.get("blockTime")

    movers = {m: d for m, d in parsed.token_deltas.items() if d != 0 and m not in NON_MEME_MINTS}
    if len(movers) != 1:
        # 0 => not a swap. >1 => token-to-token route or batch; it can't be priced in SOL
        # reliably, so it is skipped rather than guessed.
        return []
    mint, delta = next(iter(movers.items()))

    sol = parsed.sol_delta_lamports
    stable_mint, stable_delta = None, 0
    for m, d in parsed.stable_deltas.items():
        if d != 0:
            stable_mint, stable_delta = m, d

    if delta > 0:
        side = Side.BUY
        if sol <= -_MIN_QUOTE_LAMPORTS:
            quote_mint, quote_amount = WSOL_MINT, -sol
        elif stable_mint and stable_delta < 0:
            quote_mint, quote_amount = stable_mint, -stable_delta
        else:
            return []  # tokens arrived without payment: an airdrop or transfer, not a buy
    else:
        side = Side.SELL
        if sol >= _MIN_QUOTE_LAMPORTS:
            quote_mint, quote_amount = WSOL_MINT, sol
        elif stable_mint and stable_delta > 0:
            quote_mint, quote_amount = stable_mint, stable_delta
        else:
            return []  # tokens left without payment: a transfer out, not a sell

    return [
        SwapEvent(
            signature=signature,
            slot=slot,
            block_time=block_time,
            wallet=wallet,
            side=side,
            mint=mint,
            token_amount_raw=abs(delta),
            decimals=parsed.decimals.get(mint, 0),
            quote_mint=quote_mint,
            quote_amount_raw=int(quote_amount),
            token_balance_before_raw=parsed.token_pre.get(mint, 0),
            token_balance_after_raw=parsed.token_post.get(mint, 0),
            fee_lamports=parsed.fee_lamports,
            token_program=parsed.programs.get(mint, ""),
        )
    ]


def extract_transfers_out(tx: dict, wallet: str) -> dict[str, int]:
    """Mints whose balance dropped with no payment received (moved to another wallet).

    The scorer uses this as an insider / bundler tell: real traders sell, insiders shuffle
    supply between their own wallets.
    """
    parsed = parse_balances(tx, wallet)
    if parsed is None:
        return {}
    if abs(parsed.sol_delta_lamports) >= _MIN_QUOTE_LAMPORTS or any(parsed.stable_deltas.values()):
        return {}
    return {m: -d for m, d in parsed.token_deltas.items() if d < 0 and m not in NON_MEME_MINTS}
