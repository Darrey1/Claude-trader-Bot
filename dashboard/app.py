"""
Claude Trader Dashboard — Streamlit app.

Launch:
  streamlit run dashboard/app.py

Select a completed run from the sidebar, then navigate day by day.
"""
import streamlit as st
import json
import os
import sys
from pathlib import Path
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Claude Trader | $20K Crypto Challenge",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

RUNS_DIR = Path("runs")
STRATEGY_COLORS = {
    "trend_following":    "#00d4aa",
    "momentum_rotation":  "#ff6b35",
    "mean_reversion":     "#7c4dff",
    "breakout":           "#ffd600",
    "risk_off":           "#ef5350",
    "balanced":           "#42a5f5",
    None:                 "#888888",
}
BENCHMARK_COLORS = {
    "BTC_hold":              "#f7931a",
    "ETH_hold":              "#627eea",
    "BTC_ETH_50_50":         "#9b59b6",
    "equal_weight_universe": "#2ecc71",
    "cash":                  "#95a5a6",
}
BENCHMARK_LABELS = {
    "BTC_hold":              "BTC Hold",
    "ETH_hold":              "ETH Hold",
    "BTC_ETH_50_50":         "50/50 BTC+ETH",
    "equal_weight_universe": "Equal Weight",
    "cash":                  "Cash",
}


def load_snapshots(run_id: str) -> list[dict]:
    path = RUNS_DIR / run_id / "all_snapshots.json"
    with open(path) as f:
        return json.load(f)


def load_run_log(run_id: str) -> dict:
    path = RUNS_DIR / run_id / "run_log.json"
    with open(path) as f:
        return json.load(f)


def list_runs() -> list[str]:
    if not RUNS_DIR.exists():
        return []
    return sorted([d.name for d in RUNS_DIR.iterdir() if d.is_dir() and (d / "all_snapshots.json").exists()])


def fmt_pct(v: float, decimals: int = 2) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v*100:.{decimals}f}%"


def fmt_usd(v: float) -> str:
    return f"${v:,.2f}"


def color_metric(value: float) -> str:
    return "#00d4aa" if value >= 0 else "#ef5350"


# ── sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📈 Claude Trader")
    st.markdown("**$20,000 Paper Portfolio**")
    st.divider()

    runs = list_runs()
    if not runs:
        st.warning("No completed runs found.\nRun `scripts/run_episode.py` first.")
        st.stop()

    selected_run = st.selectbox("Select Run", runs, index=len(runs) - 1)
    snapshots = load_snapshots(selected_run)
    run_log = load_run_log(selected_run)

    st.divider()
    st.markdown("### Navigate Days")
    day_labels = {0: "Day 0 — Setup"}
    for i in range(1, len(snapshots)):
        s = snapshots[i]
        pnl_pct = (s["total_value"] - 20000) / 20000 * 100
        sign = "+" if pnl_pct >= 0 else ""
        label = f"Day {i} — {sign}{pnl_pct:.1f}%"
        day_labels[i] = label

    selected_day = st.radio("", list(day_labels.keys()), format_func=lambda x: day_labels[x])
    st.divider()
    st.caption(f"Run: `{selected_run}`")
    st.caption(f"Model: {run_log['config']['episode']['model']}")

snap = snapshots[selected_day]
starting_capital = run_log["config"]["portfolio"]["starting_capital"]
total_value = snap["total_value"]
pnl_abs = total_value - starting_capital
pnl_pct = pnl_abs / starting_capital

# ── header ────────────────────────────────────────────────────────────────────
if selected_day == 0:
    st.markdown(f"# Day 0 — Challenge Setup")
    st.markdown(f"**{snap.get('date', '')} UTC** | Starting Capital: **{fmt_usd(starting_capital)}** | 100% Cash")
else:
    decision = snap.get("decision", {}) or {}
    strategy = decision.get("selected_strategy", "—")
    strat_color = STRATEGY_COLORS.get(strategy, "#888")
    st.markdown(
        f"# Day {selected_day} — "
        f"<span style='color:{strat_color};font-weight:bold'>{strategy.replace('_',' ').title() if strategy else '—'}</span>",
        unsafe_allow_html=True,
    )
    st.markdown(f"**{snap.get('date', '')} UTC**")

st.divider()

# ── top metrics row ───────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Portfolio Value", fmt_usd(total_value), delta=f"{pnl_abs:+,.2f}")

with col2:
    st.metric("Total Return", fmt_pct(pnl_pct), delta=None)

with col3:
    st.metric("Cash", fmt_usd(snap["cash"]))

