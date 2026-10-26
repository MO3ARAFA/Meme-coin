# Architecture review of the 5-module mandate

The mandate is sound in spirit, and most of it is implemented exactly as written. This
document covers where it would **fail as written** on Solana in late 2026, what the code does
instead, and what is still unsolved. Measured numbers come from live mainnet calls made
while building this (Oct 2026).

---

## A. Corrections to the mandate

### A1. Win-rate window has a hole (Module A)
The mandate accepts wallets with a win rate up to 82% and rejects them above 85%. That leaves
82–85% undefined. **Fix:** anything above 82% is rejected (`SCORER__MAX_WIN_RATE`).

### A2. Median ROI alone can be gamed (Module A)
A wallet with 60% of trades at +16% and 40% at −90% has a median ROI of +16% and passes, yet
it loses money every week. **Fix:** two extra checks.
- **Profit factor ≥ 1.5** (gross profit / gross loss).
- **Top-trade concentration ≤ 50%**: one 50x cannot be most of the profit. This catches the
  "lottery ticket" case from the other side.

### A3. Hold time must measure the *first* sell, not the full exit (Module A)
A farmer sells 95% of the bag 3 seconds after the copy-bots pile in, then holds dust for an
hour. The "average hold" then looks like 60 minutes. **Fix:** a trade counts as a flip when its
**first sell** lands under 120 s after the buy. More than 30% flips means blacklist. A cycle only
closes when the holding falls to ≤1% of its peak, so dust can't extend it.

### A4. Block-0 detection needs a launch time (Module A)
Deriving the creation slot of every token from RPC is expensive: you paginate the mint's history
back to its first signature. **Fix:** DexScreener's earliest `pairCreatedAt` for the mint. The
Pump.fun curve pair is created in the mint transaction, and one call covers 30 tokens. A buy
within **2 s (~5 slots)** of launch counts as a block-0/1 snipe. More than 30% of winners
sniped means reject.

### A5. Insiders hide behind transfers (Module A + C)
Bundlers and devs often *move* tokens to fresh wallets and dump from there, so no sell is ever
recorded. **Fix:**
- The scorer counts cycles that ended by transfer-out. Over 25% means reject.
- The exit engine tracks the whale's **token balance**, not its sells. A transfer of ≥30% of
  its peak holding triggers our full exit, exactly like a sell.

### A6. `Mint/Freeze = None` is necessary but nowhere near sufficient (Module B)
Since 2025, new Pump.fun tokens are minted with **Token-2022** (verified live: extensions
`metadataPointer` and `tokenMetadata`). Two naive outcomes:
- Rejecting Token-2022 outright skips every fresh Pump.fun launch.
- Checking only the authorities lets through `permanentDelegate` (can burn or move your tokens),
  `transferHook` (can block sells), `transferFeeConfig` (a sell tax, possibly 100%) and
  `pausable`.

**Fix:** an allow-list of harmless extensions. Anything else fails closed. A transfer-fee
extension is rejected even at 0 bps if its authority is live. In the live test, PYUSD was
rejected on 7 counts.

### A7. Honeypots and sell taxes pass every static check (Module B)
**Fix:** a **round-trip quote**. Quote SOL→token for our exact size, then token→SOL for the
exact output. One number covers DEX fees on both legs, impact on both legs, transfer taxes
and missing sell routes. Abort if the loss exceeds 5%.

### A8. Anti-chase must compare like with like (Module B)
- The whale's execution price is derived from balance deltas **excluding** network fee,
  priority fee, Jito tip and ATA rent. Otherwise the whale's price looks worse than it was,
  the chase looks smaller, and the bot chases more.
- Both prices are in **lamports per raw token unit**. Decimals cancel (the token-decimals
  bug class is gone) and SOL/USD drift is irrelevant.
- Our price comes from a **fresh executable Jupiter quote** at our size, not a chart price,
  so the latency of the check itself is priced in.

### A9. The 1.2% fee cap blocks most low-cap PumpSwap tokens (Module D)
Measured live on a $115k-market-cap PumpSwap token: the round trip lost **2.5%**, which is
**1.26% per leg** from the pool fee alone (Pump's dynamic fee tiers are highest at low market
caps). Under a 1.2% all-in cap, those tokens are **always** skipped. The code keeps the
mandate's value and gives the priority fee only what the budget leaves.

**Your call:** either keep 1.2% (fewer, cleaner trades) or set `RISK__MAX_LEG_COST_PCT=0.016`
and let the shadow journal show whether those trades are worth it. Shadow mode is free, so
measure before deciding.

Also: exits are **never** blocked by the fee cap. A stop-loss that can't fire costs far more
than a fee.

### A10. Rent is the hidden fee at $10 positions (Module D)
Opening a token account locks **~0.00204 SOL**, about **2% of a 0.1 SOL position**. It is refunded
only when the account is **closed**. **Fix:** LIVE closes the account after every full exit,
and shadow mode books the rent as locked capital, refunded on close.

