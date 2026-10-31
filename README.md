# copybot — anti-exit-liquidity Solana memecoin copy trader

A self-hosted, auditable Python engine that:

1. **scores** candidate wallets and keeps only *copyable* smart money, rejecting farmers,
   snipers, insiders and lucky gamblers;
2. **listens** to those wallets in real time;
3. **gates** every copy through liquidity, contract-security, anti-chase and honeypot checks;
4. **manages exits on its own**, front-running the whale's dump instead of waiting for it;
5. runs in **SHADOW_PAPER mode by default**: live data, paper fills, no private key.

There are ~3,500 lines of code (about a third of them comments) you can read in an evening, and 5 mainstream dependencies,
hash-locked. Read [`docs/ARCHITECTURE_REVIEW.md`](docs/ARCHITECTURE_REVIEW.md) before
trusting it with money.

> ⚠️ Memecoin trading usually loses money. This is software, not financial advice. Run
> shadow mode for weeks, and never put more in the bot's wallet than you can lose entirely.

## Architecture

```
seed_wallets.txt ──► wallet_scorer ──► approved_wallets.json
                     (Module A)                │
                                               ▼
 Solana WS logsSubscribe ──► listener ──► copy_engine ──► tx_parser (balance deltas)
 (+ backfill / poll)                           │
                       BUY ────────────────────┤──────────────── SELL / transfer
                        ▼                      │                      ▼
                  safety_gate (B)              │          whale holding ↓ ≥30%
         DexScreener ∥ mint RPC ∥ Jupiter      │                      │
         → round-trip quote → fee guard        │                      ▼
                        ▼                      │              exit_manager (C)
                  risk_config (D)              │   whale-exit · stop · trail · scale-out
          10% size · 3 max · breaker           │   · time-decay · max-hold · rug
                        ▼                      │                      │
                  executor (E) ◄───────────────┴──────────────────────┘
       SHADOW: live quote − latency haircut      LIVE: Jupiter tx → verify → simulate
       → shadow_trades.csv                        → sign (solders) → send → confirm
```

| File | Role |
|---|---|
| `copybot/config.py` | Every threshold, typed (pydantic), overridable from `.env` |
| `copybot/momentum.py` | Optional breakout-momentum signal source: pure detector + DexScreener scanner |
| `copybot/harvester.py` | Cross-token mid-wave discovery (`harvest`) and co-buyer graph discovery (`--co-buyers`) |
| `copybot/fingerprint.py` | Execution fingerprints (compute budget, program sequence, tips) and timing entropy |
| `copybot/cabal_detector.py` | Same-tx bundles, co-slot cabals, holder concentration (pools/PDAs excluded) |
| `copybot/ai_analyst.py` | Optional Claude forensic judge (veto only) and post-buy overwatch |
| `copybot/evidence.py` | Evidence ledger: every COPY/ABORT/EXIT/EJECT/QUARANTINE with slot, signature, reason |
| `copybot/adversarial_shield.py` | **Pillar 1**: kill switch (net copy EV after all frictions + exit-liquidity risk score, RugCheck) |
| `copybot/social_radar.py` | **Pillar 2**: boosts / takeovers / profiles / PumpSwap migrations, social legitimacy, universe expansion |
| `copybot/treasury_cfo.py` | **Pillar 3**: accounting ledger, meritocracy sizing (12% / 10% / 5%), high-water-mark profit lock |
| `copybot/self_improver.py` | **Pillar 4**: post-exit regret, bounded AI/rules tuning, hot-reloaded `runtime_overrides.json` |
| `copybot/wallet_scorer.py` | **Module A**: trade cycles, copyability filters, latency-adjusted replay, sybil links |
| `copybot/safety_gate.py` | **Module B**: liquidity / mcap / authorities / Token-2022 / chase / round trip |
| `copybot/token_security.py` | Mint inspection with a Token-2022 extension allow-list |
| `copybot/exit_manager.py` | **Module C**: pure `decide_exit()` + monitoring loop |
| `copybot/risk_config.py` | **Module D**: sizing, per-leg fee budget, circuit breaker |
| `copybot/executor.py` | **Module E**: `ShadowExecutor` / `LiveExecutor` (same interface) |
| `copybot/copy_engine.py` | Orchestration: signal → gate → risk → execute → positions |
| `copybot/tx_parser.py` | Venue-agnostic swap extraction from balance deltas |
| `copybot/tx_verify.py` | Zero-trust check of API-built transactions before signing |
| `copybot/wallet_vault.py` | The only code that touches a key (LIVE only); never printable |
| `copybot/listener.py` | WebSocket per-wallet subscriptions, reconnect + backfill |
| `copybot/solana_rpc.py`, `jupiter.py`, `dexscreener.py` | Thin, auditable API clients |
| `copybot/state.py`, `report.py` | Crash-safe state, trade journal, LIVE-readiness gate |
| `main.py` | CLI |