with col4:
    dd = snap.get("max_drawdown", 0)
    st.metric("Max Drawdown", fmt_pct(dd))

with col5:
    trades_today = snap.get("trades_today", [])
    st.metric("Trades Today", len(trades_today))

st.divider()

# ── main content ──────────────────────────────────────────────────────────────
left, right = st.columns([3, 2])

with left:
    # Equity curve
    st.markdown("#### Portfolio vs Benchmarks")
    equity_data = snap.get("equity_curve", [starting_capital])
    days_x = list(range(len(equity_data)))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=days_x, y=equity_data,
        name="Claude", line=dict(color="#00d4aa", width=3),
        mode="lines+markers",
    ))

    # benchmark lines
    benchmarks = snap.get("benchmarks", {})
    for bench_key, bench_data in benchmarks.items():
        bench_value = bench_data.get("value", starting_capital)
        # flat line from 0 to current day at this value
        fig.add_trace(go.Scatter(
            x=[0, len(equity_data) - 1],
            y=[starting_capital, bench_value],
            name=BENCHMARK_LABELS.get(bench_key, bench_key),
            line=dict(color=BENCHMARK_COLORS.get(bench_key, "#888"), width=1.5, dash="dot"),
            mode="lines",
        ))

    fig.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=-0.2),
        xaxis=dict(title="Day", gridcolor="#333"),
        yaxis=dict(title="Value ($)", gridcolor="#333"),
        font=dict(color="#eee"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # daily PnL bars across all days
    st.markdown("#### Daily PnL")
    daily_pnl_vals = []
    daily_labels = []
    prev = starting_capital
    for i, s in enumerate(snapshots):
        if i == 0:
            continue
        pnl_d = s["total_value"] - prev
        daily_pnl_vals.append(round(pnl_d, 2))
        daily_labels.append(f"D{i}")
        prev = s["total_value"]
        if i == selected_day:
            break

    bar_colors = ["#00d4aa" if v >= 0 else "#ef5350" for v in daily_pnl_vals]
    fig2 = go.Figure(go.Bar(
        x=daily_labels, y=daily_pnl_vals,
        marker_color=bar_colors, text=[fmt_usd(v) for v in daily_pnl_vals],
        textposition="outside",
    ))
    fig2.update_layout(
        height=220,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="#333"),
        yaxis=dict(gridcolor="#333"),
        font=dict(color="#eee"),
    )
    st.plotly_chart(fig2, use_container_width=True)

