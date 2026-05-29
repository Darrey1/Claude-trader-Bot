"""
Paper-Forward Daily Runner.

Run this script ONCE PER DAY for 7 days.

  Day 0 (today):    python3 scripts/run_paper_forward.py --config config/episode_01.yaml
  Day 1 (tomorrow): python3 scripts/run_paper_forward.py --config config/episode_01.yaml
  ...
  Day 7:            python3 scripts/run_paper_forward.py --config config/episode_01.yaml

The script detects which day it is automatically from saved state.
After Day 7, run: python3 scripts/generate_exports.py
Then:             streamlit run dashboard/app.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from src.config_manager import load_config, finalize_config, get_run_dir
from src.live_prices import fetch_current_prices, fetch_all_live_ohlcv
from src.indicators import compute_all_signals
from src.claude_agent import get_decision
from src.risk_validator import validate, save_decision
from src.portfolio_engine import (
    initial_state, mark_to_market, execute_trades,
    end_of_day_snapshot, save_portfolio_state,
)
from src.benchmark import compute_benchmarks, benchmark_summary_at_day


STATE_FILE = "forward_run_state.json"


def load_state(run_dir: Path) -> dict | None:
    path = run_dir / STATE_FILE
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def save_state(state: dict, run_dir: Path):
    path = run_dir / STATE_FILE
    with open(path, "w") as f:
        json.dump(state, f, indent=2, default=str)


def load_snapshots(run_dir: Path) -> list:
    path = run_dir / "all_snapshots.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def save_snapshots(snapshots: list, run_dir: Path):
    path = run_dir / "all_snapshots.json"
    with open(path, "w") as f:
        json.dump(snapshots, f, indent=2, default=str)


def load_run_log(run_dir: Path) -> dict:
    path = run_dir / "run_log.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_run_log(run_log: dict, run_dir: Path):
    path = run_dir / "run_log.json"
    with open(path, "w") as f:
        json.dump(run_log, f, indent=2, default=str)


def find_existing_run(cfg: dict) -> str | None:
    """Return run_id from config if a forward run is in progress."""
    return cfg["episode"].get("run_id")


def init_day_zero(cfg: dict, config_path: str) -> tuple[dict, Path]:
    """Initialize Day 0 — sets up the run, saves starting state."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date = (datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                .__class__.fromisoformat(today + "+00:00")).__class__
    # compute end date = start + duration_days
    from datetime import timedelta
    start_dt = datetime.strptime(today, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=cfg["episode"]["duration_days"])
    end_date = end_dt.strftime("%Y-%m-%d")

    cfg = finalize_config(cfg, today, end_date, config_path)
    run_dir = get_run_dir(cfg)
    shutil.copy(config_path, run_dir / "config_snapshot.yaml")

    portfolio = initial_state(cfg)
    universe = cfg["assets"]["universe"]

    print("Fetching current live prices for Day 0 baseline...")
    live_prices = fetch_current_prices(universe)
    print("Fetching recent OHLCV history for indicator warmup...")
    ohlcv_data = fetch_all_live_ohlcv(universe, cfg["assets"]["lookback_days"])

    # save benchmark entry prices (what each benchmark bought at on Day 0)
    bench_entry_prices = {asset: live_prices[asset] for asset in universe if asset in live_prices}

    state = {
        "run_id": cfg["episode"]["run_id"],
        "current_day": 0,
        "start_date": today,
        "portfolio": portfolio,
        "prior_decisions": [],
        "bench_entry_prices": bench_entry_prices,
        "all_trades": [],
    }

    # Day 0 snapshot
    portfolio = mark_to_market(portfolio, live_prices)
    day0_signals = compute_all_signals(ohlcv_data, today, cfg)
    day0_snapshot = {
        "day": 0,
        "date": today,
        "total_value": round(portfolio["total_value"], 2),
        "cash": round(portfolio["cash"], 2),
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "max_drawdown": 0.0,
        "equity_curve": [portfolio["total_value"]],
        "positions": {},
        "trades_today": [],
        "benchmarks": {
            "BTC_hold": {"value": cfg["portfolio"]["starting_capital"], "return_pct": 0.0},
            "ETH_hold": {"value": cfg["portfolio"]["starting_capital"], "return_pct": 0.0},
            "BTC_ETH_50_50": {"value": cfg["portfolio"]["starting_capital"], "return_pct": 0.0},
            "equal_weight_universe": {"value": cfg["portfolio"]["starting_capital"], "return_pct": 0.0},
            "cash": {"value": cfg["portfolio"]["starting_capital"], "return_pct": 0.0},
        },
        "decision": None,
        "market_signals": day0_signals,
        "note": "Starting position — 100% cash. Paper-forward run begins.",
        "live_prices_at_init": live_prices,
    }

    save_state(state, run_dir)
    save_snapshots([day0_snapshot], run_dir)

    run_log = {
        "run_id": cfg["episode"]["run_id"],
        "run_mode": "paper_forward",
        "config": cfg,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "days": [],
        "all_trades": [],
    }
    save_run_log(run_log, run_dir)
    save_portfolio_state(portfolio, 0, run_dir)

    return cfg, run_dir


