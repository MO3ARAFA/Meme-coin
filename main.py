#!/usr/bin/env python3
"""copybot CLI.

  python main.py doctor                 # check config + connectivity (RPC, WS, Jupiter, DexScreener)
  python main.py score                  # Module A: seed_wallets.txt -> approved_wallets.json
  python main.py check-token <MINT>     # run the Module B safety gate on any token, right now
  python main.py run                    # copy-trade approved wallets (SHADOW_PAPER by default)
  python main.py report                 # shadow PnL stats + LIVE-readiness gate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time

from copybot.config import ExecutionMode, Settings, load_settings
from copybot.constants import LAMPORTS_PER_SOL, USDC_MINT, WSOL_MINT
from copybot.http_utils import make_client
from copybot.report import build_report, format_report
from copybot.state import TradeJournal

log = logging.getLogger("copybot")


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def cmd_doctor(s: Settings) -> int:
    from copybot.dexscreener import DexScreenerClient
    from copybot.jupiter import JupiterClient
    from copybot.solana_rpc import SolanaRpc

    ok = True
    print(f"mode           {s.execution_mode.value}")
    print(f"rpc            {s.rpc_url.split('?')[0]}")
    print(f"ws             {s.ws_url.split('?')[0]}")
    print(f"jupiter        {s.jupiter_base_url}")
    async with make_client() as client:
        rpc = SolanaRpc(client, s.rpc_url, s.rpc_rps)
        try:
            t0 = time.perf_counter()
            slot = await rpc.get_slot()
            print(f"[ok] RPC slot {slot} ({(time.perf_counter() - t0) * 1000:.0f}ms)")
        except Exception as exc:
            ok = False
            print(f"[FAIL] RPC: {exc}")
        try:
            import websockets

            async with websockets.connect(s.ws_url, open_timeout=8) as ws:
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "slotSubscribe"}))
                await asyncio.wait_for(ws.recv(), 8)
            print("[ok] WebSocket subscribe")
        except Exception as exc:
            print(f"[warn] WebSocket: {exc} — set LISTENER_MODE=poll or use a provider with WS")
        jup = JupiterClient(client, s.jupiter_base_url, s.jupiter_api_key, s.jupiter_rps)
        try:
            t0 = time.perf_counter()
            q = await jup.quote(WSOL_MINT, USDC_MINT, LAMPORTS_PER_SOL, 50)
            print(f"[ok] Jupiter quote: 1 SOL = {q.out_amount / 1e6:.2f} USDC ({(time.perf_counter() - t0) * 1000:.0f}ms)")
        except Exception as exc:
            ok = False
            print(f"[FAIL] Jupiter: {exc}")
        dex = DexScreenerClient(client, s.dexscreener_base_url, s.dexscreener_rps)
        try:
            pair = await dex.best_pair(WSOL_MINT)
            print(f"[ok] DexScreener ({pair.dex_id if pair else 'no pair'})")
        except Exception as exc:
            ok = False
            print(f"[FAIL] DexScreener: {exc}")
    print("approved wallets:", "present" if s.approved_wallets_path.exists() else "missing (run `score`)")
    print("seed wallets:   ", "present" if s.seed_wallets_path.exists() else "missing (see docs/SEED_WALLETS.md)")
    return 0 if ok else 1


async def cmd_score(s: Settings) -> int:
    from copybot.dexscreener import DexScreenerClient
    from copybot.jupiter import JupiterClient
    from copybot.solana_rpc import SolanaRpc
    from copybot.wallet_scorer import run_scorer

    async with make_client() as client:
        rpc = SolanaRpc(client, s.rpc_url, s.rpc_rps)
        dex = DexScreenerClient(client, s.dexscreener_base_url, s.dexscreener_rps)
        jup = JupiterClient(client, s.jupiter_base_url, s.jupiter_api_key, s.jupiter_rps)
        results = await run_scorer(s, rpc, dex, jup)
    return 0 if any(m.passed for m in results) else 2


async def cmd_check_token(s: Settings, mint: str, size_sol: float) -> int:
    """Gate a token as if a whale had just bought it at the current price."""
    from copybot.copy_engine import CopyEngine
    from copybot.tx_parser import Side, SwapEvent

    s.execution_mode = ExecutionMode.SHADOW_PAPER  # never needs a key
    async with make_client() as client:
        engine = CopyEngine(s, client)
        lamports = int(size_sol * LAMPORTS_PER_SOL)
        q = await engine.jupiter.quote(WSOL_MINT, mint, lamports, s.risk.entry_slippage_bps)
        ev = SwapEvent(
            signature="manual-check", slot=0, block_time=int(time.time()), wallet="manual", side=Side.BUY, mint=mint,
            token_amount_raw=q.out_amount, decimals=0, quote_mint=WSOL_MINT, quote_amount_raw=q.in_amount,
            token_balance_before_raw=0, token_balance_after_raw=q.out_amount, fee_lamports=0,
        )
        # Bypass the whale-size precheck: this is a manual probe at our own size.
        s.safety.min_whale_buy_sol = 0.0
        res = await engine.gate.evaluate(ev, lamports)
    print(res.summary())
    if res.mint_info:
        print(f"token program: {res.mint_info.program}  extensions: {list(res.mint_info.extensions) or 'none'}")
    if res.buy_quote:
        print(f"route: {' -> '.join(res.buy_quote.route_labels)}  impact {res.buy_quote.price_impact_pct:.3%}")
    if res.fee_budget and res.fee_budget.allowed:
        print(f"priority fee budget: {res.fee_budget.max_priority_lamports} lamports "
              f"(DEX fee+impact {res.fee_budget.dex_cost_frac:.2%}/leg)")
    return 0 if res.passed else 3


async def cmd_run(s: Settings, force_live: bool) -> int:
    from copybot.copy_engine import CopyEngine

    signer = None
    if s.is_live:
        rep = build_report(TradeJournal(s.data_dir / "shadow_trades.csv").read(), s.shadow_starting_sol, s.live_gate)
        if not rep.live_ready and not force_live:
            print(format_report(rep))
            print("\nRefusing to start LIVE: the shadow record has not proven an edge yet.")
            return 4
        from copybot.wallet_vault import load_signer

        signer = load_signer()
        log.warning("LIVE MODE — signing as %s. Use a dedicated burner wallet holding only your risk budget.", signer.pubkey)
    async with make_client() as client:
        engine = CopyEngine(s, client, signer)
        try:
            await engine.run()
        finally:
            engine.save()
    return 0


def cmd_report(s: Settings) -> int:
    rows = TradeJournal(s.trades_csv).read()
    print(format_report(build_report(rows, s.shadow_starting_sol, s.live_gate)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Anti-exit-liquidity Solana copy-trading bot")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("score")
    ct = sub.add_parser("check-token")
    ct.add_argument("mint")
    ct.add_argument("--size-sol", type=float, default=0.1)
    run = sub.add_parser("run")
    run.add_argument(
        "--i-accept-unproven-live-risk",
        dest="force_live",
        action="store_true",
        help="start LIVE even though the shadow record fails the readiness gate (not recommended)",
    )
    sub.add_parser("report")
    args = ap.parse_args(argv)
    setup_logging(args.verbose)
    s = load_settings()
    try:
        if args.cmd == "doctor":
            return asyncio.run(cmd_doctor(s))
        if args.cmd == "score":
            return asyncio.run(cmd_score(s))
        if args.cmd == "check-token":
            return asyncio.run(cmd_check_token(s, args.mint, args.size_sol))
        if args.cmd == "run":
            return asyncio.run(cmd_run(s, args.force_live))
        if args.cmd == "report":
            return cmd_report(s)
    except KeyboardInterrupt:
        log.info("stopped")
        return 130
    return 1


if __name__ == "__main__":
    sys.exit(main())
