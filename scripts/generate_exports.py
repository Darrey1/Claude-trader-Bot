"""
Export package generator.

Run after a completed episode to produce the full filming package:
  - trade_log.csv
  - summary.html
  - key_moments.md
  - charts/ (equity curve, benchmark comparison, drawdown, daily PnL, allocation heatmap)

Usage:
  python3 scripts/generate_exports.py --run-id <run_id>
  python3 scripts/generate_exports.py  (uses the most recent run)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import argparse
import json
import csv
from pathlib import Path
from datetime import datetime
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

RUNS_DIR = Path("runs")
STARTING_CAPITAL = 20000

BENCHMARK_LABELS = {
    "BTC_hold":              "BTC Hold",
    "ETH_hold":              "ETH Hold",
    "BTC_ETH_50_50":         "50/50 BTC+ETH",
    "equal_weight_universe": "Equal Weight",
    "cash":                  "Cash",
}
BENCHMARK_COLORS = {
    "BTC_hold": "#f7931a", "ETH_hold": "#627eea",
    "BTC_ETH_50_50": "#9b59b6", "equal_weight_universe": "#2ecc71", "cash": "#95a5a6",
}


def load(run_id: str):
    run_dir = RUNS_DIR / run_id
    with open(run_dir / "all_snapshots.json") as f:
        snapshots = json.load(f)
    with open(run_dir / "run_log.json") as f:
        run_log = json.load(f)
    return snapshots, run_log, run_dir


def export_trade_log(run_log: dict, run_dir: Path):
    trades = run_log.get("all_trades", [])
    if not trades:
        print("  No trades to export.")
        return
    fieldnames = ["day", "date", "action", "asset", "price", "quantity", "notional",
                  "fee", "slippage", "total_cost", "net_proceeds", "realized_pnl", "reason"]
    path = run_dir / "exports" / "trade_log.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)
    print(f"  Trade log → {path} ({len(trades)} trades)")


def export_charts(snapshots: list, run_dir: Path):
    charts_dir = run_dir / "exports" / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    final_snap = snapshots[-1]
    benchmarks = final_snap.get("benchmarks", {})

    # 1. Equity curve vs benchmarks
    equity = [s["total_value"] for s in snapshots]
    days_x = list(range(len(equity)))

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=days_x, y=equity, name="Claude",
                             line=dict(color="#00d4aa", width=3), mode="lines+markers"))
    for bkey, bdata in benchmarks.items():
        bval = bdata.get("value", STARTING_CAPITAL)
        fig.add_trace(go.Scatter(
            x=[0, len(equity) - 1], y=[STARTING_CAPITAL, bval],
            name=BENCHMARK_LABELS.get(bkey, bkey),
            line=dict(color=BENCHMARK_COLORS.get(bkey, "#888"), width=2, dash="dot"),
        ))
    fig.update_layout(title="Portfolio Value vs Benchmarks", height=500,
                      template="plotly_dark", legend=dict(orientation="h", y=-0.2))
    fig.write_image(str(charts_dir / "equity_curve.png"), width=1200, height=500)
    print("  Chart → equity_curve.png")

    # 2. Daily PnL bars
    daily_pnl = []
    day_labels = []
    prev = STARTING_CAPITAL
    for i, s in enumerate(snapshots):
        if i == 0:
            continue
        pnl_d = s["total_value"] - prev
        daily_pnl.append(round(pnl_d, 2))
        day_labels.append(f"Day {i}\n{s.get('date','')[:10]}")
        prev = s["total_value"]
    bar_colors = ["#00d4aa" if v >= 0 else "#ef5350" for v in daily_pnl]
    fig2 = go.Figure(go.Bar(x=day_labels, y=daily_pnl, marker_color=bar_colors,
                             text=[f"${v:+,.0f}" for v in daily_pnl], textposition="outside"))
    fig2.update_layout(title="Daily PnL", height=400, template="plotly_dark")
    fig2.write_image(str(charts_dir / "daily_pnl.png"), width=1200, height=400)
    print("  Chart → daily_pnl.png")

    # 3. Drawdown chart
    peak = STARTING_CAPITAL
    drawdowns = []
    for s in snapshots:
        v = s["total_value"]
        peak = max(peak, v)
        dd = (v - peak) / peak * 100
        drawdowns.append(round(dd, 3))
    fig3 = go.Figure(go.Scatter(x=days_x, y=drawdowns, fill="tozeroy",
                                 line=dict(color="#ef5350"), name="Drawdown %"))
    fig3.update_layout(title="Drawdown from Peak (%)", height=350, template="plotly_dark",
                       yaxis=dict(tickformat=".1f", ticksuffix="%"))
    fig3.write_image(str(charts_dir / "drawdown.png"), width=1200, height=350)
    print("  Chart → drawdown.png")

    # 4. Benchmark comparison bar chart (final returns)
    bench_names = [BENCHMARK_LABELS.get(k, k) for k in benchmarks]
    bench_rets = [benchmarks[k].get("return_pct", 0) * 100 for k in benchmarks]
    claude_ret = (snapshots[-1]["total_value"] - STARTING_CAPITAL) / STARTING_CAPITAL * 100
    all_names = ["Claude"] + bench_names
    all_rets = [claude_ret] + bench_rets
    bar_c = ["#00d4aa" if v >= 0 else "#ef5350" for v in all_rets]
    fig4 = go.Figure(go.Bar(
        x=all_names, y=all_rets, marker_color=bar_c,
        text=[f"{v:+.2f}%" for v in all_rets], textposition="outside",
    ))
    fig4.update_layout(title="7-Day Returns vs Benchmarks", height=450, template="plotly_dark",
                       yaxis=dict(ticksuffix="%"))
    fig4.write_image(str(charts_dir / "benchmark_comparison.png"), width=1000, height=450)
    print("  Chart → benchmark_comparison.png")

    # 5. Strategy usage timeline
    strategies = []
    strat_days = []
    for s in snapshots[1:]:
        dec = s.get("decision") or {}
        strategies.append((dec.get("selected_strategy") or "—").replace("_", " ").title())
        strat_days.append(f"Day {s.get('day', '?')}")
    fig5 = go.Figure(go.Bar(
        x=strat_days, y=[1] * len(strategies),
        text=strategies, textposition="inside",
        marker_color=["#00d4aa", "#ff6b35", "#7c4dff", "#ffd600", "#ef5350", "#42a5f5",
                      "#f7931a"][:len(strategies)],
    ))
    fig5.update_layout(title="Strategy Selected Each Day", height=300, template="plotly_dark",
                       yaxis=dict(visible=False), showlegend=False)
    fig5.write_image(str(charts_dir / "strategy_timeline.png"), width=1200, height=300)
    print("  Chart → strategy_timeline.png")


def export_key_moments(snapshots: list, run_log: dict, run_dir: Path):
    final_val = snapshots[-1]["total_value"]
    final_ret = (final_val - STARTING_CAPITAL) / STARTING_CAPITAL * 100
    all_trades = run_log.get("all_trades", [])

    moments = []

    # biggest single-day gain/loss
    prev = STARTING_CAPITAL
    best_day = {"day": 0, "pnl": 0}
    worst_day = {"day": 0, "pnl": 0}
    for i, s in enumerate(snapshots):
        if i == 0:
            continue
        pnl_d = s["total_value"] - prev
        if pnl_d > best_day["pnl"]:
            best_day = {"day": i, "pnl": pnl_d, "date": s.get("date", ""), "value": s["total_value"]}
        if pnl_d < worst_day["pnl"]:
            worst_day = {"day": i, "pnl": pnl_d, "date": s.get("date", ""), "value": s["total_value"]}
        prev = s["total_value"]

    if best_day["pnl"] > 0:
        moments.append(f"**Day {best_day['day']} — Best Day:** +${best_day['pnl']:,.2f} | Portfolio hit ${best_day['value']:,.2f}")
    if worst_day["pnl"] < 0:
        moments.append(f"**Day {worst_day['day']} — Worst Day:** ${worst_day['pnl']:,.2f} | Portfolio dropped to ${worst_day['value']:,.2f}")

    # strategy switches
    prev_strat = None
    for s in snapshots[1:]:
        dec = s.get("decision") or {}
        strat = dec.get("selected_strategy")
        if strat and strat != prev_strat and prev_strat is not None:
            moments.append(f"**Day {s.get('day')} — Strategy Switch:** {prev_strat.replace('_',' ').title()} → {strat.replace('_',' ').title()}")
        prev_strat = strat

    # risk validator corrections
    for s in snapshots[1:]:
        dec = s.get("decision") or {}
        val = dec.get("validation_report") or {}
        if val.get("corrections"):
            moments.append(f"**Day {s.get('day')} — Risk Override:** Validator corrected Claude's allocation → {', '.join(val['corrections'][:1])}")

    # largest single trade
    if all_trades:
        biggest = max(all_trades, key=lambda t: t.get("notional", 0))
        moments.append(
            f"**Day {biggest['day']} — Biggest Trade:** {biggest['action']} {biggest['asset']} "
            f"${biggest['notional']:,.2f} @ ${biggest['price']:,.4f}"
        )

    # final result vs benchmarks
    final_snap = snapshots[-1]
    benchmarks = final_snap.get("benchmarks", {})
    beaten = [BENCHMARK_LABELS.get(k, k) for k, v in benchmarks.items() if final_ret/100 > v.get("return_pct", 0)]
    lost_to = [BENCHMARK_LABELS.get(k, k) for k, v in benchmarks.items() if final_ret/100 <= v.get("return_pct", 0)]
    result_line = f"**Final Reveal:** Claude returned {final_ret:+.2f}%"
    if beaten:
        result_line += f" — beat {', '.join(beaten)}"
    if lost_to:
        result_line += f" — lost to {', '.join(lost_to)}"
    moments.append(result_line)

    md = f"""# Key Moments — Filming Guide
