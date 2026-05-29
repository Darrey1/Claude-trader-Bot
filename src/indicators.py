import pandas as pd
import numpy as np
from datetime import datetime, timezone


def _slice(df: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    """Return only candles up to and including as_of_date. Anti-leakage gate."""
    cutoff = pd.Timestamp(as_of_date, tz="UTC")
    return df[df.index <= cutoff].copy()


def rsi(series: pd.Series, period: int) -> float | None:
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    val = rsi_series.iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else None


def sma(series: pd.Series, period: int) -> float | None:
    if len(series) < period:
        return None
    val = series.rolling(period).mean().iloc[-1]
    return round(float(val), 6) if not pd.isna(val) else None


def volatility(series: pd.Series, window: int) -> float | None:
    """Annualized rolling volatility from daily log returns."""
    if len(series) < window + 1:
        return None
    log_returns = np.log(series / series.shift(1)).dropna()
    if len(log_returns) < window:
        return None
    vol = log_returns.iloc[-window:].std() * np.sqrt(365)
    return round(float(vol), 4) if not pd.isna(vol) else None


def drawdown_from_high(series: pd.Series, lookback: int) -> float | None:
    """Current price vs rolling high over lookback window."""
    if len(series) < 2:
        return None
    window = series.iloc[-lookback:]
    peak = window.max()
    current = series.iloc[-1]
    dd = (current - peak) / peak
    return round(float(dd), 4)


def trend_status(close: float, sma20: float | None, sma50: float | None) -> str:
    if sma20 is None or sma50 is None:
        return "unknown"
    if close > sma20 > sma50:
        return "strong_uptrend"
    if close > sma20:
        return "uptrend"
    if close < sma20 < sma50:
        return "strong_downtrend"
    if close < sma20:
        return "downtrend"
    return "neutral"


def return_pct(series: pd.Series, periods: int) -> float | None:
    if len(series) < periods + 1:
        return None
    val = (series.iloc[-1] - series.iloc[-periods - 1]) / series.iloc[-periods - 1]
    return round(float(val), 6)


def compute_asset_signals(df: pd.DataFrame, as_of_date: str, cfg: dict) -> dict:
    """
    Compute all signals for one asset as of a given date.
    Strictly uses only past data — never leaks future candles.
    """
    sliced = _slice(df, as_of_date)
    if len(sliced) < 2:
        return {}

    closes = sliced["close"]
    current_price = float(closes.iloc[-1])

    ind = cfg["indicators"]
    rsi_periods = ind["rsi_periods"]
    sma_periods = ind["sma_periods"]
    vol_window = ind["volatility_window"]
    dd_lookback = ind["drawdown_lookback"]

    s20 = sma(closes, sma_periods[0])
    s50 = sma(closes, sma_periods[1])

    signals = {
        "price": round(current_price, 6),
        "return_1d": return_pct(closes, 1),
        "return_7d": return_pct(closes, 7),
        "return_30d": return_pct(closes, 30),
        "rsi_7": rsi(closes, rsi_periods[0]),
        "rsi_14": rsi(closes, rsi_periods[1]),
        "sma_20": round(s20, 4) if s20 else None,
        "sma_50": round(s50, 4) if s50 else None,
        "volatility_14d_annualized": volatility(closes, vol_window),
        "drawdown_from_30d_high": drawdown_from_high(closes, dd_lookback),
        "trend": trend_status(current_price, s20, s50),
        "candles_available": len(sliced),
    }

    return signals


def compute_all_signals(data: dict, as_of_date: str, cfg: dict) -> dict:
    """Compute signals for every asset in the universe."""
    universe = cfg["assets"]["universe"]
    signals = {}
    for asset in universe:
        if asset in data:
            signals[asset] = compute_asset_signals(data[asset], as_of_date, cfg)
    return signals
