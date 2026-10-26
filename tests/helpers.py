"""Builders for synthetic jsonParsed transactions (same shape as getTransaction returns)."""

from __future__ import annotations

from copybot.constants import TOKEN_2022_PROGRAM, TOKEN_PROGRAM, WSOL_MINT

WHALE = "WhaLe1111111111111111111111111111111111111"
POOL = "Poo11111111111111111111111111111111111111111"
MEME = "MemeMint111111111111111111111111111111pump"
TIP = "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"
SOL = 1_000_000_000
RENT = 2_039_280


def tok(index, mint, owner, amount, decimals=6, program=TOKEN_PROGRAM):
    return {
        "accountIndex": index,
        "mint": mint,
        "owner": owner,
        "programId": program,
        "uiTokenAmount": {"amount": str(amount), "decimals": decimals, "uiAmount": None, "uiAmountString": ""},
    }


def make_tx(sig, keys, pre, post, pre_tok, post_tok, *, fee=5_000, err=None, block_time=1_700_000_000, slot=1):
    return {
        "slot": slot,
        "blockTime": block_time,
        "version": 0,
        "transaction": {
            "signatures": [sig],
            "message": {"accountKeys": [{"pubkey": k, "signer": i == 0, "writable": True} for i, k in enumerate(keys)]},
        },
        "meta": {
            "err": err,
            "fee": fee,
            "preBalances": pre,
            "postBalances": post,
            "preTokenBalances": pre_tok,
            "postTokenBalances": post_tok,
        },
    }


def whale_buy_tx(sig, *, sol_spent, tokens, before=0, block_time=1_700_000_000, mint=MEME, wallet=WHALE, tip=0,
                 program=TOKEN_2022_PROGRAM, slot=1, bundled_to=()):
    """Whale (fee payer) buys `tokens` raw for `sol_spent` lamports, creating its ATA if needed."""
    fee = 5_000
    rent = RENT if before == 0 else 0
    keys = [wallet, f"{wallet[:20]}Ata{mint[:19]}", POOL, TIP]
    pre = [100 * SOL, RENT if before else 0, 500 * SOL, 10 * SOL]
    post = [100 * SOL - sol_spent - fee - rent - tip, RENT, 500 * SOL + sol_spent, 10 * SOL + tip]
    pre_tok = [tok(1, mint, wallet, before, program=program)] if before else []
    post_tok = [tok(1, mint, wallet, before + tokens, program=program)]
    for i, other in enumerate(bundled_to):  # same tx delivers tokens to other wallets (bundler)
        keys.append(f"{other[:20]}Ata{mint[:19]}")
        pre.append(0)
        post.append(RENT)
        post_tok.append(tok(len(keys) - 1, mint, other, tokens, program=program))
    return make_tx(sig, keys, pre, post, pre_tok, post_tok, fee=fee, block_time=block_time, slot=slot)


def whale_sell_tx(sig, *, sol_received, tokens, before, block_time=1_700_000_100, mint=MEME, wallet=WHALE,
                  close=False, program=TOKEN_2022_PROGRAM):
    fee = 5_000
    refund = RENT if close else 0
    keys = [wallet, f"{wallet[:20]}Ata{mint[:19]}", POOL]
    pre = [100 * SOL, RENT, 500 * SOL]
    post = [100 * SOL + sol_received - fee + refund, 0 if close else RENT, 500 * SOL - sol_received]
    pre_tok = [tok(1, mint, wallet, before, program=program)]
    post_tok = [] if close else [tok(1, mint, wallet, before - tokens, program=program)]
    return make_tx(sig, keys, pre, post, pre_tok, post_tok, fee=fee, block_time=block_time)


def wsol_funded_buy_tx(sig, *, sol_spent, tokens):
    """Buy paid out of an existing wrapped-SOL account (no native SOL moves except the fee)."""
    keys = [WHALE, "WsolAcct11111111111111111111111111111111111", "MemeAta111111111111111111111111111111111111", POOL]
    pre = [10 * SOL, sol_spent + RENT, RENT, 500 * SOL]
    post = [10 * SOL - 5_000, RENT, RENT, 500 * SOL + sol_spent]
    pre_tok = [tok(1, WSOL_MINT, WHALE, sol_spent, decimals=9), tok(2, MEME, WHALE, 0)]
    post_tok = [tok(1, WSOL_MINT, WHALE, 0, decimals=9), tok(2, MEME, WHALE, tokens)]
    return make_tx(sig, keys, pre, post, pre_tok, post_tok)
