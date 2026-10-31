# nautilus_lab: backtest the momentum strategy on NautilusTrader

Optional research tooling. The bot (`copybot/`) does not import anything from here.

## What is real and what is approximated

| | |
|---|---|
| **Real (identical code)** | Entry rules: `copybot.momentum.detect_momentum`. Exits: `copybot.exit_manager.decide_exit` (hard stop, trail, +45% scale-out, moonbag floor, time decay, max hold). Anti-chase: `SafetyConfig.max_chase_pct`. |
| **Approximated** | Buy pressure. Candles have no buy/sell counts, so `--volume-spike` (recent volume vs. the 60-bar median) stands in for "25+ buys, 60% ratio". |
| **Missing** | The safety gate: honeypot, holder concentration, mint authorities, RugCheck. A backtest cannot tell you a token was a trap. |
| **Fees** | `--leg-cost` (default 1.2%/leg, the bot's own replay number) as a taker fee on both legs. |

## Execution timing: read this

Nautilus fills a market order at the *last price it has when the order is sent*, which is the **close of
the candle that triggered it**. That is zero latency. So decisions are made on a closed candle but the
order is sent `--delay-bars` candles later (default **1**, one minute: pessimistic for a bot that lands in
seconds) and fills at that candle's close. Entries are cancelled if price ran past
`max_chase_pct` meanwhile, exactly as the live gate would. Run with `--delay-bars 0` and `1` and compare:
an edge that disappears at one minute of latency was never copyable.

## Data hygiene (done for you, but know it exists)

* GeckoTerminal stamps candles with their **open** time; Nautilus wants **close** time. We shift by one
  bar, otherwise the strategy trades on a candle before it finished.
* GeckoTerminal omits minutes with no trades. Those are re-inserted as flat, zero-volume candles so a
  "5 minute window" is 5 minutes.
* Volume is converted from USD to tokens (`usd / close`), which is what Nautilus expects.

## Reading the output

Per token: candles, signals, trades, win rate, profit factor, expectancy, return, max drawdown. Then a
pooled summary and PASS/FAIL against `LiveGateConfig` (>= 50 trades, PF >= 1.3, expectancy >= +2%/trade,
drawdown <= 20%). Trades are independent per token; capital is not shared between tokens.

**Warnings that matter:** fewer than ~30 trades is noise; you chose the tokens after seeing which ones
moved (survivorship); rugged tokens often vanish from the data you can fetch. `--synthetic` generates
candles with breakouts injected, so it proves the plumbing and nothing else.

## Tuning

```bash
python -m nautilus_lab backtest --pool <POOL> --momentum min_return=0.05 min_buys_m5=0 --exit hard_stop_loss=0.15
```
Any `MomentumConfig` / `ExitConfig` field can be overridden. Tuning on the same data you evaluate on
overfits: split your tokens or your days.

## Robustness block (printed after every backtest)

* **Bootstrap 95% CI on profit factor**, twice: resampling trades, and resampling whole tokens (trades in
  one token share its regime, so the token version is the stricter one). If the interval includes 1.0, no
  edge can be claimed regardless of the point estimate.
* **Concentration**: share of PnL from the top 3 trades, and how many of the best trades must be removed
  for the total to reach zero. A small number is a red flag.
* **`--features-out file.csv`**: one row per trade with PnL and the market state at the signal
  (window return, volume ratio, volatility, prior-hour return, ...), plus Spearman correlations against the
  return. With few trades and many features, one will look predictive by chance. Treat a correlation as a
  hypothesis and test it on tokens you did not look at.

Order of work: widen the sample first (30+ tokens, 14-30 days, default thresholds), run the live shadow
record in parallel, and only then consider tuning or a train/test split.

## fetch-many: building a bigger sample

```bash
python -m nautilus_lab fetch-many --preflight-only --pools <POOL>   # 1 pool x 1 hour: is the endpoint still what we expect?
python -m nautilus_lab fetch-many --discover 30                    # queue the 30 most liquid pools and fetch
python -m nautilus_lab fetch-many                                  # same command again: resumes where it stopped
python -m nautilus_lab backtest --pool $(ls data/lab/*.csv ...)    # or --csv files; verified against data/manifest.json
```

* **Resolution split:** the first `--first-hours` (default 24) of each pool's usable history at 1 minute,
  the rest of `--days` (default 14) at `--coarse-minutes` (15). The backtest reads only the 1-minute file,
  so usable sample = pools x first-hours. 30 pools x 24 h is only 30 token-days; raise `--first-hours`
  (168 is about 12 calls/pool) if you want more minute data.
* **Pacing:** sliding 60 s window (`--max-per-min`, default 28). A 429 anyway backs off 5/10/20/60 s; if it
  persists the run saves state and exits **2**. Exit codes: 0 ok, 1 some pool failed / pre-flight failed,
  2 rate limited, 130 interrupted.
* **State:** `data/.fetch_state.json` (per pool: status, cursor, calls). Empty pools are marked after one
  attempt; failed pools are skipped (`--retry-failed` to try again).
* **Provenance:** `data/manifest.json` has the SHA-256 of every CSV; `backtest` refuses a changed file
  (`--ignore-manifest` to override) and prints a data fingerprint. `data/fetch.log` has the full story.

## Acceptance gates, trial counting and the frozen holdout

`backtest` ends with a block that can only **reject**:

| Gate | Meaning |
|---|---|
| Deflated Sharpe >= 0.95 | probability the true per-trade Sharpe beats what the best of N zero-skill tries would show. N = `data/trials.json`: 5 untracked manual tries plus every distinct configuration run on development data. Changing a threshold costs a trial. |
| PBO | Probability of Backtest Overfitting (CSCV). Needs per-slice results of >= 3 configurations; printed as "not computed" until you run a sweep. It is never filled with a made-up number. |
| CI lower bound > 1.0 | bootstrap, resampling trades and resampling tokens |
| Concentration | the result must not vanish when the best few trades are removed |
| Holdout | see below |

Passing earns a holdout look and paper trading. It is not approval to trade money.

**Holdout.** About 30% of pools, chosen by a hash of the address (not by results), are frozen in
`data/holdout.json`. Pools that were backtested before the freeze are listed as `contaminated` and can never
be holdout. Development runs exclude holdout pools automatically. `backtest --open-holdout` runs only them,
ignores `--ignore-manifest`, and works **once**; a second attempt is refused. With few pools the holdout is
a handful of tokens: it grows as new pools are fetched, and it is worth nothing statistically until it does.

**Why a gate is not enough on its own:** any metric used as a gate on the same data becomes the thing being
optimised. The only test that cannot be tuned against is data not yet seen: the holdout and live paper trading.
