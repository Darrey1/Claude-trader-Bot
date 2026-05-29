"""
Main episode runner.

Usage:
  python3 scripts/run_episode.py --config config/episode_01.yaml

The config must have start_date and end_date set.
Run scripts/backtest_scan.py first to select your window,
then update the config and run this script.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

from src.config_manager import load_config, finalize_config, get_run_dir
from src.market_data import fetch_all_assets, get_day_open, get_day_close, save_data_manifest
from src.indicators import compute_all_signals
from src.claude_agent import get_decision
from src.risk_validator import validate, save_decision
from src.portfolio_engine import (
    initial_state, mark_to_market, execute_trades,
    end_of_day_snapshot, save_portfolio_state,
)
from src.benchmark import compute_benchmarks, benchmark_summary_at_day


def date_range(start: str, days: int) -> list[str]:
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    return [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days + 1)]


def get_prices_for_date(data: dict, date: str, price_type: str = "close") -> dict:
    prices = {}
    for asset, df in data.items():
        dt = pd.Timestamp(date, tz="UTC")
        past = df[df.index <= dt]
        if len(past) > 0:
            prices[asset] = float(past.iloc[-1][price_type])
    return prices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/episode_01.yaml")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not found in environment. Add it to your .env file.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  CLAUDE TRADER — EPISODE RUN")
    print("=" * 60)

    cfg = load_config(args.config)
    ep = cfg["episode"]

    if not ep.get("start_date") or not ep.get("end_date"):
        print("ERROR: start_date and end_date must be set in the config.")
        print("Run scripts/backtest_scan.py first to select your window.")
        sys.exit(1)

    # generate run_id if this is the first run
    if not ep.get("run_id"):
        cfg = finalize_config(cfg, ep["start_date"], ep["end_date"], args.config)
        ep = cfg["episode"]

    print(f"\nRun ID:  {ep['run_id']}")
    print(f"Window:  {ep['start_date']} → {ep['end_date']} ({ep['duration_days']} days)")
    print(f"Capital: ${cfg['portfolio']['starting_capital']:,}")
    print(f"Assets:  {', '.join(cfg['assets']['universe'])}")
    print(f"Model:   {ep['model']}")
    print()

    run_dir = get_run_dir(cfg)
    print(f"Run directory: {run_dir}\n")

    # save a copy of the config into the run folder (immutable audit trail)
    import shutil
    shutil.copy(args.config, run_dir / "config_snapshot.yaml")

    # fetch all market data
    print("Step 1: Fetching market data from Binance...")
    data = fetch_all_assets(cfg)
    save_data_manifest(data, run_dir, cfg)
    print(f"  Data fetched for {len(data)} assets\n")

    # initialize portfolio
    portfolio = initial_state(cfg)
    days = date_range(ep["start_date"], ep["duration_days"])
    prior_decisions = []
    all_snapshots = []
    run_log = {
        "run_id": ep["run_id"],
        "config": cfg,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "days": [],
    }

    # Day 0 — initial state snapshot (no trading, just setup)
    print("Step 2: Day 0 — Initial setup snapshot")
    day0_prices = get_prices_for_date(data, days[0], "open")
    portfolio = mark_to_market(portfolio, day0_prices)
    benchmarks_d0 = compute_benchmarks(data, ep["start_date"], days[0], cfg["portfolio"]["starting_capital"], cfg)
    day0_signals = compute_all_signals(data, days[0], cfg)

    day0_snapshot = {
        "day": 0,
        "date": days[0],
        "total_value": round(portfolio["total_value"], 2),
        "cash": round(portfolio["cash"], 2),
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "max_drawdown": 0.0,
        "equity_curve": [portfolio["total_value"]],
        "positions": {},
        "trades_today": [],
        "benchmarks": benchmarks_d0,
        "decision": None,
        "market_signals": day0_signals,
        "note": "Starting position — 100% cash, no trades yet.",
    }
    all_snapshots.append(day0_snapshot)
    save_portfolio_state(portfolio, 0, run_dir)
    print(f"  Day 0 complete — Portfolio: ${portfolio['total_value']:,.2f} (all cash)\n")

    # Days 1–7
    print("Step 3: Running 7-day trading loop...\n")
    for day_num in range(1, ep["duration_days"] + 1):
        decision_date = days[day_num - 1]   # Claude decides on this date
        execution_date = days[day_num]       # trades execute at next day's open

        print(f"--- Day {day_num} | Decision: {decision_date} | Execution: {execution_date} ---")

        # compute signals as of decision date (anti-leakage: no future data)
        signals = compute_all_signals(data, decision_date, cfg)

        # compute benchmarks so far
        benchmarks = compute_benchmarks(
            data, ep["start_date"], decision_date,
            cfg["portfolio"]["starting_capital"], cfg
        )
        bench_summary = benchmark_summary_at_day(benchmarks)

        # Claude decision
        raw_decision = get_decision(
            day=day_num,
            decision_date=decision_date,
            portfolio_state=portfolio,
            signals=signals,
            prior_decisions=prior_decisions,
            benchmark_performance=bench_summary,
            cfg=cfg,
            run_dir=run_dir,
        )

        # risk validation
        validated_decision = validate(raw_decision, cfg)
        save_decision(validated_decision, day_num, run_dir)

        # get execution prices (next day open)
        exec_prices = {}
        for asset in cfg["assets"]["universe"]:
            p = get_day_open(data, asset, execution_date)
            if p:
                exec_prices[asset] = p

        # execute trades at next-day open
        portfolio = execute_trades(portfolio, validated_decision, exec_prices, cfg)

        # mark portfolio to market at EOD close prices — updates total_value so
        # next day's market packet shows correct portfolio value
        eod_prices = get_prices_for_date(data, execution_date, "close")
        portfolio = mark_to_market(portfolio, eod_prices)
        portfolio["equity_curve"].append(round(portfolio["total_value"], 2))

        snapshot = end_of_day_snapshot(portfolio, eod_prices, validated_decision, signals)
        snapshot["benchmarks"] = compute_benchmarks(
            data, ep["start_date"], execution_date,
            cfg["portfolio"]["starting_capital"], cfg
        )
        all_snapshots.append(snapshot)
        save_portfolio_state(portfolio, day_num, run_dir)

        prior_decisions.append({
            "day": day_num,
            "date": decision_date,
            "strategy": validated_decision.get("selected_strategy"),
            "action": validated_decision.get("portfolio_action"),
            "market_view": validated_decision.get("market_view"),
            "confidence": validated_decision.get("confidence"),
        })

        pnl = portfolio["total_value"] - cfg["portfolio"]["starting_capital"]
        pnl_pct = pnl / cfg["portfolio"]["starting_capital"] * 100
        print(f"  EOD Portfolio: ${portfolio['total_value']:,.2f} | PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)\n")

        run_log["days"].append({
            "day": day_num,
            "decision_date": decision_date,
            "execution_date": execution_date,
            "strategy": validated_decision.get("selected_strategy"),
            "portfolio_value": round(portfolio["total_value"], 2),
            "trades_count": len([t for t in portfolio["trades"] if t["day"] == day_num]),
            "validation_status": validated_decision.get("validation_report", {}).get("status"),
        })

    # save complete run log and all snapshots
    run_log["completed_at"] = datetime.now(timezone.utc).isoformat()
    run_log["final_value"] = round(portfolio["total_value"], 2)
    run_log["total_return_pct"] = round(
        (portfolio["total_value"] - cfg["portfolio"]["starting_capital"]) /
        cfg["portfolio"]["starting_capital"] * 100, 2
    )
    run_log["all_trades"] = portfolio["trades"]

    with open(run_dir / "run_log.json", "w") as f:
        json.dump(run_log, f, indent=2, default=str)

    with open(run_dir / "all_snapshots.json", "w") as f:
        json.dump(all_snapshots, f, indent=2, default=str)

    final_pnl = portfolio["total_value"] - cfg["portfolio"]["starting_capital"]
    print("=" * 60)
    print("  RUN COMPLETE")
    print("=" * 60)
    print(f"  Final portfolio: ${portfolio['total_value']:,.2f}")
    print(f"  Total PnL:       ${final_pnl:+,.2f} ({run_log['total_return_pct']:+.2f}%)")
    print(f"  Max drawdown:    {portfolio['max_drawdown']*100:.2f}%")
    print(f"  Total trades:    {len(portfolio['trades'])}")
    print(f"\n  Run logs saved to: {run_dir}")
    print(f"\n  Next step: streamlit run dashboard/app.py -- --run-id {ep['run_id']}")
    print()


if __name__ == "__main__":
    main()
