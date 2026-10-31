"""python -m nautilus_lab {pools,fetch,backtest} ..."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from copybot.config import MomentumConfig

from .data import fetch_ohlcv, load_csv, save_csv, synthetic_ohlcv

DATA_DIR = Path("data/lab")


def _kv(items: list[str] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in items or []:
        key, _, value = item.partition("=")
        if not value:
            raise SystemExit(f"expected name=value, got {item!r}")
        out[key.strip()] = float(value)
    return out


def cmd_pools() -> int:
    import httpx

    from copybot.config import load_settings
    from copybot.harvester import discover_tokens

    async def go():
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await discover_tokens(client, load_settings())

    tokens = asyncio.run(go())
    print(f"{'symbol':<12}{'pool':<46}{'liq $':>12}{'vol24h $':>14}{'age d':>7}")
    for t in tokens:
        print(f"{t.symbol:<12}{t.pool:<46}{t.liquidity_usd:>12,.0f}{t.volume_h24_usd:>14,.0f}{t.age_days:>7.1f}")
    print("\nnext: python -m nautilus_lab fetch <pool> --days 3")
    return 0 if tokens else 2


def cmd_fetch(pool: str, days: float, out: Path | None) -> int:
    df = fetch_ohlcv(pool, days)
    path = out or DATA_DIR / f"{pool}.csv"
    save_csv(df, path)
    print(f"{len(df)} one-minute candles ({df.index[0]} .. {df.index[-1]}) -> {path}")
    return 0


def cmd_backtest(args) -> int:
    from .backtest import run_backtest, summarize

    unknown = set(_kv(args.momentum)) - set(MomentumConfig.model_fields)
    if unknown:
        raise SystemExit(f"unknown momentum parameter(s): {sorted(unknown)}")
    datasets: list[tuple[str, object]] = []
    if args.synthetic:
        datasets.append(("SYNTH", synthetic_ohlcv(args.seed)))
    for f in args.csv or []:
        datasets.append((Path(f).stem[:8], load_csv(Path(f))))
    for pool in args.pool or []:
        path = DATA_DIR / f"{pool}.csv"
        df = load_csv(path) if path.exists() else fetch_ohlcv(pool, args.days)
        if not path.exists():
            save_csv(df, path)
        datasets.append((pool[:8], df))
    if not datasets:
        raise SystemExit("give --synthetic, --csv FILE... or --pool ADDRESS...")

    all_trades = []
    by_token: dict[str, list] = {}
    for name, df in datasets:
        r = run_backtest(
            df, name, capital=args.capital, leg_cost=args.leg_cost, size_frac=args.size_frac,
            min_volume_spike=args.volume_spike, delay_bars=args.delay_bars, momentum=_kv(args.momentum), exits=_kv(args.exit),
        )
        s = summarize(r.trades, args.capital)
        print(f"{name:<10} {r.candles:>6} candles  {r.signals:>3} signals  {s.trades:>3} trades  "
              f"win {s.win_rate:>4.0%}  PF {s.profit_factor:>5.2f}  exp {s.expectancy:+.1%}  "
              f"ret {s.total_return:+.1%}  mdd {s.max_drawdown:.1%}")
        if abs(sum(t.pnl for t in r.trades) - r.account_pnl) > 0.05 * max(1, r.still_open + len(r.trades)):
            print(f"  WARNING: trade PnL {sum(t.pnl for t in r.trades):+.2f} != account change {r.account_pnl:+.2f}")
        if r.chase_aborts:
            print(f"  note: {r.chase_aborts} entr(y/ies) cancelled: price ran past the signal during the delay")
        if r.still_open:
            print(f"  note: {r.still_open} position(s) still open at the end of the data (excluded)")
        all_trades += r.trades
        by_token[name] = r.trades

    total = summarize(all_trades, args.capital)
    print("\npooled (trades are independent per token; capital is not shared):")
    print(f"  {total.trades} trades, win rate {total.win_rate:.0%}, profit factor {total.profit_factor:.2f}, "
          f"expectancy {total.expectancy:+.2%}/trade, avg win {total.avg_win:+.1%}, avg loss {total.avg_loss:+.1%}")
    print("  LIVE-readiness yardsticks (same as `python main.py report`):")
    for line in total.verdict:
        print("   ", line)
    _print_robustness(all_trades, by_token, args.capital, args.features_out)
    if args.synthetic:
        print("\n  SYNTHETIC data: this only proves the plumbing runs. It says NOTHING about profitability.")
    elif total.trades < 30:
        print("\n  Fewer than 30 trades: too few to conclude anything. Add more tokens / longer history.")
    print("  Backtests overstate: no honeypot/rug filter, tokens picked after the fact (survivorship), fills at candle closes.")
    return 0


def _print_robustness(trades, by_token, capital, features_out) -> None:
    """Memecoin payoffs are a few huge winners among many small losers. Say how much of the result
    rests on luck, so one lucky token can't pass for an edge."""
    from .backtest import summarize
    from .stats import bootstrap_pf, bootstrap_pf_by_group, concentration

    if not trades:
        return
    pnls = [t.pnl for t in trades]
    print("  robustness (read before the PASS/FAIL lines above):")
    for b in (bootstrap_pf(pnls), bootstrap_pf_by_group({k: [t.pnl for t in v] for k, v in by_token.items()})):
        if b:
            print("    bootstrap:", b.line())
    c = concentration(pnls)
    if c.total > 0:
        print(f"    top 3 trades = ${c.top3:,.0f} = {c.top3_share_of_total:.0%} of total PnL, "
              f"{c.top3_share_of_gross_profit:.0%} of gross profit")
        print(f"    removing the best {c.drop_to_zero} of {c.n} trades makes total PnL <= 0"
              + ("   <-- RED FLAG: the result rests on a handful of trades" if c.red_flag else ""))
    else:
        print(f"    total PnL ${c.total:,.0f}: nothing to concentrate")
    if len(by_token) > 1:
        best = max(by_token, key=lambda k: sum(t.pnl for t in by_token[k]))
        rest = summarize([t for k, ts in by_token.items() if k != best for t in ts], capital)
        print(f"    without the best token ({best}): {rest.trades} trades, profit factor "
              f"{rest.profit_factor:.2f}, expectancy {rest.expectancy:+.2%}/trade")
    _features(trades, features_out)


