"""On-chain mint inspection: authorities and Token-2022 extensions.

Important 2025+ edge case: new Pump.fun tokens are minted with **Token-2022** (with the
benign `metadataPointer` + `tokenMetadata` extensions). A gate that rejects Token-2022
outright would reject every fresh Pump.fun launch; a gate that only checks mint/freeze
authority would happily buy a token whose `permanentDelegate` can burn your balance or
whose `transferHook` blocks sells. We allow-list harmless extensions and reject the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .constants import SAFE_TOKEN_2022_EXTENSIONS, TOKEN_2022_PROGRAM, TOKEN_PROGRAM


@dataclass(frozen=True)
class MintInfo:
    mint: str
    program: str
    decimals: int
    supply_raw: int
    mint_authority: str | None
    freeze_authority: str | None
    extensions: tuple[str, ...] = ()
    problems: tuple[str, ...] = field(default=())

    @property
    def is_safe(self) -> bool:
        return not self.problems

    @property
    def immutable(self) -> bool:
        """Revoked authorities can never be re-enabled, so a clean result can be cached forever."""
        return self.mint_authority is None and self.freeze_authority is None


def inspect_mint(mint: str, account: dict | None) -> MintInfo:
    """`account` is the `value` of getAccountInfo(jsonParsed)."""
    if account is None:
        return MintInfo(mint, "", 0, 0, None, None, problems=("mint account not found",))
    owner = account.get("owner", "")
    data = account.get("data")
    if not isinstance(data, dict) or data.get("parsed", {}).get("type") != "mint":
        return MintInfo(mint, owner, 0, 0, None, None, problems=("account is not a token mint",))
    info = data["parsed"]["info"]
    problems: list[str] = []

    if owner not in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
        problems.append(f"unknown token program {owner}")

    mint_auth = info.get("mintAuthority")
    freeze_auth = info.get("freezeAuthority")
    if mint_auth is not None:
        problems.append("mint authority is enabled (supply can be inflated)")
    if freeze_auth is not None:
        problems.append("freeze authority is enabled (your tokens can be frozen)")

    ext_names: list[str] = []
    for ext in info.get("extensions") or []:
        name = ext.get("extension", "?")
        ext_names.append(name)
        state = ext.get("state") or {}
        if name in SAFE_TOKEN_2022_EXTENSIONS:
            continue
        if name == "transferFeeConfig":
            bps = max(
                int((state.get("olderTransferFee") or {}).get("transferFeeBasisPoints", 0)),
                int((state.get("newerTransferFee") or {}).get("transferFeeBasisPoints", 0)),
            )
            # Zero fee today with a live authority can become a 100% tax tomorrow.
            if bps > 0 or state.get("transferFeeConfigAuthority") is not None:
                problems.append(f"transfer fee (tax) {bps} bps / fee authority set")
            continue
        if name == "transferHook":
            if state.get("programId") is not None or state.get("authority") is not None:
                problems.append("transfer hook can block or tax transfers")
            continue
        problems.append(f"risky Token-2022 extension: {name}")

    return MintInfo(
        mint=mint,
        program=owner,
        decimals=int(info.get("decimals", 0)),
        supply_raw=int(info.get("supply", 0)),
        mint_authority=mint_auth,
        freeze_authority=freeze_auth,
        extensions=tuple(ext_names),
        problems=tuple(problems),
    )