### A11. Your SOL math is out of date (Module D)
SOL traded at **~$101** during the build, so $100 ≈ 1 SOL and a 10% position ≈ 0.1 SOL (the
mandate assumed 0.05–0.07 SOL). Sizing is a fraction of SOL equity, so it is unit-free;
`SHADOW_STARTING_SOL` defaults to 1.0.

### A12. Exits must use *executable* prices (Module C)
A chart price says +45%. A sell quote for your size after fees might say +38%. **Fix:** every
trigger is evaluated on the **net value ratio**: Jupiter sell-quote output for our exact
remaining tokens, minus the estimated exit fee, divided by the remaining cost basis. That
makes "+45% net profit" mean net.

Jupiter's free tier returned HTTP 429 at ~1 req/s bursts (measured), so positions are marked
with one batched DexScreener call (30 tokens per call). A Jupiter quote is spent only when:
- the mark suggests a trigger fired,
- the mark shows a new high, or
- the 12 s refresh comes due.

The mark self-calibrates against every real quote.

### A13. Additional exit protection (Module C)
- **Max hold of 4 h.** Never bag-hold a memecoin overnight.
- **Rug emergency.** When the sell route disappears for 90 s, attempt an emergency exit at
  15% slippage. If there is still no route, the position is written off honestly in the
  journal instead of sitting as "open" forever.

### A14. Circuit breaker counts unrealized losses (Module D)
Three open positions at −20% each is a −6% day that realized-only accounting doesn't see.
The breaker uses realized + marked-to-quote unrealized PnL. Exits keep running while entries
are halted.

### A15. "50+ profitable shadow trades" is not an edge (Module E)
50 wins of +5% and 15 losses of −22% is a losing system with 50 profitable trades (there is a
test for exactly this). **Fix:** LIVE refuses to start until the shadow journal shows:
- ≥ 50 closed trades,
- profit factor ≥ 1.3,
- expectancy ≥ +2% per trade,
- max drawdown ≤ 20%.

There is an explicit, loudly named override flag.

### A16. Shadow fills must be pessimistic (Module E)
Each paper fill uses:
- a real quote, minus a **75 bps latency haircut**;
- base + priority fees;
- rent;
- a **simulated revert** when the haircut breaches the slippage limit.

If shadow is optimistic, LIVE disappoints with real money.

### A17. The <300 ms gate target isn't reachable on free endpoints
Measured: **365–680 ms** with a full rate-limit bucket, up to ~1 s under load (DexScreener +
mint RPC + buy quote run concurrently, then a dependent sell quote, all within Jupiter's free
0.8 req/s). With a paid RPC, a Jupiter key and a VPS near the endpoints, expect
150–300 ms. The gate has a 2.5 s hard timeout and fails closed. Because the chase check uses
the fresh quote, a slow gate makes the bot *skip*, never *overpay*.

---

## B. Solana edge cases handled in code

| Edge case | Where | How |
|---|---|---|
| Pump.fun curve vs PumpSwap / Raydium / Meteora routing | `tx_parser.py`, `jupiter.py` | Swaps are read from **balance deltas**, not per-DEX instruction decoding, so every venue, router (Photon/Axiom/BullX) and future program works. Jupiter routes the Pump.fun curve and PumpSwap directly (verified live). |
| Bonding-curve tokens report no liquidity | `safety_gate.py` | DexScreener `liquidity` is `null` on `pumpfun` pairs. Treated as fail (below the $25k floor). The most liquid AMM pair is used otherwise. |
| **Version-1 transactions (new on mainnet)** | `solana_rpc.py` | Found during the build: mainnet now carries **v1** transactions, and `maxSupportedTransactionVersion: 0` (what reference copy bots use) makes the node *refuse* them with error −32015. Those whale trades are silently missed. We request v1 and auto-upgrade if the node reports a newer version. The jsonParsed balance fields are unchanged (regression test on a real captured v1 transaction). |
| Memes paired with WBTC/USDC instead of SOL | `exit_manager.py` | Marks use the most liquid pair regardless of quote token. Executable values always come from SOL sell quotes. |
| Token decimals | everywhere | Raw base units end-to-end. Prices are lamports/raw. |
| wSOL vs native SOL | `tx_parser.py` | Wrapped SOL in the wallet's own token accounts counts as SOL. Temporary wSOL accounts net out. |
| ATA rent in prices | `tx_parser.py` | Lamport changes on the wallet's token accounts are added back. |
| Relayed transactions (whale ≠ fee payer) | `tx_parser.py` | Fees and rent are not attributed to the whale. A bug here was caught by a test during the build. |
| Token-to-token routes | `tx_parser.py` | Skipped rather than mispriced. |
| `logsSubscribe` takes 1 address | `listener.py` | One subscription per wallet, on one connection. |
| Silent WebSocket drops | `listener.py` | Pings, exponential reconnect, `getSignaturesForAddress(until=last)` backfill, signature dedupe. |
| RPC lags behind WebSocket | `solana_rpc.py` | `getTransaction` retries `null` with backoff. |
| Free-tier rate limits | `http_utils.py` | A token bucket per provider, a **non-cumulative** 429 penalty (concurrent 429s once stacked into multi-second stalls during the build), `Retry-After`, jittered retries. Jupiter runs at 0.8 rps, burst 2. |
| Stale signals after a reconnect | `safety_gate.py` | Whale transactions older than 25 s are not copied. |
| Restart with open positions | `state.py` | Atomic JSON state (positions, cooldowns, breaker, cursors). A test covers restart. |
| Two whales buying the same token | `copy_engine.py` | Entries are serialized. One position per mint per 24 h. |