def compute_benchmark_values(bench_entry_prices: dict, live_prices: dict,
                              starting_capital: float, cfg: dict) -> dict:
    """Compute benchmark portfolio values based on entry prices vs current prices."""
    fee_rate = (cfg["risk"]["trading_fee_bps"] + cfg["risk"]["slippage_bps"]) / 10000
    universe = cfg["assets"]["universe"]
    results = {}

    # BTC hold
    if "BTC" in bench_entry_prices and "BTC" in live_prices:
        invested = starting_capital * (1 - fee_rate)
        qty = invested / bench_entry_prices["BTC"]
        value = qty * live_prices["BTC"]
        results["BTC_hold"] = {"value": round(value, 2), "return_pct": round((value - starting_capital) / starting_capital, 4)}

    # ETH hold
    if "ETH" in bench_entry_prices and "ETH" in live_prices:
        invested = starting_capital * (1 - fee_rate)
        qty = invested / bench_entry_prices["ETH"]
        value = qty * live_prices["ETH"]
        results["ETH_hold"] = {"value": round(value, 2), "return_pct": round((value - starting_capital) / starting_capital, 4)}

    # 50/50 BTC+ETH
    if "BTC" in bench_entry_prices and "ETH" in bench_entry_prices:
        half = starting_capital / 2
        invested = half * (1 - fee_rate)
        btc_val = (invested / bench_entry_prices["BTC"]) * live_prices.get("BTC", bench_entry_prices["BTC"])
        eth_val = (invested / bench_entry_prices["ETH"]) * live_prices.get("ETH", bench_entry_prices["ETH"])
        value = btc_val + eth_val
        results["BTC_ETH_50_50"] = {"value": round(value, 2), "return_pct": round((value - starting_capital) / starting_capital, 4)}

    # equal weight
    per_asset = starting_capital / len(universe)
    eq_value = 0.0
    for asset in universe:
        if asset in bench_entry_prices and asset in live_prices:
            invested = per_asset * (1 - fee_rate)
            eq_value += (invested / bench_entry_prices[asset]) * live_prices[asset]
    results["equal_weight_universe"] = {"value": round(eq_value, 2), "return_pct": round((eq_value - starting_capital) / starting_capital, 4)}

    results["cash"] = {"value": starting_capital, "return_pct": 0.0}
    return results


