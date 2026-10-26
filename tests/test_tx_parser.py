from copybot.constants import WSOL_MINT
from copybot.tx_parser import Side, extract_swaps, extract_transfers_out

from .helpers import MEME, POOL, RENT, SOL, WHALE, make_tx, tok, whale_buy_tx, whale_sell_tx, wsol_funded_buy_tx


def test_buy_excludes_fee_rent_and_jito_tip_from_price():
    tx = whale_buy_tx("s1", sol_spent=2 * SOL, tokens=4_000_000_000, tip=1_000_000)
    [ev] = extract_swaps(tx, WHALE)
    assert ev.side is Side.BUY
    assert ev.mint == MEME
    assert ev.quote_mint == WSOL_MINT
    assert ev.quote_amount_raw == 2 * SOL  # not 2 SOL + fee + ATA rent + tip
    assert ev.token_amount_raw == 4_000_000_000
    assert ev.price_quote_per_raw == 0.5
    assert ev.token_balance_after_raw == 4_000_000_000


def test_sell_with_account_close_counts_rent_refund_out_of_proceeds():
    tx = whale_sell_tx("s2", sol_received=3 * SOL, tokens=4_000_000_000, before=4_000_000_000, close=True)
    [ev] = extract_swaps(tx, WHALE)
    assert ev.side is Side.SELL
    assert ev.quote_amount_raw == 3 * SOL  # rent refund is not trading profit
    assert ev.sold_fraction == 1.0
    assert ev.token_balance_after_raw == 0


def test_partial_sell_fraction():
    tx = whale_sell_tx("s3", sol_received=SOL, tokens=1_000, before=4_000)
    [ev] = extract_swaps(tx, WHALE)
    assert ev.sold_fraction == 0.25
    assert ev.token_balance_after_raw == 3_000


def test_buy_funded_from_wrapped_sol_account():
    [ev] = extract_swaps(wsol_funded_buy_tx("s4", sol_spent=SOL, tokens=10_000), WHALE)
    assert ev.side is Side.BUY
    assert ev.quote_amount_raw == SOL


def test_relayed_tx_where_whale_is_not_fee_payer():
    relayer = "Re1ayer111111111111111111111111111111111111"
    keys = [relayer, WHALE, "WhaleAta1111111111111111111111111111111111", POOL]
    tx = make_tx(
        "s5", keys,
        pre=[5 * SOL, 10 * SOL, 0, 500 * SOL],
        post=[5 * SOL - 5_000 - RENT, 9 * SOL, RENT, 501 * SOL],
        pre_tok=[], post_tok=[tok(2, MEME, WHALE, 777)],
    )
    [ev] = extract_swaps(tx, WHALE)
    assert ev.quote_amount_raw == SOL
    assert ev.fee_lamports == 0


def test_failed_transaction_is_ignored():
    tx = whale_buy_tx("s6", sol_spent=SOL, tokens=10)
    tx["meta"]["err"] = {"InstructionError": [2, {"Custom": 6001}]}
    assert extract_swaps(tx, WHALE) == []


def test_token_to_token_route_is_skipped_not_guessed():
    other = "OtherMint11111111111111111111111111111pump"
    keys = [WHALE, "AtaA111111111111111111111111111111111111111", "AtaB111111111111111111111111111111111111111"]
    tx = make_tx(
        "s7", keys, pre=[SOL, RENT, RENT], post=[SOL - 5_000, RENT, RENT],
        pre_tok=[tok(1, MEME, WHALE, 0), tok(2, other, WHALE, 500)],
        post_tok=[tok(1, MEME, WHALE, 900), tok(2, other, WHALE, 0)],
    )
    assert extract_swaps(tx, WHALE) == []


def test_airdrop_is_not_a_buy_and_transfer_out_is_detected():
    keys = [WHALE, "AtaA111111111111111111111111111111111111111"]
    airdrop = make_tx("s8", keys, pre=[SOL, RENT], post=[SOL - 5_000, RENT],
                      pre_tok=[tok(1, MEME, WHALE, 0)], post_tok=[tok(1, MEME, WHALE, 100)])
    assert extract_swaps(airdrop, WHALE) == []
    send = make_tx("s9", keys, pre=[SOL, RENT], post=[SOL - 5_000, RENT],
                   pre_tok=[tok(1, MEME, WHALE, 100)], post_tok=[tok(1, MEME, WHALE, 0)])
    assert extract_swaps(send, WHALE) == []
    assert extract_transfers_out(send, WHALE) == {MEME: 100}


def test_real_mainnet_version1_transaction():
    """Mainnet carries v1 transactions (Oct 2026). Captured with jsonParsed; instructions and
    logs stripped. The parser only needs balances, which are version-independent."""
    import json
    from pathlib import Path

    tx = json.loads((Path(__file__).parent / "fixtures" / "mainnet_v1_tx.json").read_text())
    assert tx["version"] == 1
    [ev] = extract_swaps(tx, "BBNe6tSmvsKSc58CEHpRnH1PnkWhekTryKascaCUtDuJ")
    assert ev.side is Side.SELL
    assert ev.mint == "C5xph2yL6gMdxmuLGxJBkGpmuDFfyi5fqkBNhvL6pump"
    assert ev.quote_amount_raw == 330_076_724
    assert ev.token_amount_raw == 3_635_826_554
    # the arbitrage bot that paid for this tx made no memecoin trade
    assert extract_swaps(tx, "NALUxTJsozrScVNzRWy9LAg2xoC37RXNNZyyem76kmc") == []