## Quick start (shadow mode, no key)

```bash
git clone <this repo> && cd Meme-coin
python3 -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements.txt   # every package verified by hash
cp .env.example .env    # add a free Helius RPC URL; nothing else is required

python main.py doctor                  # RPC, WebSocket, Jupiter, DexScreener all reachable?
python main.py harvest                 # multi-token winners from 50-80 liquid memecoins -> seed_wallets.txt
python main.py harvest --co-buyers     # wallets that bought approved whales' winners BEFORE them
python main.py score                   # -> approved_wallets.json (+ data/scorer_report.json)
python main.py check-token <MINT>      # see the safety gate's verdict on any token
python main.py run                     # shadow copy-trading; Ctrl-C to stop (state persists)
python main.py report                  # PnL, exits by trigger, PnL per wallet, LIVE readiness
python main.py cfo                     # treasury statement: flows, friction, meritocracy, locked reserve
python main.py evolve                  # one bounded tuning round (AI if reachable, rules otherwise)
python main.py radar --expand          # social/narrative radar; queue early profitable traders
python main.py score --with-queue      # score seeds + radar queue
```

Run the tests: `pip install -r requirements-dev.txt && pytest`. The suite has 131 tests (120 without the
optional lab), including a full shadow lifecycle against fake markets and a real captured mainnet v1
transaction.

## Momentum signal source (optional, off by default)

A second way to find entries, next to copy-trading: breakout momentum on liquid memecoins that are
at least 6 hours old. It is *only a signal*: every candidate goes through the **same** safety gate,
kill switch, fee guard, circuit breaker and exit engine as a copied whale buy, at half the base
size (`MOMENTUM__SIZE_FRAC=0.05`) because it has no track record yet.

```bash
python main.py momentum-scan          # watch live signals, observation only, never trades (warm-up ~2 min)
MOMENTUM__ENABLED=true python main.py run     # shadow-trade them; works without approved_wallets.json
```

| Rule | Default | Why |
|---|---|---|
| Return over 5 min | +8% to +60% | below = no trend; above = a vertical candle, i.e. buying the top |
| Up-steps | >= 55% of samples rose | a grind, not one spike |
| Distance from window high | <= 3% | still going, not fading |
| Buys in 5 min / buy ratio | >= 25 / >= 60% | real flow behind the move |
| Pair | SOL-quoted AMM, >= $40k liquidity, 6 h - 14 d old | never a launch: that is sniping |

The signal's own price is the anti-chase reference, so if the market runs past `SAFETY__MAX_CHASE_PCT`
(12%) before we can fill, the gate aborts. There is no whale behind these positions: they exit on
the hard stop, trail, scale-out and timers only. Positions are tagged `MOMENTUM` in the journal, so
`python main.py report` and `cfo` show the source's own record. **Judge it by that shadow record, not
by a backtest.**

## Research lab: backtesting on NautilusTrader (optional)