with right:
    # Current positions / allocation
    st.markdown("#### Portfolio Allocation")
    positions = snap.get("positions", {})
    cash_pct = snap["cash"] / snap["total_value"] if snap["total_value"] > 0 else 1.0
    alloc_labels = list(positions.keys()) + ["CASH"]
    alloc_values = [p["allocation_pct"] for p in positions.values()] + [cash_pct]
    alloc_colors = ["#00d4aa", "#627eea", "#f7931a", "#ff6b35", "#7c4dff", "#ffd600", "#2ecc71", "#42a5f5", "#95a5a6"]

    if sum(alloc_values) > 0:
        fig3 = go.Figure(go.Pie(
            labels=alloc_labels,
            values=alloc_values,
            hole=0.5,
            marker_colors=alloc_colors[:len(alloc_labels)],
            textinfo="label+percent",
            textfont_size=13,
        ))
        fig3.update_layout(
            height=280,
            margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            font=dict(color="#eee"),
        )
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("100% Cash")

    # positions table
    if positions:
        st.markdown("#### Positions")
        rows = []
        for asset, pos in positions.items():
            rows.append({
                "Asset": asset,
                "Alloc": fmt_pct(pos["allocation_pct"]),
                "Value": fmt_usd(pos["market_value"]),
                "PnL": fmt_pct(pos["unrealized_pnl_pct"]),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

st.divider()

# ── Claude reasoning panel ────────────────────────────────────────────────────
if selected_day > 0:
    decision = snap.get("decision", {}) or {}
    col_strat, col_action, col_conf = st.columns(3)
    with col_strat:
        strategy = decision.get("selected_strategy", "—")
        color = STRATEGY_COLORS.get(strategy, "#888")
        st.markdown(f"**Strategy**")
        st.markdown(f"<h3 style='color:{color}'>{strategy.replace('_',' ').title() if strategy else '—'}</h3>", unsafe_allow_html=True)
    with col_action:
        st.markdown(f"**Market View**")
        mv = decision.get("market_view", "—")
        mv_color = "#00d4aa" if "bull" in (mv or "") else "#ef5350" if "bear" in (mv or "") else "#ffd600"
        st.markdown(f"<h3 style='color:{mv_color}'>{(mv or '—').title()}</h3>", unsafe_allow_html=True)
    with col_conf:
        st.markdown(f"**Confidence**")
        conf = decision.get("confidence", 0) or 0
        st.markdown(f"<h3>{conf*100:.0f}%</h3>", unsafe_allow_html=True)

    st.markdown("#### Claude's Reasoning")
    reasoning = decision.get("reasoning", "—")
    risk_note = decision.get("risk_note", "—")
    st.info(f"**Decision:** {reasoning}")
    st.warning(f"**Risk Note:** {risk_note}")

    # validation report
    val = decision.get("validation_report", {}) or {}
    if val.get("corrections") or val.get("rejections"):
        st.error(f"**Risk Validator — {val.get('status', 'CORRECTED')}**\n" +
                 "\n".join(val.get("corrections", []) + val.get("rejections", [])))
    else:
        st.success("**Risk Validator:** APPROVED — all constraints satisfied")

    st.divider()

# ── trades table ──────────────────────────────────────────────────────────────
if selected_day > 0 and trades_today:
    st.markdown("#### Trades Executed Today")
    trade_rows = []
    for t in trades_today:
        trade_rows.append({
            "Action": t["action"],
            "Asset": t["asset"],
            "Price": fmt_usd(t["price"]),
            "Qty": f"{t['quantity']:.6f}",
            "Notional": fmt_usd(t["notional"]),
            "Fee+Slip": fmt_usd(t.get("total_cost", 0)),
        })
    st.dataframe(pd.DataFrame(trade_rows), hide_index=True, use_container_width=True)
elif selected_day > 0:
    st.info("No trades executed today — Claude held current allocations.")

st.divider()

# ── benchmark comparison ──────────────────────────────────────────────────────
benchmarks = snap.get("benchmarks", {})
if benchmarks:
    st.markdown("#### Benchmark Comparison")
    bench_cols = st.columns(len(benchmarks) + 1)
    with bench_cols[0]:
        st.metric("Claude", fmt_usd(total_value), delta=fmt_pct(pnl_pct))
    for i, (key, bdata) in enumerate(benchmarks.items()):
        with bench_cols[i + 1]:
            bval = bdata.get("value", starting_capital)
            bret = bdata.get("return_pct", 0)
            delta_vs_claude = pnl_pct - bret
            st.metric(
                BENCHMARK_LABELS.get(key, key),
                fmt_usd(bval),
                delta=fmt_pct(bret),
            )

# ── market signals panel ──────────────────────────────────────────────────────
if selected_day > 0:
    with st.expander("Market Signals (what Claude saw)"):
        signals = snap.get("market_signals", {})
        if signals:
            rows = []
            for asset, sig in signals.items():
                rows.append({
                    "Asset": asset,
                    "Price": fmt_usd(sig.get("price", 0)),
                    "1D Ret": fmt_pct(sig.get("return_1d") or 0),
                    "7D Ret": fmt_pct(sig.get("return_7d") or 0),
                    "RSI-14": sig.get("rsi_14", "—"),
                    "Trend": sig.get("trend", "—"),
                    "Drawdown": fmt_pct(sig.get("drawdown_from_30d_high") or 0),
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

# ── final reveal (day 7 only) ─────────────────────────────────────────────────
if selected_day == len(snapshots) - 1 and selected_day > 0:
    st.divider()
    st.markdown("## 🏁 Final Verdict")
    final_col1, final_col2 = st.columns(2)
    with final_col1:
        st.markdown(f"**Started with:** {fmt_usd(starting_capital)}")
        st.markdown(f"**Ended with:** {fmt_usd(total_value)}")
        st.markdown(f"**Net PnL:** {fmt_usd(pnl_abs)} ({fmt_pct(pnl_pct)})")
        st.markdown(f"**Max Drawdown:** {fmt_pct(snap.get('max_drawdown', 0))}")
        st.markdown(f"**Total Trades:** {sum(len(s.get('trades_today',[])) for s in snapshots)}")
    with final_col2:
        # who won?
        bench_returns = {k: v.get("return_pct", 0) for k, v in benchmarks.items()}
        beaten = [BENCHMARK_LABELS.get(k, k) for k, v in bench_returns.items() if pnl_pct > v]
        lost_to = [BENCHMARK_LABELS.get(k, k) for k, v in bench_returns.items() if pnl_pct <= v]
        if beaten:
            st.success(f"Claude beat: {', '.join(beaten)}")
        if lost_to:
            st.error(f"Claude lost to: {', '.join(lost_to)}")
