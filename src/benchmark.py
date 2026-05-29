import pandas as pd
from datetime import datetime, timezone


BENCHMARK_NAMES = {
    "BTC_hold": "BTC Buy & Hold",
    "ETH_hold": "ETH Buy & Hold",
    "BTC_ETH_50_50": "50/50 BTC+ETH",
    "equal_weight_universe": "Equal Weight (8 assets)",
    "cash": "Cash (0% return)",
}


def _buy_price(df: pd.DataFrame, start_date: str) -> float:
    """Get the open price on or after start_date."""
    start_dt = pd.Timestamp(start_date, tz="UTC")
    future = df[df.index >= start_dt]
    if len(future) == 0:
        return float(df["close"].iloc[-1])
    return float(future.iloc[0]["open"])


def _current_price(df: pd.DataFrame, as_of_date: str) -> float:
    cutoff = pd.Timestamp(as_of_date, tz="UTC")
    past = df[df.index <= cutoff]
    if len(past) == 0:
        return float(df["close"].iloc[0])
    return float(past.iloc[-1]["close"])


def compute_benchmarks(
    data: dict,
    start_date: str,
    as_of_date: str,
    starting_capital: float,
    cfg: dict,
) -> dict:
    """
    Compute all benchmark portfolio values as of as_of_date.
    Benchmarks use next-day open for entry (same rule as Claude).
    Single buy-and-hold trade: one fee applied at entry only.
    """
    fee_rate = cfg["risk"]["trading_fee_bps"] / 10000
    slippage_rate = cfg["risk"]["slippage_bps"] / 10000
    entry_cost = fee_rate + slippage_rate

    results = {}

    # BTC hold
    if "BTC" in data:
        buy = _buy_price(data["BTC"], start_date)
        current = _current_price(data["BTC"], as_of_date)
        invested = starting_capital * (1 - entry_cost)
        qty = invested / buy
        value = qty * current
        results["BTC_hold"] = {
            "value": round(value, 2),
            "return_pct": round((value - starting_capital) / starting_capital, 4),
            "buy_price": round(buy, 4),
            "current_price": round(current, 4),
        }

    # ETH hold
    if "ETH" in data:
        buy = _buy_price(data["ETH"], start_date)
        current = _current_price(data["ETH"], as_of_date)
        invested = starting_capital * (1 - entry_cost)
        qty = invested / buy
        value = qty * current
        results["ETH_hold"] = {
            "value": round(value, 2),
            "return_pct": round((value - starting_capital) / starting_capital, 4),
            "buy_price": round(buy, 4),
            "current_price": round(current, 4),
        }

    # 50/50 BTC + ETH
    if "BTC" in data and "ETH" in data:
        half = starting_capital / 2
        invested = half * (1 - entry_cost)
        btc_buy = _buy_price(data["BTC"], start_date)
        eth_buy = _buy_price(data["ETH"], start_date)
        btc_val = (invested / btc_buy) * _current_price(data["BTC"], as_of_date)
        eth_val = (invested / eth_buy) * _current_price(data["ETH"], as_of_date)
        value = btc_val + eth_val
        results["BTC_ETH_50_50"] = {
            "value": round(value, 2),
            "return_pct": round((value - starting_capital) / starting_capital, 4),
        }

    # equal weight across all 8 assets
    universe = cfg["assets"]["universe"]
    per_asset = starting_capital / len(universe)
    eq_value = 0.0
    for asset in universe:
        if asset in data:
            invested = per_asset * (1 - entry_cost)
            buy = _buy_price(data[asset], start_date)
            current = _current_price(data[asset], as_of_date)
            eq_value += (invested / buy) * current
    results["equal_weight_universe"] = {
        "value": round(eq_value, 2),
        "return_pct": round((eq_value - starting_capital) / starting_capital, 4),
    }

    # cash — no return
    results["cash"] = {
        "value": starting_capital,
        "return_pct": 0.0,
    }

    return results


def benchmark_summary_at_day(benchmarks: dict) -> dict:
    """Compact version for the Claude market packet."""
    return {k: round(v["return_pct"] * 100, 2) for k, v in benchmarks.items()}
