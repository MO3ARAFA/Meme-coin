# Pre-registration H2: smart-wallet copy trading persists out of time

Written BEFORE any wallet data was fetched or scored for this hypothesis. Changing anything below after
data has been looked at is allowed only by adding a dated amendment at the bottom; the original text stays.

## Hypothesis (falsifiable)
Wallets selected by `copybot.wallet_scorer` using ONLY transactions before time `T` earn a positive net
expectancy when their later buys (after `T`) are copied with the bot's latency, fee and entry-penalty model.
Selection skill must persist forward in time. It is not enough that selected wallets look good on the
period they were selected from.

## Why the previous design cannot test this
* `WalletScorer.signatures()` anchors its window to `time.time()`: there is no `as_of`. Selecting and
  evaluating on the same window is circular.
* `harvest` finds wallets by REALISED PROFIT in tokens that already ran. That is selection on the outcome.
* So H2 requires a walk-forward split by time, implemented before any scoring is run (see Procedure).

## Fixed before looking (no tuning)
* Scorer, safety, exit and risk settings: the defaults of the commit that contains this file. Recorded:
  `git rev-parse HEAD` at the time of the first run goes into `data/h2_run.json`.
* Selection window: 21 days ending at `T`. Evaluation window: the 14 days after `T`, never overlapping.
* Copy model: `SCORER__REPLAY_*` as shipped (latency-adjusted entry penalty, 1.2% fee per leg), exits
  from `decide_exit`. Wallets are selected ONCE at `T`; no re-selection during the evaluation window.
* Independence unit: a wallet *link group* (`link_groups`), not a trade. Bootstrap resamples link groups.

## Data
* Solana RPC with real history (a Helius-class key). The public endpoint is not sufficient.
* Holdout: the **last 7 days** of the evaluation window are frozen by date, not by outcome, and opened
  once. Development evaluation uses the first 7 days after `T`.
* Wallets seen in any earlier momentum analysis do not matter here (different data); but the momentum
  ledgers stay untouched.
* New ledger `data/trials_h2.json`, prior untracked trials = **0** (nothing has been tried on this data),
  incremented for every changed setting, including a different `T`.

## Decision rules
Reported as INCONCLUSIVE, not pass or fail, unless the minimum sample is met:
**>= 100 copied trades from >= 10 independent link groups in the development evaluation window.**

With the minimum met, the hypothesis is REJECTED if any of these fails:
1. Deflated Sharpe >= 0.95 (trials counted from `trials_h2.json`).
2. Bootstrap 95% CI lower bound of profit factor > 1.0 resampling link groups.
3. Removing the best 3 trades leaves total PnL > 0.
4. Net expectancy > 0 after fees in the development window.

If it survives, the holdout is opened once, then paper trading decides. Passing here is permission to
paper trade, nothing more.

## Stop rules
* REJECTED or INCONCLUSIVE after the planned windows: close H2. No re-selection with other thresholds,
  other `T` values or other filters unless each is a counted trial with a fresh evaluation window.
* No reading of evaluation-window results before the selection step is finished and logged.

## Known biases, stated up front
* Survivorship: wallets that stopped trading or were rugged out are invisible to the scorer.
* Hunters: wallets that dump on followers appear good until they are copied. Latency-adjusted replay and
  quarantine mitigate this and cannot remove it. Only paper trading sees it.
* Shared infrastructure: link groups catch same-operator wallets, not all coordinated actors.
* Any number from this study is an upper bound.

## Amendments
(none)
