import json
import copy
from pathlib import Path
from datetime import datetime, timezone


def initial_state(cfg: dict) -> dict:
    return {
        "day": 0,
        "date": cfg["episode"]["start_date"],
        "total_value": float(cfg["portfolio"]["starting_capital"]),
        "cash": float(cfg["portfolio"]["starting_capital"]),
        "positions": {},      # asset -> {quantity, avg_cost, current_price, market_value, unrealized_pnl, unrealized_pnl_pct}
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "max_drawdown": 0.0,
        "peak_value": float(cfg["portfolio"]["starting_capital"]),
        "equity_curve": [float(cfg["portfolio"]["starting_capital"])],
        "trades": [],
    }


def mark_to_market(state: dict, prices: dict) -> dict:
    """Update all position values with current prices."""
    state = copy.deepcopy(state)
    total_crypto_value = 0.0

    for asset, pos in state["positions"].items():
        if pos["quantity"] > 0 and asset in prices:
            price = prices[asset]
            market_value = pos["quantity"] * price
            unrealized_pnl = market_value - (pos["quantity"] * pos["avg_cost"])
            unrealized_pnl_pct = unrealized_pnl / (pos["quantity"] * pos["avg_cost"]) if pos["avg_cost"] > 0 else 0
            pos["current_price"] = price
            pos["market_value"] = market_value
            pos["unrealized_pnl"] = unrealized_pnl
            pos["unrealized_pnl_pct"] = unrealized_pnl_pct
            total_crypto_value += market_value

    state["unrealized_pnl"] = sum(
        p["unrealized_pnl"] for p in state["positions"].values() if p["quantity"] > 0
    )
    state["total_value"] = state["cash"] + total_crypto_value

    # update drawdown
    if state["total_value"] > state["peak_value"]:
        state["peak_value"] = state["total_value"]
    dd = (state["total_value"] - state["peak_value"]) / state["peak_value"]
    if dd < state["max_drawdown"]:
        state["max_drawdown"] = dd

    return state


def execute_trades(state: dict, decision: dict, prices: dict, cfg: dict) -> dict:
    """
    Convert target_allocations from the validated decision into paper trades.
    Execution price = prices passed in (next-day open per config).
    Applies fee and slippage to every buy and sell.
    """
    state = copy.deepcopy(state)
    fee_rate = cfg["risk"]["trading_fee_bps"] / 10000
    slippage_rate = cfg["risk"]["slippage_bps"] / 10000
    total_cost_rate = fee_rate + slippage_rate

    target_allocs = decision["target_allocations"]
    total_value = state["total_value"]
    trades_today = []

    # compute target dollar values
    target_values = {}
    for asset, pct in target_allocs.items():
        if asset == "CASH":
            continue
        target_values[asset] = total_value * pct

    # compute current dollar values
    current_values = {}
    for asset in target_allocs:
        if asset == "CASH":
            continue
        pos = state["positions"].get(asset, {})
        qty = pos.get("quantity", 0)
        price = prices.get(asset, 0)
        current_values[asset] = qty * price

    # determine sells first, then buys (to free up cash)
    sells = []
    buys = []
    for asset in target_allocs:
        if asset == "CASH":
            continue
        target = target_values.get(asset, 0)
        current = current_values.get(asset, 0)
        diff = target - current
        if diff < -1.0:          # sell threshold $1
            sells.append((asset, abs(diff)))
        elif diff > 1.0:         # buy threshold $1
            buys.append((asset, diff))

    # execute sells
    for asset, notional in sells:
        price = prices.get(asset)
        if not price or price <= 0:
            continue
        cost = notional * total_cost_rate
        proceeds = notional - cost
        pos = state["positions"].get(asset, {"quantity": 0, "avg_cost": 0})
        qty_to_sell = min(notional / price, pos["quantity"])
        if qty_to_sell <= 0:
            continue

        realized = (price - pos["avg_cost"]) * qty_to_sell - cost
        state["realized_pnl"] += realized
        state["cash"] += proceeds
        pos["quantity"] -= qty_to_sell
        pos["market_value"] = pos["quantity"] * price
        state["positions"][asset] = pos

        trade = {
            "day": decision["day"],
            "date": decision["decision_date"],
            "asset": asset,
            "action": "SELL",
            "price": round(price, 6),
            "quantity": round(qty_to_sell, 8),
            "notional": round(notional, 2),
            "fee": round(notional * fee_rate, 4),
            "slippage": round(notional * slippage_rate, 4),
            "total_cost": round(cost, 4),
            "net_proceeds": round(proceeds, 2),
            "realized_pnl": round(realized, 2),
            "reason": decision.get("reasoning", ""),
        }
        trades_today.append(trade)
        print(f"    SELL {asset}: {qty_to_sell:.6f} @ ${price:,.4f} | Notional: ${notional:,.2f} | Fee+slip: ${cost:.2f}")

    # execute buys
    for asset, notional in buys:
        price = prices.get(asset)
        if not price or price <= 0:
            continue
        notional = min(notional, state["cash"] * 0.999)  # don't overspend cash
        if notional <= 0:
            continue
        cost = notional * total_cost_rate
        spend = notional + cost
        if spend > state["cash"]:
            spend = state["cash"]
            notional = spend / (1 + total_cost_rate)
            cost = spend - notional

        qty_bought = notional / price
        state["cash"] -= spend

        if asset not in state["positions"] or state["positions"][asset]["quantity"] == 0:
            state["positions"][asset] = {"quantity": 0, "avg_cost": price, "current_price": price, "market_value": 0, "unrealized_pnl": 0, "unrealized_pnl_pct": 0}

        pos = state["positions"][asset]
        old_qty = pos["quantity"]
        old_cost = pos["avg_cost"]
        new_qty = old_qty + qty_bought
        pos["avg_cost"] = ((old_qty * old_cost) + (qty_bought * price)) / new_qty if new_qty > 0 else price
        pos["quantity"] = new_qty
        pos["current_price"] = price
        pos["market_value"] = new_qty * price
        state["positions"][asset] = pos

        trade = {
            "day": decision["day"],
            "date": decision["decision_date"],
            "asset": asset,
            "action": "BUY",
            "price": round(price, 6),
            "quantity": round(qty_bought, 8),
            "notional": round(notional, 2),
            "fee": round(notional * fee_rate, 4),
            "slippage": round(notional * slippage_rate, 4),
            "total_cost": round(cost, 4),
            "net_spend": round(spend, 2),
            "reason": decision.get("reasoning", ""),
        }
        trades_today.append(trade)
        print(f"    BUY  {asset}: {qty_bought:.6f} @ ${price:,.4f} | Notional: ${notional:,.2f} | Fee+slip: ${cost:.2f}")

    if not trades_today:
        print(f"    HOLD — no trades executed (allocations within $1 threshold)")

    state["trades"].extend(trades_today)
    state["day"] = decision["day"]
    state["date"] = decision["decision_date"]

    return state