---

## C. Security model (zero trust)

1. **No key in SHADOW.** `wallet_vault.load_signer()` is only called in LIVE.
2. **Key never printable.** Verified during the build: `repr(Keypair)` and `str(Keypair)` in
   solders **print the secret key**. A stray `log.info(kp)` or a traceback would leak it.
   `Signer` wraps the key and exposes only the pubkey and signing. It refuses to be pickled.
   Keypair files must be `chmod 600`.
3. **Every API-built transaction is verified before signing** (`tx_verify.py`):
   - we are the only signer and the fee payer;
   - top-level programs are allow-listed;
   - SOL transfers only go to our own wSOL account (bounded by the input) or a Jito tip
     account (bounded by the cap);
   - SPL Token instructions are limited to SyncNative and CloseAccount-to-self (no
     Transfer/Approve/SetAuthority);
   - the priority fee is ≤ the cap.

   Tested against real Jupiter transactions (buy and sell, priority and Jito) and against
   crafted attacks.
4. **Simulation guard.** Before sending, the signed transaction is simulated, and it is
   refused if the wallet would lose more SOL than input + fee cap + rent.
5. **Supply chain.** There are 5 direct dependencies, all mainstream. `requirements.txt` is
   **hash-locked** (`pip install --require-hashes`), and transitive dependencies are pinned
   to mature releases, not whatever shipped this week. No Solana "SDK wrappers", no `bs58`
   clones, no `crypto-layout`.
6. **Operational.** Use a burner wallet holding only the risk budget. Never reuse a wallet
   that holds anything else. The bot never needs your main wallet.

---

## C2. Findings from scoring real wallets (Oct 2026)

- **Vault-funded buys.** Some trading-bot programs (seen: `proVF4…`) pay for buys from a
  program-held deposit vault, so the wallet's SOL barely moves. The buy parses as nearly free,
  and the sell as a 130,000x. Cycles bought for < 0.01 SOL or returning > 20x are now
  *unpriced*: excluded from stats, and the wallet is rejected if > 25% of its exits are unpriced
  (its buy signals carry no usable price for the copy engine either).
- **A high whale PF is not a copyable edge.** A wallet with 187 trades, 65% win rate and PF
  2.17 replayed at **−2.7%/trade** for a copier (replay win rate 28%, PF 0.44). Its PF was
  size-weighted on a few big trades. Its typical trade (+2–5%) is smaller than our latency +
  fee cost. Only the replay exposes this.
- **Recent pool transactions are mostly bots.** 17 of 30 wallets sampled from the latest pool
  activity did 300–470 tx/day. `harvest` samples evenly across thousands of signatures,
  requires a system-owned account (pools and vaults are program-owned), ≤ 80 tx/day, and
  realized profit in ≥ 2 different tokens.
- **The supply of fresh liquid memecoins is small.** On a given day, only ~13 Solana tokens
  are 1–14 days old with ≥ $40k liquidity and ≥ $100k volume (GeckoTerminal + DexScreener).
  About 50 requires an age window of ~120 days (`HARVEST__MAX_AGE_DAYS`).

## D. What remains unsolved (be honest with yourself)

- **Structural latency.** You are always 1–3 slots behind the whale. The edge must survive
  that. Shadow mode measures exactly this; nothing else can.
- **Copier-baiting.** Bait-size detection and auto-quarantine catch the crude versions. A
  patient hunter that keeps normal sizes and holds 3+ minutes before dumping looks like a
  normal trader. Re-score weekly and prune by your own per-wallet shadow PnL (`report` shows it).
- **The replay has no price path.** It re-prices the whale's own exit, not our independent exit
  engine (stops, trail, time decay). It is a necessary filter, not a backtest of our exits.
- **Sybil links are direct links only.** Two wallets funded from the same CEX, or linked through
  an intermediate wallet, are not detected.
- **Scorer survivorship.** Seeds come from leaderboards of tokens that *went up*. The filters
  reduce, but cannot remove, that bias.
- **LP burn and holder concentration** are not checked yet. PumpSwap migrations burn LP, but
  Raydium/Meteora pools may not. The round-trip check, liquidity floor, stops and rug-emergency
  exit mitigate this. The next additions would be a `getTokenLargestAccounts` top-holder check
  and an LP-burn check for non-Pump pools.
- **MEV on your own buys.** A swap sent through a normal RPC can be sandwiched by the leader
  or validator that receives it. Tight slippage (2% entry) caps the damage. Submitting
  through a Jito block-engine / MEV-protected send endpoint would reduce it further. That is
  not implemented yet: `JITO_TIP` mode adds the tip, but the transaction still goes through
  your RPC.

Nothing here is financial advice. Memecoin trading can and often does lose 100% of the capital
involved.
