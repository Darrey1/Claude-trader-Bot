import ccxt
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import time


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


def _get_exchange():
    return ccxt.binance({"enableRateLimit": True})


def fetch_ohlcv(asset: str, start_date: str, end_date: str, lookback_days: int = 60) -> pd.DataFrame:
    """
    Fetch daily OHLCV candles for an asset from Binance.
    Fetches lookback_days before start_date for indicator warmup.
    Returns DataFrame with UTC timestamps as index.
    """
    exchange = _get_exchange()
    symbol = SYMBOL_MAP[asset]

    since_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    since_dt = since_dt - timedelta(days=lookback_days)
    since_ms = int(since_dt.timestamp() * 1000)

    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = end_dt + timedelta(days=1)

    all_candles = []
    current_since = since_ms

    while True:
        candles = exchange.fetch_ohlcv(symbol, timeframe="1d", since=current_since, limit=500)
        if not candles:
            break
        all_candles.extend(candles)
        last_ts = candles[-1][0]
        if last_ts >= int(end_dt.timestamp() * 1000):
            break
        current_since = last_ts + 86400000
        time.sleep(0.2)

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()

    # trim to end date
    df = df[df.index <= end_dt]

    # drop zero-volume candles
    df = df[df["volume"] > 0]
    df = df[~df.index.duplicated(keep="first")]

    return df


def fetch_all_assets(cfg: dict) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for every asset in the universe and return as a dict."""
    universe = cfg["assets"]["universe"]
    start = cfg["episode"]["start_date"]
    end = cfg["episode"]["end_date"]
    lookback = cfg["assets"]["lookback_days"]

    data = {}
    for asset in universe:
        print(f"  Fetching {asset}...")
        data[asset] = fetch_ohlcv(asset, start, end, lookback)
        time.sleep(0.3)

    return data


def get_day_open(data: dict[str, pd.DataFrame], asset: str, date: str) -> float | None:
    """Return the open price for an asset on a given date (used for trade execution)."""
    df = data[asset]
    date_dt = pd.Timestamp(date, tz="UTC")
    if date_dt in df.index:
        return float(df.loc[date_dt, "open"])
    # find nearest next available candle
    future = df[df.index >= date_dt]
    if len(future) > 0:
        return float(future.iloc[0]["open"])
    return None


def get_day_close(data: dict[str, pd.DataFrame], asset: str, date: str) -> float | None:
    df = data[asset]
    date_dt = pd.Timestamp(date, tz="UTC")
    if date_dt in df.index:
        return float(df.loc[date_dt, "close"])
    return None


def save_data_manifest(data: dict[str, pd.DataFrame], run_dir: Path, cfg: dict):
    manifest = {
        "source": "Binance public REST API",
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "symbol_map": SYMBOL_MAP,
        "candle_interval": "1d",
        "assets": {}
    }
    for asset, df in data.items():
        manifest["assets"][asset] = {
            "symbol": SYMBOL_MAP[asset],
            "candle_count": len(df),
            "first_candle": df.index[0].isoformat(),
            "last_candle": df.index[-1].isoformat(),
        }

    with open(run_dir / "data_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
