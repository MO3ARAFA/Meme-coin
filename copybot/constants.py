"""On-chain addresses and protocol constants. All values are public, well-known program IDs."""

LAMPORTS_PER_SOL = 1_000_000_000

# Mints
WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
STABLE_MINTS = frozenset({USDC_MINT, USDT_MINT})
# Assets a wallet "pays with" when it buys a memecoin.
QUOTE_MINTS = frozenset({WSOL_MINT}) | STABLE_MINTS

# Liquid staking tokens and majors are not memecoins: never treat them as copy signals.
NON_MEME_MINTS = QUOTE_MINTS | frozenset(
    {
        "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",  # mSOL
        "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # JitoSOL
        "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",  # bSOL
        "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v",  # jupSOL
        "pSo1f9nQXWgXibFtKf7NWYxb5enAM4qfP6UJSiXRQfL",  # pSOL
        "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",  # JUP
        "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh",  # WBTC
        "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",  # WETH (Wormhole)
    }
)

# Programs
SYSTEM_PROGRAM = "11111111111111111111111111111111"
COMPUTE_BUDGET_PROGRAM = "ComputeBudget111111111111111111111111111111"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
JUPITER_V6_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
MEMO_PROGRAM_V1 = "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo"

# Top-level programs a Jupiter swap transaction is allowed to invoke. Anything else
# (e.g. a raw SPL Token transfer or approve) means the transaction is not what we asked for.
SWAP_TX_PROGRAM_ALLOWLIST = frozenset(
    {
        JUPITER_V6_PROGRAM,
        COMPUTE_BUDGET_PROGRAM,
        SYSTEM_PROGRAM,
        TOKEN_PROGRAM,
        TOKEN_2022_PROGRAM,
        ATA_PROGRAM,
        MEMO_PROGRAM,
        MEMO_PROGRAM_V1,
    }
)

# Jito tip accounts (public, documented by Jito Labs). Used to (a) exclude tips from a
# wallet's execution price and (b) whitelist tip transfers in swap tx verification.
JITO_TIP_ACCOUNTS = frozenset(
    {
        "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
        "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
        "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
        "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
        "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
        "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
        "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
        "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
    }
)

# Token-2022 mint extensions that cannot hurt a holder. Anything not listed here is
# rejected by the safety gate (fail-closed): permanentDelegate can burn/steal your tokens,
# transferHook can block sells, transferFeeConfig is a sell tax, pausable can freeze trading.
SAFE_TOKEN_2022_EXTENSIONS = frozenset(
    {
        "metadataPointer",
        "tokenMetadata",
        "groupPointer",
        "groupMemberPointer",
        "tokenGroup",
        "tokenGroupMember",
        "mintCloseAuthority",  # can only close a mint whose supply is zero
    }
)

# Signature fee per signature (protocol constant).
BASE_FEE_LAMPORTS = 5_000
# Rent-exempt minimum of an SPL token account (165 bytes). Token-2022 accounts with
# extensions are slightly larger; we read the real value from chain when it matters.
TOKEN_ACCOUNT_RENT_LAMPORTS = 2_039_280
