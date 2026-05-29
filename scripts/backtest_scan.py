"""
Backtest Scanner — finds the most narratively interesting 7-day window.

Scans candidate windows and scores each on:
  - Volatility (price swings)
  - Narrative arc (trend reversal, drawdown, recovery)
  - Strategy signal clarity (RSI extremes, trend crossovers)
  - Benchmark divergence (Claude strategy vs buy-and-hold difference)

Run:  python3 scripts/backtest_scan.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time
import json

from src.indicators import compute_asset_signals


CANDIDATE_WINDOWS = [
    ("2026-01-05", "2026-01-11"),   # New year open
    ("2026-02-02", "2026-02-08"),   # February market regime
    ("2026-03-02", "2026-03-08"),   # Q1 volatility
    ("2026-04-06", "2026-04-12"),   # Q2 open
    ("2026-05-04", "2026-05-10"),   # May momentum
    ("2026-05-11", "2026-05-17"),   # Recent window
]

ASSETS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "LINK", "AVAX"]
SYMBOL_MAP = {
    "BTC": "BTC/USDT", "ETH": "ETH/USDT", "SOL": "SOL/USDT", "BNB": "BNB/USDT",
    "XRP": "XRP/USDT", "DOGE": "DOGE/USDT", "LINK": "LINK/USDT", "AVAX": "AVAX/USDT",
}


def fetch_window(asset: str, start: str, end: str, exchange) -> pd.DataFrame:
    symbol = SYMBOL_MAP[asset]
    since_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc) - timedelta(days=60)
    since_ms = int(since_dt.timestamp() * 1000)
    end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=2)

    candles = []
    current = since_ms
    while True:
        batch = exchange.fetch_ohlcv(symbol, "1d", since=current, limit=500)
        if not batch:
            break
        candles.extend(batch)
        if batch[-1][0] >= int(end_dt.timestamp() * 1000):
            break
        current = batch[-1][0] + 86400000
        time.sleep(0.15)

    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[df["volume"] > 0]
    df = df[~df.index.duplicated(keep="first")]
    return df


def score_window(start: str, end: str, data: dict) -> dict:
    """Score a candidate window for narrative value."""
    start_dt = pd.Timestamp(start, tz="UTC")
    end_dt = pd.Timestamp(end, tz="UTC")

    window_dates = pd.date_range(start=start_dt, end=end_dt, freq="D", tz="UTC")

    # compute daily BTC returns within the window
    btc = data["BTC"]
    btc_window = btc[(btc.index >= start_dt) & (btc.index <= end_dt)]

    if len(btc_window) < 5:
        return {"score": 0, "reason": "insufficient data"}

    daily_returns = btc_window["close"].pct_change().dropna()
    total_return = (btc_window["close"].iloc[-1] / btc_window["close"].iloc[0]) - 1
    max_single_day_move = daily_returns.abs().max()
    volatility = daily_returns.std()
    # direction changes = number of times return sign flips
    sign_changes = (np.diff(np.sign(daily_returns.values)) != 0).sum()

    # check for a big down day followed by recovery (drama arc)
    has_big_crash = any(daily_returns < -0.04)
    has_recovery = total_return > -0.02 if has_big_crash else False

    # multi-asset dispersion (altcoins behaving differently from BTC)
    asset_returns = {}
    for asset in ASSETS:
        df = data[asset]
        w = df[(df.index >= start_dt) & (df.index <= end_dt)]
        if len(w) >= 5:
            asset_returns[asset] = (w["close"].iloc[-1] / w["close"].iloc[0]) - 1

    if len(asset_returns) >= 4:
        returns_arr = list(asset_returns.values())
        dispersion = np.std(returns_arr)
        best_asset = max(asset_returns, key=asset_returns.get)
        worst_asset = min(asset_returns, key=asset_returns.get)
        spread = asset_returns[best_asset] - asset_returns[worst_asset]
    else:
        dispersion = 0
        best_asset = "BTC"
        worst_asset = "BTC"
        spread = 0

    # narrative scoring
    score = 0
    score += min(max_single_day_move * 200, 30)    # big single day moves (max 30)
    score += min(volatility * 500, 20)              # overall volatility (max 20)
    score += min(sign_changes * 5, 20)              # direction changes (max 20)
    score += min(dispersion * 200, 15)              # asset dispersion (max 15)
    score += 15 if has_big_crash else 0             # big crash event
    score += 10 if has_recovery else 0              # recovery arc

    key_moments = []
    for date, ret in daily_returns.items():
        if abs(ret) > 0.04:
            direction = "CRASH" if ret < 0 else "PUMP"
            key_moments.append(f"{date.date()} — {direction} {ret*100:.1f}%")

    return {
        "start": start,
        "end": end,
        "score": round(score, 1),
        "btc_total_return": round(total_return * 100, 2),
        "max_single_day_move_pct": round(max_single_day_move * 100, 2),
        "direction_changes": int(sign_changes),
        "asset_dispersion": round(dispersion * 100, 2),
        "best_asset": best_asset,
        "best_asset_return_pct": round(asset_returns.get(best_asset, 0) * 100, 2),
        "worst_asset": worst_asset,
        "worst_asset_return_pct": round(asset_returns.get(worst_asset, 0) * 100, 2),
        "has_big_crash": has_big_crash,
        "has_recovery": has_recovery,
        "key_moments": key_moments,
        "all_asset_returns": {k: round(v * 100, 2) for k, v in asset_returns.items()},
    }


def main():
    print("\n=== CLAUDE TRADER — BACKTEST WINDOW SCANNER ===\n")
    exchange = ccxt.binance({"enableRateLimit": True})

    # fetch all data for all candidate windows (batch by asset to minimize API calls)
    print("Fetching market data for all candidate windows...\n")

    # use the broadest date range needed
    all_start = min(w[0] for w in CANDIDATE_WINDOWS)
    all_end = max(w[1] for w in CANDIDATE_WINDOWS)

    all_data = {}
    for asset in ASSETS:
        print(f"  Downloading {asset}...")
        all_data[asset] = fetch_window(asset, all_start, all_end, exchange)

    print("\nScoring candidate windows...\n")
    results = []
    for start, end in CANDIDATE_WINDOWS:
        # slice data to this window
        window_data = {}
        for asset in ASSETS:
            df = all_data[asset]
            start_dt = pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=60)
            window_data[asset] = df[df.index >= start_dt].copy()
        result = score_window(start, end, window_data)
        results.append(result)

    results.sort(key=lambda x: x["score"], reverse=True)

    print("=" * 70)
    print(f"{'RANK':<5} {'WINDOW':<25} {'SCORE':<8} {'BTC%':<10} {'NOTES'}")
    print("=" * 70)
    for i, r in enumerate(results):
        window_str = f"{r['start']} → {r['end']}"
        notes = []
        if r["has_big_crash"]:
            notes.append("CRASH")
        if r["has_recovery"]:
            notes.append("RECOVERY")
        if r["asset_dispersion"] > 5:
            notes.append("HIGH DISPERSION")
        notes_str = " | ".join(notes) if notes else "-"
        print(f"  #{i+1}   {window_str:<25} {r['score']:<8} {r['btc_total_return']:+.1f}%     {notes_str}")

    print("\n")
    print("=== DETAILED REPORT — TOP 3 WINDOWS ===\n")
    for r in results[:3]:
        print(f"Window: {r['start']} → {r['end']}  |  Score: {r['score']}")
        print(f"  BTC return: {r['btc_total_return']:+.2f}%  |  Max single-day move: {r['max_single_day_move_pct']:.2f}%")
        print(f"  Direction changes: {r['direction_changes']}  |  Asset dispersion: {r['asset_dispersion']:.2f}%")
        print(f"  Best: {r['best_asset']} {r['best_asset_return_pct']:+.2f}%  |  Worst: {r['worst_asset']} {r['worst_asset_return_pct']:+.2f}%")
        print(f"  Asset returns: {r['all_asset_returns']}")
        if r["key_moments"]:
            print(f"  Key moments:")
            for m in r["key_moments"]:
                print(f"    {m}")
        print()

    # save full report
    os.makedirs("runs", exist_ok=True)
    report_path = "runs/backtest_scan_report.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Full report saved to: {report_path}")

    winner = results[0]
    print(f"\n>>> RECOMMENDED WINDOW: {winner['start']} → {winner['end']} (Score: {winner['score']}) <<<")
    print(f"    Update config/episode_01.yaml with:")
    print(f"      start_date: \"{winner['start']}\"")
    print(f"      end_date:   \"{winner['end']}\"")
    print("\nReview the full report, then confirm or choose a different window.\n")


if __name__ == "__main__":
    main()
