"""
Live price fetcher for paper-forward mode.

Fetches current prices and recent OHLCV history from Binance public API.
No API key required.
"""
import ccxt
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

SYMBOL_MAP = {
    "BTC": "BTC/USDT",
    "ETH": "ETH/USDT",
    "SOL": "SOL/USDT",
    "BNB": "BNB/USDT",
    "XRP": "XRP/USDT",
    "DOGE": "DOGE/USDT",
    "LINK": "LINK/USDT",
    "AVAX": "AVAX/USDT",
}


def _exchange():
    return ccxt.binance({"enableRateLimit": True})


def fetch_current_prices(universe: list[str]) -> dict:
    """Fetch the latest ticker price for every asset. This is the live price right now."""
    exchange = _exchange()
    prices = {}
    for asset in universe:
        symbol = SYMBOL_MAP[asset]
        ticker = exchange.fetch_ticker(symbol)
        prices[asset] = float(ticker["last"])
        time.sleep(0.1)
    return prices


def fetch_live_ohlcv(asset: str, lookback_days: int = 65) -> pd.DataFrame:
    """
    Fetch recent daily OHLCV candles for indicator computation.
    Returns only fully closed candles — never the in-progress current day.
    """
    exchange = _exchange()
    symbol = SYMBOL_MAP[asset]
    since_dt = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    since_ms = int(since_dt.timestamp() * 1000)

    candles = []
    current = since_ms
    while True:
        batch = exchange.fetch_ohlcv(symbol, "1d", since=current, limit=500)
        if not batch:
            break
        candles.extend(batch)
        if len(batch) < 500:
            break
        current = batch[-1][0] + 86400000
        time.sleep(0.15)

    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[df["volume"] > 0]
    df = df[~df.index.duplicated(keep="first")]

    # drop today's in-progress candle — only use fully closed days
    today = pd.Timestamp.now(tz="UTC").normalize()
    df = df[df.index < today]

    return df


def fetch_all_live_ohlcv(universe: list[str], lookback_days: int = 65) -> dict:
    """Fetch live OHLCV history for all assets in the universe."""
    data = {}
    for asset in universe:
        print(f"  Fetching {asset} history...")
        data[asset] = fetch_live_ohlcv(asset, lookback_days)
        time.sleep(0.2)
    return data


def get_benchmark_entry_prices(universe: list[str], start_prices: dict) -> dict:
    """
    Returns the prices at which benchmarks entered (Day 0 prices).
    Used to compute benchmark performance over the run.
    """
    return start_prices