def run_next_day(cfg: dict, run_dir: Path):
    """Advance the run by one day — fetch live prices, call Claude, execute trades."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not found. Add it to your .env file.")
        sys.exit(1)

    state = load_state(run_dir)
    snapshots = load_snapshots(run_dir)
    run_log = load_run_log(run_dir)

    current_day = state["current_day"]
    next_day = current_day + 1
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    duration = cfg["episode"]["duration_days"]

    if next_day > duration:
        print(f"\nRun is already complete ({duration} days done).")
        print("Run: python3 scripts/generate_exports.py")
        print("Then: streamlit run dashboard/app.py")
        return

    print(f"\n{'='*60}")
    print(f"  PAPER-FORWARD | Day {next_day} of {duration} | {today}")
    print(f"{'='*60}\n")

    universe = cfg["assets"]["universe"]
    portfolio = state["portfolio"]

    # fetch live prices RIGHT NOW
    print("Fetching live prices from Binance...")
    live_prices = fetch_current_prices(universe)
    for asset, price in live_prices.items():
        print(f"  {asset}: ${price:,.4f}")

    # fetch recent OHLCV for indicators (up to yesterday's close only)
    print("\nFetching OHLCV history for indicators...")
    ohlcv_data = fetch_all_live_ohlcv(universe, cfg["assets"]["lookback_days"])

    # compute indicators as of yesterday (anti-leakage: don't use today's in-progress candle)
    from datetime import timedelta
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    signals = compute_all_signals(ohlcv_data, yesterday, cfg)

    # compute benchmark performance vs Day 0 entry prices
    bench_entry_prices = state["bench_entry_prices"]
    benchmarks = compute_benchmark_values(
        bench_entry_prices, live_prices,
        cfg["portfolio"]["starting_capital"], cfg
    )
    bench_summary = {k: round(v["return_pct"] * 100, 2) for k, v in benchmarks.items()}

    # mark portfolio to market at current live prices
    portfolio = mark_to_market(portfolio, live_prices)

    # call Claude
    print(f"\nCalling Claude for Day {next_day}...")
    raw_decision = get_decision(
        day=next_day,
        decision_date=today,
        portfolio_state=portfolio,
        signals=signals,
        prior_decisions=state["prior_decisions"],
        benchmark_performance=bench_summary,
        cfg=cfg,
        run_dir=run_dir,
    )

    # risk validation
    validated_decision = validate(raw_decision, cfg)
    save_decision(validated_decision, next_day, run_dir)

    # execute trades at current live prices
    print("\nExecuting paper trades at current prices...")
    portfolio = execute_trades(portfolio, validated_decision, live_prices, cfg)

    # mark to market again after trades (prices haven't changed, but positions have)
    portfolio = mark_to_market(portfolio, live_prices)
    portfolio["equity_curve"].append(round(portfolio["total_value"], 2))

    # end-of-day snapshot
    snapshot = end_of_day_snapshot(portfolio, live_prices, validated_decision, signals)
    snapshot["benchmarks"] = benchmarks
    snapshot["live_prices"] = live_prices
    snapshots.append(snapshot)
    save_snapshots(snapshots, run_dir)
    save_portfolio_state(portfolio, next_day, run_dir)

    # update state
    state["current_day"] = next_day
    state["portfolio"] = portfolio
    state["all_trades"] = portfolio["trades"]
    state["prior_decisions"].append({
        "day": next_day,
        "date": today,
        "strategy": validated_decision.get("selected_strategy"),
        "action": validated_decision.get("portfolio_action"),
        "market_view": validated_decision.get("market_view"),
        "confidence": validated_decision.get("confidence"),
    })
    save_state(state, run_dir)

    # update run log
    pnl = portfolio["total_value"] - cfg["portfolio"]["starting_capital"]
    run_log.setdefault("days", []).append({
        "day": next_day,
        "date": today,
        "strategy": validated_decision.get("selected_strategy"),
        "portfolio_value": round(portfolio["total_value"], 2),
        "trades_count": len([t for t in portfolio["trades"] if t["day"] == next_day]),
        "validation_status": validated_decision.get("validation_report", {}).get("status"),
    })
    run_log["all_trades"] = portfolio["trades"]

    if next_day == duration:
        run_log["completed_at"] = datetime.now(timezone.utc).isoformat()
        run_log["final_value"] = round(portfolio["total_value"], 2)
        run_log["total_return_pct"] = round(pnl / cfg["portfolio"]["starting_capital"] * 100, 2)

    save_run_log(run_log, run_dir)

    pnl_pct = pnl / cfg["portfolio"]["starting_capital"] * 100
    print(f"\n{'='*60}")
    print(f"  Day {next_day} Complete")
    print(f"  Portfolio: ${portfolio['total_value']:,.2f} | PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)")
    print(f"  Max Drawdown: {portfolio['max_drawdown']*100:.2f}%")
    print(f"{'='*60}")

    days_remaining = duration - next_day
    if days_remaining > 0:
        print(f"\n  {days_remaining} day(s) remaining.")
        print(f"  Run again tomorrow: python3 scripts/run_paper_forward.py --config config/episode_01.yaml")
    else:
        print(f"\n  Run complete! Generate your filming package:")
        print(f"    python3 scripts/generate_exports.py")
        print(f"    streamlit run dashboard/app.py")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/episode_01.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)

    existing_run_id = find_existing_run(cfg)

    if existing_run_id:
        # resume existing run
        run_dir = Path("runs") / existing_run_id
        if not run_dir.exists():
            print(f"ERROR: Run directory not found: {run_dir}")
            sys.exit(1)
        state = load_state(run_dir)
        if state is None:
            print("ERROR: Could not load run state. Run may be corrupted.")
            sys.exit(1)
        print(f"Resuming run: {existing_run_id} | Currently on Day {state['current_day']}")
        run_next_day(cfg, run_dir)
    else:
        # first time — initialize Day 0
        print("\n=== INITIALIZING PAPER-FORWARD RUN ===")
        print(f"Starting capital: ${cfg['portfolio']['starting_capital']:,}")
        print(f"Duration: {cfg['episode']['duration_days']} days")
        print(f"Model: {cfg['episode']['model']}\n")
        cfg, run_dir = init_day_zero(cfg, args.config)
        print(f"\nDay 0 initialized. Run ID: {cfg['episode']['run_id']}")
        print(f"Run directory: {run_dir}")
        print(f"\nNow run this command each day for {cfg['episode']['duration_days']} days:")
        print(f"  python3 scripts/run_paper_forward.py --config config/episode_01.yaml")
        print(f"\nYou can check the dashboard anytime:")
        print(f"  streamlit run dashboard/app.py")


if __name__ == "__main__":
    main()
