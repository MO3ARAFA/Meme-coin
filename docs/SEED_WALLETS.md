# Finding 30 seed wallets for the scorer (free, ~45 minutes)

The scorer is a filter, not an oracle. Feed it candidates that *look* profitable on public
leaderboards, and let it reject the farmers, snipers, insiders and lucky gamblers that
dominate those leaderboards. Expect 3–5 of 30 to survive. That is normal and healthy.

Site layouts change often. If a tab has been renamed, look for the equivalent
"top traders / PnL leaderboard" view.

## Step 1: Choose 8–10 "copyable" tokens on DexScreener (10 min)

On <https://dexscreener.com/solana>, sort by **24H** or **6H** gainers and keep only tokens that:

- have **liquidity ≥ $50k and market cap $300k–$20M**. Their traders operated where our
  gate operates. Wallets that only trade $8k-cap launches can never be copied by a bot with a
  $25k liquidity floor.
- are **older than 1 day**. Tokens that were rugged within hours mostly show sniper and bundler wallets.
- trade on **PumpSwap, Raydium or Meteora**, not the Pump.fun bonding curve.

## Step 2: Pull wallets from each token's Top Traders tab (15 min)

On each token page, open **Top Traders**. For each candidate, check the row.

Take wallets that:
- show **realized** profit, not just unrealized;
- bought **0.5–30 SOL** (bigger is fine, but dust buyers are often bait);
- show both a buy *and* a sell (you need closed trades).

Skip wallets that:
- bought in the first seconds of the chart (likely dev, bundler or sniper);
- have dozens of buys and sells on the same token (MM / farmer bot);
- are the pool, a CEX, or a known router (the scorer rejects these, but it wastes RPC credits).

Click the address, open it on Solscan, and copy it. Take 3–4 wallets per token.

## Step 3: Cross-check on GMGN and Birdeye (10 min)

- **GMGN.ai** (Solana): open a candidate's wallet page. It shows 7d/30d PnL, win rate and
  trade count. **Drop** any wallet GMGN labels *sniper, bundler, dev, insider* or *rat trader*.
  Its token pages also have a top-traders view, which is another source of candidates.
- **Birdeye**: the token *Top Traders* tab (24h/7d) and the wallet *Profile* PnL are a second
  opinion.
- **Priority signal:** a wallet that appears in the top traders of **2+ different tokens** is
  worth more than a one-hit wallet.

## Step 4: Run the scorer (≈1h with a free Helius key)

```bash
cat > seed_wallets.txt <<'EOF'
# one address per line; comments are fine
<WALLET_ADDRESS_1>   # from $TOKEN1 top traders, GMGN 30d +$12k
<WALLET_ADDRESS_2>   # in top traders of $TOKEN1 and $TOKEN4
EOF
python main.py score
```

Cost: each fetched transaction is one RPC call. 30 wallets × 1,500 transactions = 45,000
calls. That is about **75 minutes at 10 req/s on Helius free**, but **20+ hours on the public
endpoint** (measured: ~0.6 tx/s). Fetched transactions are cached under `data/cache/tx/`, so
re-scoring next week only fetches new activity.

Output:
- `approved_wallets.json`: the top 3–5 wallets with their full metrics.
- `data/scorer_report.json`: every wallet, with the exact reasons each one was rejected.
  Read it. It shows what the leaderboards are hiding.

## Step 5: Maintain the list

- Re-score **weekly**. Edges decay, and good wallets rotate or start farming once they get copied.
- After ~2 weeks of shadow trading, `python main.py report` shows PnL **per copied wallet**.
  Remove any wallet that is net negative for *you*, even if its own stats are good: its edge
  may not survive your latency.
