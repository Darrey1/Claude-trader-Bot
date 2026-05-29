import anthropic
import json
import os
from datetime import datetime, timezone
from pathlib import Path


STRATEGY_OPTIONS = [
    "trend_following",
    "momentum_rotation",
    "mean_reversion",
    "breakout",
    "risk_off",
    "balanced",
]

SYSTEM_PROMPT = """You are Claude, managing a $20,000 paper crypto portfolio for a 7-day challenge.
You receive a daily market packet and must return ONLY a valid JSON object — no prose, no markdown, no explanation outside the JSON.

Your constraints (enforced by a risk validator after you respond):
- Max 40% in any single asset
- Max 80% total crypto exposure (minimum 20% CASH at all times)
- No leverage, no short positions
- All allocations must be non-negative and sum to exactly 1.0
- Only trade assets in your universe: BTC, ETH, SOL, BNB, XRP, DOGE, LINK, AVAX, CASH

Choose one strategy per day from: trend_following, momentum_rotation, mean_reversion, breakout, risk_off, balanced

Your JSON must follow this exact schema:
{
  "day": <integer>,
  "market_view": "bullish" | "bearish" | "neutral" | "mixed",
  "selected_strategy": "<strategy_name>",
  "portfolio_action": "hold" | "rebalance" | "de_risk" | "increase_exposure",
  "target_allocations": {
    "BTC": <float>, "ETH": <float>, "SOL": <float>, "BNB": <float>,
    "XRP": <float>, "DOGE": <float>, "LINK": <float>, "AVAX": <float>, "CASH": <float>
  },
  "reasoning": "<1-3 sentence explanation of your decision>",
  "risk_note": "<main risk you are managing today>",
  "confidence": <float between 0.0 and 1.0>
}"""


def build_market_packet(
    day: int,
    decision_date: str,
    portfolio_state: dict,
    signals: dict,
    prior_decisions: list,
    benchmark_performance: dict,
    cfg: dict,
) -> str:
    r = cfg["risk"]
    packet = {
        "run_id": cfg["episode"]["run_id"],
        "day": day,
        "decision_timestamp": f"{decision_date}T00:00:00Z",
        "portfolio": {
            "total_value": round(portfolio_state["total_value"], 2),
            "cash": round(portfolio_state["cash"], 2),
            "cash_pct": round(portfolio_state["cash"] / portfolio_state["total_value"], 4),
            "positions": {
                asset: {
                    "quantity": round(pos["quantity"], 8),
                    "current_price": round(pos["current_price"], 4),
                    "market_value": round(pos["market_value"], 2),
                    "allocation_pct": round(pos["market_value"] / portfolio_state["total_value"], 4),
                    "unrealized_pnl": round(pos["unrealized_pnl"], 2),
                    "unrealized_pnl_pct": round(pos["unrealized_pnl_pct"], 4),
                }
                for asset, pos in portfolio_state.get("positions", {}).items()
                if pos["quantity"] > 0
            },
            "total_unrealized_pnl": round(portfolio_state.get("unrealized_pnl", 0), 2),
            "total_realized_pnl": round(portfolio_state.get("realized_pnl", 0), 2),
            "max_drawdown_so_far": round(portfolio_state.get("max_drawdown", 0), 4),
            "pnl_vs_start": round(portfolio_state["total_value"] - cfg["portfolio"]["starting_capital"], 2),
            "return_pct": round(
                (portfolio_state["total_value"] - cfg["portfolio"]["starting_capital"])
                / cfg["portfolio"]["starting_capital"], 4
            ),
        },
        "market": signals,
        "risk_constraints": {
            "max_per_asset": r["max_asset_allocation"],
            "max_crypto_exposure": r["max_total_crypto_exposure"],
            "min_cash": r["min_cash_allocation"],
            "leverage_enabled": r["leverage_enabled"],
            "shorting_enabled": r["shorting_enabled"],
            "fee_bps": r["trading_fee_bps"],
            "slippage_bps": r["slippage_bps"],
            "execution": r["execution_price"],
        },
        "available_strategies": STRATEGY_OPTIONS,
        "benchmarks_so_far": benchmark_performance,
        "prior_decisions": prior_decisions[-3:] if prior_decisions else [],
        "instruction": (
            "Return ONLY valid JSON matching the schema exactly. "
            "Allocations must sum to 1.0. CASH minimum is 0.20. "
            "No single asset may exceed 0.40."
        ),
    }
    return json.dumps(packet, indent=2)


def call_claude(market_packet: str, cfg: dict) -> tuple[str, dict]:
    """Send market packet to Claude, return (raw_text, parsed_json)."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    message = client.messages.create(
        model=cfg["episode"]["model"],
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Here is your daily market packet. Respond with the JSON decision only.\n\n{market_packet}",
            }
        ],
    )

    raw_text = message.content[0].text.strip()

    # parse JSON — strip markdown code fences if present
    clean = raw_text
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    parsed = json.loads(clean)
    return raw_text, parsed


def save_raw_decision(raw_text: str, day: int, run_dir: Path):
    path = run_dir / "claude_raw" / f"day_{day:02d}_raw.txt"
    path.write_text(raw_text)


def save_market_packet(packet_str: str, day: int, run_dir: Path):
    path = run_dir / "market_packets" / f"day_{day:02d}_packet.json"
    path.write_text(packet_str)


def get_decision(
    day: int,
    decision_date: str,
    portfolio_state: dict,
    signals: dict,
    prior_decisions: list,
    benchmark_performance: dict,
    cfg: dict,
    run_dir: Path,
) -> dict:
    """Full Claude decision pipeline: build packet → call API → parse → save."""
    packet_str = build_market_packet(
        day, decision_date, portfolio_state, signals,
        prior_decisions, benchmark_performance, cfg
    )
    save_market_packet(packet_str, day, run_dir)

    print(f"  Calling Claude for Day {day} ({decision_date})...")
    raw_text, parsed = call_claude(packet_str, cfg)
    save_raw_decision(raw_text, day, run_dir)

    parsed["decision_date"] = decision_date
    parsed["called_at"] = datetime.now(timezone.utc).isoformat()
    return parsed
