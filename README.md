# Claude Trader — $20,000 AI Crypto Challenge

A fully automated paper trading system where Claude AI manages a simulated $20,000 crypto portfolio.

Claude reads live market data from Binance every day, computes technical indicators, decides how to allocate the portfolio across 8 cryptocurrencies, and executes simulated trades — all with full logging, risk enforcement, and a visual dashboard.

**This is paper trading. No real money is involved.**

---

## How It Works

Every day the system runs through this pipeline:

```
Binance API → Live Prices + OHLCV History
      ↓
Technical Indicators (RSI, SMA, Volatility, Drawdown)
      ↓
Claude AI → Strategy + Target Allocations + Reasoning
      ↓
Risk Validator → Enforce Hard Position Limits
      ↓
Portfolio Engine → Execute Paper Trades + Mark to Market
      ↓
Snapshot Saved → Dashboard + Exports Updated
```

---

## Modes

### Backtest Mode (recommended)
Runs all 7 days instantly using historical Binance candle data. Set a date range in the config and run once.

### Paper-Forward Mode
Runs one day at a time using live real-time prices. Designed for a cron job that fires daily at 09:00 UTC over 7 real days.

---

## Project Structure

```
claude-trader-bot/
├── config/
│   └── episode_01.yaml          # Master config — dates, assets, risk rules, capital
│
├── src/
│   ├── config_manager.py        # Loads and validates the config, generates run IDs
│   ├── market_data.py           # Historical OHLCV fetcher from Binance (backtest)
│   ├── live_prices.py           # Real-time price fetcher from Binance (paper-forward)
│   ├── indicators.py            # RSI, SMA, volatility, drawdown — pure pandas/numpy
│   ├── claude_agent.py          # Builds market packet, calls Claude API, parses decision
│   ├── risk_validator.py        # Enforces hard position limits on Claude's output
│   ├── portfolio_engine.py      # Paper trade execution, mark-to-market, snapshots
│   └── benchmark.py             # Tracks 5 benchmark portfolios alongside Claude
│
├── scripts/
│   ├── run_episode.py           # Backtest runner — runs all 7 days at once
│   ├── run_paper_forward.py     # Paper-forward runner — runs one day at a time
│   ├── generate_exports.py      # Generates charts, CSV, HTML, key moments after Day 7
│   └── backtest_scan.py         # Scans historical windows and scores them for story value
│
├── dashboard/
│   └── app.py                   # Streamlit dashboard — Day 0 to Day 7 visual review
│
├── runs/                        # All run data saved here (auto-created)
│   └── ep01_YYYYMMDD_XXXXXX/
│       ├── all_snapshots.json
│       ├── run_log.json
│       ├── forward_run_state.json
│       ├── config_snapshot.yaml
│       ├── decisions/
│       ├── claude_raw/
│       ├── market_packets/
│       ├── portfolio_states/
│       └── exports/
│           ├── charts/
│           ├── trade_log.csv
│           ├── summary.html
│           └── key_moments.md
│
├── requirements.txt
├── run_daily.sh                 # Manual shell wrapper for paper-forward
└── setup_cron.sh                # Installs daily cron job for paper-forward
```

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo-url>
cd claude-trader-bot
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Add your Anthropic API key

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Get your key from [console.anthropic.com](https://console.anthropic.com).

No Binance API key is needed — market data is pulled from Binance's public REST API.

---

## Running a Backtest

### Step 1 — Set your date range in the config

Open `config/episode_01.yaml` and set the dates. Remove `run_id` and `locked_at` if they are present from a previous run:

```yaml
episode:
  run_mode: backtest
  start_date: '2026-05-15'   # Day 0 baseline date
  end_date:   '2026-05-21'   # Last execution date
  duration_days: 7
```

`start_date` is Day 0 — the baseline. Trades execute from Day 1 through Day 7, with each day's decision made on the prior day's data.

### Step 2 — Run the backtest

```bash
python3 scripts/run_episode.py --config config/episode_01.yaml
```

All 7 days run sequentially. Expect 2–4 minutes — most of the time is waiting for Claude API responses.

### Step 3 — Generate the export package

```bash
python3 scripts/generate_exports.py
```

This produces the full filming package in `runs/<run_id>/exports/`.

### Step 4 — Open the dashboard

```bash
streamlit run dashboard/app.py
```

Navigate Day 0 → Day 7 using the sidebar.

---

## Running in Paper-Forward Mode

Paper-forward uses live prices and runs one day at a time over 7 real days.

### Initialize (Day 0 — run once)

```yaml
# In config/episode_01.yaml — remove run_id and locked_at, set run_mode:
episode:
  run_mode: paper_forward
  start_date: '2026-05-28'
  end_date:   '2026-06-04'
  duration_days: 7
```

```bash
python3 scripts/run_paper_forward.py --config config/episode_01.yaml
```

### Automate with cron (runs at 09:00 UTC daily)

```bash
bash setup_cron.sh
```

Or to run manually each day:

```bash
bash run_daily.sh
```

After Day 7, generate exports and open the dashboard as above.

---

## Configuration Reference

All settings live in `config/episode_01.yaml`. Once a run is initialized the file is locked — do not edit it mid-run.

| Field | Description |
|---|---|
| `run_mode` | `backtest` or `paper_forward` |
| `start_date` | Day 0 baseline date |
| `end_date` | Last execution date |
| `duration_days` | Number of trading days (7) |
| `model` | Claude model to use |
| `assets.universe` | List of coins to trade |
| `assets.lookback_days` | Days of OHLCV history for indicator warmup |
| `risk.max_asset_allocation` | Max % of portfolio in any single coin (0.4 = 40%) |
| `risk.max_total_crypto_exposure` | Max % in crypto total (0.8 = 80%) |
| `risk.min_cash_allocation` | Minimum cash to always hold (0.2 = 20%) |
| `risk.trading_fee_bps` | Simulated trading fee in basis points (10 = 0.10%) |
| `risk.slippage_bps` | Simulated slippage in basis points (5 = 0.05%) |
| `portfolio.starting_capital` | Starting portfolio value in USD |

---

## Claude's Decision Schema

Each day Claude receives a structured JSON market packet and must return a decision in this exact format:

```json
{
  "day": 1,
  "decision_date": "2026-05-15",
  "market_view": "bearish",
  "selected_strategy": "risk_off",
  "portfolio_action": "de_risk",
  "target_allocations": {
    "BTC": 0.30,
    "ETH": 0.10,
    "SOL": 0.00,
    "BNB": 0.15,
    "XRP": 0.00,
    "DOGE": 0.00,
    "LINK": 0.00,
    "AVAX": 0.00,
    "CASH": 0.45
  },
  "reasoning": "...",
  "risk_note": "...",
  "confidence": 0.65
}
```

**Available strategies:** `trend_following`, `momentum_rotation`, `mean_reversion`, `breakout`, `risk_off`, `balanced`

Allocations must sum to exactly 1.0. The risk validator enforces this before any trade executes.

---

## Risk Validator Rules

Applied to every Claude decision before execution, in this order:

1. Unknown assets are rejected
2. Missing assets are filled with 0%
3. Negative allocations are zeroed
4. Any single asset capped at **40%**
5. Total crypto exposure capped at **80%**
6. Minimum cash enforced at **20%**
7. Allocations normalized to sum to exactly 1.0

If any correction is made, the decision is flagged as `CORRECTED` in the run log and dashboard.

---

## Benchmarks

Five passive strategies run alongside Claude for comparison:

| Benchmark | Description |
|---|---|
| `BTC_hold` | All $20,000 into BTC on Day 0, held unchanged |
| `ETH_hold` | All $20,000 into ETH on Day 0, held unchanged |
| `BTC_ETH_50_50` | Split equally between BTC and ETH, held unchanged |
| `equal_weight_universe` | Split equally across all 8 coins, held unchanged |
| `cash` | No investment, $20,000 stays in cash |

All benchmarks apply the same one-time entry fee on Day 0 to make the comparison fair.

---

## Export Package

After running `generate_exports.py`, the following files are produced in `runs/<run_id>/exports/`:

| File | Description |
|---|---|
| `charts/equity_curve.png` | Portfolio value vs all benchmarks over 7 days |
| `charts/daily_pnl.png` | Daily gain/loss bars |
| `charts/drawdown.png` | Drawdown from peak across the run |
| `charts/benchmark_comparison.png` | Final returns: Claude vs all 5 benchmarks |
| `charts/strategy_timeline.png` | Strategy Claude selected each day |
| `trade_log.csv` | All trades with full detail (price, quantity, fees, PnL) |
| `summary.html` | Styled HTML report with results and trade log |
| `key_moments.md` | Auto-generated filming guide (best/worst days, strategy switches, biggest trades) |

---

## Technical Indicators

All indicators are implemented in pure pandas/numpy — no third-party indicator library.

| Indicator | Details |
|---|---|
| RSI | 7-period and 14-period |
| SMA | 20-day and 50-day |
| Volatility | 14-day annualized |
| Drawdown | From 30-day high |
| Trend | `strong_uptrend`, `uptrend`, `neutral`, `downtrend`, `strong_downtrend` |
| Returns | 1-day, 7-day, 30-day percentage |

**Anti-leakage:** All indicators are computed using only closed historical candles. Today's in-progress candle is never included in the calculation.

---

## Requirements

```
anthropic>=0.40.0
ccxt>=4.3.0
pandas>=2.2.0
numpy>=1.26.0
streamlit>=1.40.0
plotly>=5.24.0
pyyaml>=6.0.2
python-dotenv>=1.0.1
pillow>=11.0.0
requests>=2.32.0
kaleido>=0.2.1
```

Python 3.11+ recommended.

---

## Disclaimer

This project is for educational and entertainment purposes only. All trading is simulated paper trading using historical and live market data from Binance's public API. No real money is traded. Past simulated performance does not indicate future real-world results. Nothing in this project constitutes financial advice.
