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
