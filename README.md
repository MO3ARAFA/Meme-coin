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
| `copybot/wallet_scorer.py` | **Module A**: trade-cycle reconstruction + copyability filters |
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
# put ~30 candidate wallets in seed_wallets.txt — see docs/SEED_WALLETS.md
python main.py score                   # -> approved_wallets.json (+ data/scorer_report.json)
python main.py check-token <MINT>      # see the safety gate's verdict on any token
python main.py run                     # shadow copy-trading; Ctrl-C to stop (state persists)
python main.py report                  # PnL, exits by trigger, PnL per wallet, LIVE readiness
```

Run the tests: `pip install -r requirements-dev.txt && pytest`. The suite has 47 tests,
including a full shadow lifecycle against fake markets and a real captured mainnet v1
transaction.

## Going LIVE (only after the shadow record earns it)

1. `python main.py report` must show **LIVE readiness: READY**: ≥50 closed trades,
   profit factor ≥1.3, expectancy ≥+2%/trade, max drawdown ≤20%.
2. Create a **new burner wallet** and fund it with your risk budget only:
   `solana-keygen new -o ~/.config/copybot/burner.json && chmod 600 ~/.config/copybot/burner.json`
3. In `.env`, set `EXECUTION_MODE=LIVE` and `KEYPAIR_PATH=~/.config/copybot/burner.json`.
4. `python main.py run`. Every Jupiter transaction is decoded, checked against an
   allow-list, and simulated before it is signed.

## Defaults (from the mandate, plus the review's additions)

| | Default | Env override |
|---|---|---|
| Wallet win rate | 55–82% | `SCORER__MIN_WIN_RATE`, `SCORER__MAX_WIN_RATE` |
| Avg & median hold | ≥ 300 s; blacklist if >30% first-sold < 120 s | `SCORER__MIN_MEDIAN_HOLD_S` |
| Median ROI / profit factor | ≥ +15% / ≥ 1.5 | `SCORER__MIN_MEDIAN_ROI`, `SCORER__MIN_PROFIT_FACTOR` |
| Block-0 snipes | ≤ 30% of winners | `SCORER__MAX_SNIPER_RATIO` |
| Liquidity / mcap | ≥ $25k / ≥ $60k | `SAFETY__MIN_LIQUIDITY_USD`, `SAFETY__MIN_MARKET_CAP_USD` |
| Anti-chase | skip if our fill > whale + 12% | `SAFETY__MAX_CHASE_PCT` |
| Round-trip loss | ≤ 5% | `SAFETY__MAX_ROUNDTRIP_LOSS_PCT` |
| Re-entry | 1 per token per 24 h | `SAFETY__REENTRY_COOLDOWN_S` |
| Whale exit | sell 100% when whale holding −30% | `EXITS__WHALE_SELL_TRIGGER_FRAC` |
| Scale-out | 50% at +45% net, then stop → +2% | `EXITS__SCALE_OUT_PROFIT` |
| Stops | −22% hard; 15% trailing after +25% | `EXITS__HARD_STOP_LOSS`, `EXITS__TRAILING_STOP_PCT` |
| Time decay | 45 min without +15% | `EXITS__TIME_DECAY_MINUTES` |
| Size / concurrency | 10% equity / 3 positions | `RISK__POSITION_SIZE_FRAC`, `RISK__MAX_OPEN_POSITIONS` |
| Per-leg cost cap | 1.2% (DEX fee + impact + network) | `RISK__MAX_LEG_COST_PCT` |
| Circuit breaker | −15% day → 24 h halt | `RISK__DAILY_LOSS_LIMIT_FRAC` |

---

## ملخص بالعربي

- **الوضع الافتراضي `SHADOW_PAPER`:** البوت يشتغل على بيانات حية بالكامل، لكن الصفقات ورقية. مش
  محتاج مفتاح خاص خالص، فمستحيل يتسرق.
- **التشغيل:** `doctor` بيتأكد إن الاتصال شغال. بعدها `score` يختار المحافظ، و`run` يبدأ النسخ،
  و`report` يعرض الأداء.
- **التحويل لـ LIVE:** البوت نفسه يرفض يشتغل LIVE لحد ما سجل الـ shadow يثبت إن فيه ميزة حقيقية:
  ٥٠ صفقة أو أكتر، وprofit factor ≥ ١٫٣، ومتوسط ربح ≥ ٢٪ للصفقة، وأقصى تراجع ≤ ٢٠٪.
- **محفظة منفصلة:** استخدم دايماً محفظة جديدة فيها ميزانية المخاطرة بس.
- **أمان الصفقات:** كل معاملة جاية من Jupiter بتتفحص وتتعمل لها محاكاة قبل التوقيع.
- **المكتبات:** ٥ مكتبات معروفة بس، ومقفولة بالـ hash.