*Generated from run logs. Do not edit — sourced directly from execution data.*

## Episode Summary
- **Starting Capital:** $20,000
- **Final Value:** ${final_val:,.2f}
- **Total Return:** {final_ret:+.2f}%
- **Total Trades:** {len(all_trades)}
- **Run ID:** {run_log.get('run_id', '—')}

---

## Key Moments (React to These on Camera)

"""
    for i, m in enumerate(moments, 1):
        md += f"{i}. {m}\n\n"

    md += """---

## Filming Notes
- Navigate the dashboard Day 0 → Day 7 using the sidebar
- Pause on each day before revealing the next
- The Claude reasoning panel shows exactly what it was thinking
- The risk validator panel shows if/when the system overrode Claude
- Export charts are in exports/charts/ for the editor
"""
    path = run_dir / "exports" / "key_moments.md"
    path.write_text(md)
    print(f"  Key moments → {path}")


def export_html_summary(snapshots: list, run_log: dict, run_dir: Path):
    final_val = snapshots[-1]["total_value"]
    final_ret = (final_val - STARTING_CAPITAL) / STARTING_CAPITAL * 100
    all_trades = run_log.get("all_trades", [])
    benchmarks = snapshots[-1].get("benchmarks", {})

    bench_rows = ""
    for k, v in benchmarks.items():
        ret = v.get("return_pct", 0) * 100
        color = "#00d4aa" if ret >= 0 else "#ef5350"
        bench_rows += f"<tr><td>{BENCHMARK_LABELS.get(k, k)}</td><td>${v.get('value', 20000):,.2f}</td><td style='color:{color}'>{ret:+.2f}%</td></tr>"

    trade_rows = ""
    for t in all_trades[-20:]:  # last 20 trades for summary
        action_color = "#00d4aa" if t["action"] == "BUY" else "#ef5350"
        trade_rows += f"""<tr>
            <td>Day {t['day']}</td><td>{t.get('date','')[:10]}</td>
            <td style='color:{action_color}'><b>{t['action']}</b></td>
            <td>{t['asset']}</td>
            <td>${t['price']:,.4f}</td>
            <td>{t['quantity']:.6f}</td>
            <td>${t['notional']:,.2f}</td>
            <td>${t.get('total_cost',0):.2f}</td>
        </tr>"""

    ret_color = "#00d4aa" if final_ret >= 0 else "#ef5350"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Claude Trader — Episode Summary</title>
<style>
  body {{ font-family: 'Helvetica Neue', sans-serif; background: #0e0e0e; color: #eee; margin: 40px; }}
  h1 {{ color: #00d4aa; }} h2 {{ color: #aaa; border-bottom: 1px solid #333; padding-bottom: 8px; }}
  .metric {{ display: inline-block; margin: 16px; padding: 20px 30px; background: #1a1a1a;
             border-radius: 12px; text-align: center; min-width: 160px; }}
  .metric .label {{ font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 1px; }}
  .metric .value {{ font-size: 28px; font-weight: bold; margin-top: 8px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
  th {{ background: #1a1a1a; padding: 10px; text-align: left; color: #aaa; font-size: 12px; text-transform: uppercase; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #222; font-size: 14px; }}
  tr:hover {{ background: #1a1a1a; }}
  .tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px;
          background: #222; color: #aaa; margin: 2px; }}
  .disclaimer {{ font-size: 11px; color: #555; margin-top: 40px; border-top: 1px solid #222; padding-top: 16px; }}
</style>
</head><body>
<h1>📈 Claude Trader — $20,000 Paper Portfolio Challenge</h1>
<p>7-Day Historical Replay | Paper Trading Only | No Real Money</p>
<div class="tag">Run ID: {run_log.get('run_id','—')}</div>
<div class="tag">Model: {run_log.get('config',{}).get('episode',{}).get('model','—')}</div>
<div class="tag">Window: {run_log.get('config',{}).get('episode',{}).get('start_date','—')} → {run_log.get('config',{}).get('episode',{}).get('end_date','—')}</div>

<h2>Final Results</h2>
<div class="metric"><div class="label">Starting Capital</div><div class="value">$20,000</div></div>
<div class="metric"><div class="label">Final Value</div><div class="value">${final_val:,.2f}</div></div>
<div class="metric"><div class="label">Total Return</div><div class="value" style="color:{ret_color}">{final_ret:+.2f}%</div></div>
<div class="metric"><div class="label">Total Trades</div><div class="value">{len(all_trades)}</div></div>
<div class="metric"><div class="label">Max Drawdown</div><div class="value">{snapshots[-1].get('max_drawdown',0)*100:.2f}%</div></div>

<h2>Benchmark Comparison</h2>
<table><tr><th>Benchmark</th><th>Final Value</th><th>Return</th></tr>
<tr><td><b>Claude</b></td><td><b>${final_val:,.2f}</b></td><td style='color:{ret_color}'><b>{final_ret:+.2f}%</b></td></tr>
{bench_rows}</table>

<h2>Trade Log (Last 20 Trades)</h2>
<table><tr><th>Day</th><th>Date</th><th>Action</th><th>Asset</th><th>Price</th><th>Quantity</th><th>Notional</th><th>Fee+Slip</th></tr>
{trade_rows}</table>

<div class="disclaimer">
PAPER TRADING ONLY. All results are simulated using historical market data. No real money was traded.
The system architecture is real and functional — the same pipeline could be connected to a live exchange.
Results have not been manually altered. Run ID: {run_log.get('run_id','—')}.
Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
</div>
</body></html>"""

    path = run_dir / "exports" / "summary.html"
    path.write_text(html)
    print(f"  HTML summary → {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    if args.run_id:
        run_id = args.run_id
    else:
        runs = sorted([d.name for d in RUNS_DIR.iterdir() if d.is_dir() and (d / "all_snapshots.json").exists()])
        if not runs:
            print("No completed runs found.")
            sys.exit(1)
        run_id = runs[-1]

    print(f"\n=== EXPORT GENERATOR | Run: {run_id} ===\n")
    snapshots, run_log, run_dir = load(run_id)
    export_dir = run_dir / "exports"
    export_dir.mkdir(exist_ok=True)

    print("Exporting trade log...")
    export_trade_log(run_log, run_dir)

    print("Exporting charts...")
    export_charts(snapshots, run_dir)

    print("Exporting key moments list...")
    export_key_moments(snapshots, run_log, run_dir)

    print("Exporting HTML summary...")
    export_html_summary(snapshots, run_log, run_dir)

    print(f"\n=== DONE ===")
    print(f"Full export package: {export_dir}/")
    print("  trade_log.csv")
    print("  summary.html")
    print("  key_moments.md")
    print("  charts/equity_curve.png")
    print("  charts/daily_pnl.png")
    print("  charts/drawdown.png")
    print("  charts/benchmark_comparison.png")
    print("  charts/strategy_timeline.png")


if __name__ == "__main__":
    main()