def _features(trades, out) -> None:
    import pandas as pd

    rows = [{"symbol": t.symbol, "opened": t.opened, "ret": t.ret, "pnl": t.pnl, **t.features} for t in trades]
    df = pd.DataFrame(rows)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        print(f"    per-trade features -> {out}")
    cols = [c for c in df.columns if c not in {"symbol", "opened", "ret", "pnl"} and df[c].notna().sum() >= 10]
    if len(df) >= 20 and cols:
        corr = df[cols + ["ret"]].corr(method="spearman")["ret"].drop("ret").sort_values(key=abs, ascending=False)
        shown = ", ".join(f"{k} {v:+.2f}" for k, v in corr.head(4).items())
        print(f"    feature vs return (Spearman, n={len(df)}): {shown}")
        print(f"    (|rho| < {2 / len(df) ** 0.5:.2f} is indistinguishable from zero, and with {len(cols)} features "
              "tried, one will look good by chance: confirm on NEW tokens before filtering on it)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nautilus_lab", description="Backtest the momentum strategy on NautilusTrader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pools", help="list liquid memecoin pools worth fetching")
    f = sub.add_parser("fetch", help="download 1-minute candles for a pool (GeckoTerminal)")
    f.add_argument("pool")
    f.add_argument("--days", type=float, default=3.0)
    f.add_argument("--out", type=Path)
    b = sub.add_parser("backtest")
    b.add_argument("--synthetic", action="store_true", help="generated candles: plumbing check only")
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--csv", nargs="+")
    b.add_argument("--pool", nargs="+", help="pool addresses (cached under data/lab/, fetched if missing)")
    b.add_argument("--days", type=float, default=3.0)
    b.add_argument("--capital", type=float, default=1000.0)
    b.add_argument("--size-frac", type=float, default=0.05)
    b.add_argument("--leg-cost", type=float, default=0.012, help="fee+impact per leg (the bot's own replay uses 1.2%%)")
    b.add_argument("--delay-bars", type=int, default=1, help="candles from decision to order (0 = optimistic zero latency)")
    b.add_argument("--features-out", help="write one row per trade (PnL + market state at the signal) to this CSV")
    b.add_argument("--volume-spike", type=float, default=1.5, help="buy-pressure proxy; 0 disables")
    b.add_argument("--momentum", nargs="*", metavar="K=V", help="override MomentumConfig, e.g. min_return=0.1")
    b.add_argument("--exit", nargs="*", metavar="K=V", help="override ExitConfig, e.g. hard_stop_loss=0.15")
    args = ap.parse_args(argv)
    if args.cmd == "pools":
        return cmd_pools()
    if args.cmd == "fetch":
        return cmd_fetch(args.pool, args.days, args.out)
    return cmd_backtest(args)


if __name__ == "__main__":
    sys.exit(main())