def end_of_day_snapshot(state: dict, prices: dict, decision: dict, signals: dict) -> dict:
    """Create end-of-day snapshot from an already mark-to-market'd portfolio state."""
    snapshot = {
        "day": state["day"],
        "date": state["date"],
        "total_value": round(state["total_value"], 2),
        "cash": round(state["cash"], 2),
        "realized_pnl": round(state["realized_pnl"], 2),
        "unrealized_pnl": round(state["unrealized_pnl"], 2),
        "max_drawdown": round(state["max_drawdown"], 4),
        "equity_curve": state["equity_curve"].copy(),
        "positions": {
            asset: {
                "quantity": round(pos["quantity"], 8),
                "avg_cost": round(pos["avg_cost"], 6),
                "current_price": round(pos["current_price"], 6),
                "market_value": round(pos["market_value"], 2),
                "allocation_pct": round(pos["market_value"] / state["total_value"], 4) if state["total_value"] > 0 else 0,
                "unrealized_pnl": round(pos["unrealized_pnl"], 2),
                "unrealized_pnl_pct": round(pos["unrealized_pnl_pct"], 4),
            }
            for asset, pos in state["positions"].items()
            if pos["quantity"] > 0.000001
        },
        "trades_today": [t for t in state["trades"] if t["day"] == state["day"]],
        "decision": {
            "selected_strategy": decision.get("selected_strategy"),
            "market_view": decision.get("market_view"),
            "portfolio_action": decision.get("portfolio_action"),
            "reasoning": decision.get("reasoning"),
            "risk_note": decision.get("risk_note"),
            "confidence": decision.get("confidence"),
            "validation_report": decision.get("validation_report"),
        },
        "market_signals": signals,
    }
    return snapshot


def save_portfolio_state(state: dict, day: int, run_dir: Path):
    path = run_dir / "portfolio_states" / f"day_{day:02d}_state.json"
    saveable = copy.deepcopy(state)
    with open(path, "w") as f:
        json.dump(saveable, f, indent=2, default=str)