`nautilus_lab/` runs the momentum strategy on historical candles with
[NautilusTrader](https://github.com/nautechsystems/nautilus_trader). It imports the bot's own
`detect_momentum` and `decide_exit`, so a backtest exercises the production entry and exit logic.
It is a separate install because the core stays five hash-locked packages:

```bash
pip install --require-hashes -r requirements.txt && pip install -r requirements-lab.txt
python -m nautilus_lab pools                     # liquid memecoin pools worth studying
python -m nautilus_lab fetch <POOL> --days 3     # 1-minute candles (GeckoTerminal) -> data/lab/
python -m nautilus_lab backtest --pool <POOL1> <POOL2> <POOL3>
python -m nautilus_lab backtest --synthetic      # plumbing check on generated data (proves nothing about profit)
```

It reports win rate, profit factor, expectancy and drawdown against the same thresholds as the
LIVE-readiness gate. Read [`nautilus_lab/README.md`](nautilus_lab/README.md) before trusting a number:
candles have no honeypot filter, `--delay-bars 0` is zero latency (optimistic), and a handful of trades
means nothing.

## Going LIVE (only after the shadow record earns it)

1. `python main.py report` must show **LIVE readiness: READY**: ≥50 closed trades,
   profit factor ≥1.3, expectancy ≥+2%/trade, max drawdown ≤20%.
2. Create a **new burner wallet** and fund it with your risk budget only:
   `solana-keygen new -o ~/.config/copybot/burner.json && chmod 600 ~/.config/copybot/burner.json`
3. In `.env`, set `EXECUTION_MODE=LIVE` and `KEYPAIR_PATH=~/.config/copybot/burner.json`.
4. `python main.py run`. Every Jupiter transaction is decoded, checked against an
   allow-list, and simulated before it is signed.

## Adversarial intelligence (the anti-copy-trading layer)

Whales know they are being copied. Four defenses assume they are actively hostile:

| Defense | Where | What it does |
|---|---|---|
| **Latency-adjusted replay** | `score` | Re-prices every historical trade the bot could have replicated (copyable size, closed within our 4 h max hold) as *we* would have filled it (entry +2.5%, 1.2% fee per leg). The top 5% is dropped, and replay PF must be ≥ 1.35 with positive expectancy. A whale's PF is worthless if the edge dies 2 slots later. |
| **Bait-size detection** | live gate | A buy smaller than 30% of the wallet's median buy (from `approved_wallets.json`) is treated as an inducement (a small buy from the public wallet while dumping from a shadow wallet) and aborted. |
| **Sybil links + independent cluster consensus** | `score` + live engine | Wallets that send SOL or tokens to each other form one *link group* (one operator, one approval slot). When 2+ wallets from **different** link groups buy the same token within 10 min, the position is tagged `HIGH_CONVICTION_CLUSTER` and its runner gets a 25% trail instead of 15% after the scale-out. Linked wallets never confirm each other. |
| **Auto-quarantine** | live engine | Two "dumped within 90 s of its own buy" events quarantine the wallet. It is moved to `quarantined` in `approved_wallets.json`, its signals are ignored, and it, along with every wallet linked to it, stays barred across re-scores. |

## Chameleon exits and forensic layers

- **Moonbag runner.** The 45 min time decay and 4 h max hold apply only *before* the +45%
  scale-out. After it, the remaining half is house money: no timer, a +15% floor, and a 25%
  trail (30% for `HIGH_CONVICTION_CLUSTER`). The whale-exit trigger still applies.
- **Convex imitation penalty.** The replay prices every copied trade with an entry penalty of
  1.5% + min(6%, whale buy SOL × 0.8%), plus our 1.2% fee on both legs, and models the
  scale-out + moonbag exactly.
- **Live imitation budget.** The gate aborts when price drift + round-trip cost eats ≥ 65% of
  that wallet's historical raw edge (`expected_edge_pct` in `approved_wallets.json`).
- **Holders.** `getTokenLargestAccounts` runs in parallel with the other gate checks. Abort if
  the top-5 *real* holders own > 35%, one owns > 12%, or ≥ 4 top wallets hold near-identical
  bags. Pools, LP vaults and curves (program-owned / off-curve PDA owners) are excluded first.
  Calibrated on 45 live tokens: 4 rejected, all clear cases.
- **Cabals.** The gate aborts when the whale's buy transaction also delivered the token to other
  wallets. `score` rejects wallets whose buys repeatedly share a slot with the same partners
  across tokens (> 25%), timer-driven wallets (buy-interval CV < 0.35), and merges sybils by
  execution fingerprint **plus** repeated co-buys within 60 s. Fingerprint alone is not used,
  since every user of one trading frontend shares its defaults.
- **AI forensics (optional).** `pip install --require-hashes -r requirements-ai.txt` and set
  `LLM__API_KEY` (plus `LLM__BASE_URL` for a compatible endpoint). The judge can only **veto**
  wallets the numbers approved. The post-buy overwatch may eject only with an on-chain flag
  behind it. Neither ever runs in the pre-buy path. `doctor` probes the key and model.
- **Evidence ledger.** `data/evidence.jsonl` holds every decision with its on-chain proof.

## Autonomous pillars

1. **Kill switch.** After the live quotes are in, a copy is vetoed when its expected net return
   after drift, exit cost, tips and a slippage reserve is ≤ 0, or when its exit-liquidity risk
   score is ≥ 60/100 (holders, bundled whale buy, hunter strikes, consumed edge, pool impact,
   token age, RugCheck dangers). Every point of the score is explained in the evidence ledger.
2. **Radar.** Polls free feeds, scores social legitimacy (real X account vs a link to someone
   else's tweet, Telegram, website, community takeover, and a heavy penalty for links recycled
   from other tokens), optionally adds an AI narrative score, and queues the early profitable
   traders of qualifying tokens (1 h–7 d, ≥ $35k liquidity) for `score --with-queue`.
3. **CFO.** A full ledger in `data/treasury_ledger.json`. Whales earn 12% sizing (PF ≥ 1.5
   over ≥ 3 trades), sit at 10% by default, or drop to 5% after 2 straight losses. Every +20%
   of equity locks 50% of the gain into a reserve the bot can never spend.
4. **Self-improver.** 15/60 min after each exit it measures missed upside vs saved crash. Every
   10 trades or 12 h it proposes new values for 10 whitelisted parameters plus whale demotions,
   via AI or transparent rules. Proposals are clamped to hard bounds whose risky side is the
   mandate value, limited to a 25% move per round, and hot-reloaded without a restart.

AI routing: set `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` / `MODEL_ID` (or `LLM__*`) in `.env`.
The key and URL are always taken from the same source. Every AI layer is optional and
fail-safe, and none runs in the pre-buy path.

## Defaults (from the mandate, plus the review's additions)

| | Default | Env override |
|---|---|---|
| Wallet win rate | 55–82% | `SCORER__MIN_WIN_RATE`, `SCORER__MAX_WIN_RATE` |
| Avg & median hold | ≥ 300 s; blacklist if >30% first-sold < 120 s | `SCORER__MIN_MEDIAN_HOLD_S` |
| Typical trade | non-scratch median ROI ≥ +15%, or trimmed mean ≥ +12% with PF ≥ 1.6 | `SCORER__MIN_MEDIAN_ROI`, `SCORER__MIN_TRIMMED_MEAN_ROI` |
| Profit factor | ≥ 1.5 | `SCORER__MIN_PROFIT_FACTOR` |
| Copy replay | PF ≥ 1.35, expectancy > 0 after 2.5% entry + 1.2%/leg | `SCORER__REPLAY_ENTRY_PENALTY`, `SCORER__REPLAY_MIN_PROFIT_FACTOR` |
| Block-0 snipes | ≤ 30% of winners | `SCORER__MAX_SNIPER_RATIO` |
| Liquidity / mcap | ≥ $25k / ≥ $60k | `SAFETY__MIN_LIQUIDITY_USD`, `SAFETY__MIN_MARKET_CAP_USD` |
| Anti-chase | skip if our fill > whale + 12% | `SAFETY__MAX_CHASE_PCT` |
| Round-trip loss | ≤ 5% | `SAFETY__MAX_ROUNDTRIP_LOSS_PCT` |
| Re-entry | 1 per token per 24 h | `SAFETY__REENTRY_COOLDOWN_S` |
| Whale exit | sell 100% when whale holding −30% | `EXITS__WHALE_SELL_TRIGGER_FRAC` |
| Scale-out | 50% at +45% net, then the runner has a +15% floor and no timers | `EXITS__SCALE_OUT_PROFIT`, `EXITS__MOONBAG_FLOOR_PROFIT` |
| Stops | −22% hard; 15% trail after +25%; runner 25% (cluster 30%) | `EXITS__HARD_STOP_LOSS`, `EXITS__MOONBAG_TRAILING_STOP_PCT` |
| Time decay / max hold | 45 min without +15% / 4 h, unscaled positions only | `EXITS__TIME_DECAY_MINUTES`, `EXITS__MAX_HOLD_MINUTES` |
| Size / concurrency | 10% equity / 3 positions | `RISK__POSITION_SIZE_FRAC`, `RISK__MAX_OPEN_POSITIONS` |
| Per-leg cost cap | 1.2% (DEX fee + impact + network) | `RISK__MAX_LEG_COST_PCT` |
| Circuit breaker | −15% day → 24 h halt | `RISK__DAILY_LOSS_LIMIT_FRAC` |

---

## ملخص بالعربي

- **الوضع الافتراضي `SHADOW_PAPER`:** البوت يشتغل على بيانات حية بالكامل، لكن الصفقات ورقية. مش
  محتاج مفتاح خاص خالص، فمستحيل يتسرق.
- **التشغيل:** `doctor` بيتأكد إن الاتصال شغال. بعدها `harvest` يجمع المحافظ المرشحة، و`score`
  يختار منها، و`run` يبدأ النسخ، و`report` يعرض الأداء.
- **التحويل لـ LIVE:** البوت نفسه يرفض يشتغل LIVE لحد ما سجل الـ shadow يثبت إن فيه ميزة حقيقية:
  ٥٠ صفقة أو أكتر، وprofit factor ≥ ١٫٣، ومتوسط ربح ≥ ٢٪ للصفقة، وأقصى تراجع ≤ ٢٠٪.
- **محفظة منفصلة:** استخدم دايماً محفظة جديدة فيها ميزانية المخاطرة بس.
- **أمان الصفقات:** كل معاملة جاية من Jupiter بتتفحص وتتعمل لها محاكاة قبل التوقيع.
- **المكتبات:** ٥ مكتبات معروفة بس، ومقفولة بالـ hash.
