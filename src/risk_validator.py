import json
from pathlib import Path
from datetime import datetime, timezone

UNIVERSE = {"BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "LINK", "AVAX", "CASH"}


def validate(decision: dict, cfg: dict) -> dict:
    """
    Validates Claude's decision against all hard risk rules.
    Returns a validated decision with a validation_report attached.
    """
    r = cfg["risk"]
    max_per_asset = r["max_asset_allocation"]
    max_crypto = r["max_total_crypto_exposure"]
    min_cash = r["min_cash_allocation"]

    allocs = decision.get("target_allocations", {})
    corrections = []
    rejections = []

    # 1. unknown assets
    unknown = set(allocs.keys()) - UNIVERSE
    if unknown:
        for k in unknown:
            rejections.append(f"REJECTED unknown asset: {k} (removed)")
            del allocs[k]

    # 2. fill missing universe assets with 0
    for asset in UNIVERSE:
        if asset not in allocs:
            allocs[asset] = 0.0

    # 3. no negative allocations
    for asset, pct in allocs.items():
        if pct < 0:
            corrections.append(f"CORRECTED {asset}: negative allocation {pct:.4f} → 0.0 (no shorting)")
            allocs[asset] = 0.0

    # 4. per-asset cap
    for asset, pct in allocs.items():
        if asset != "CASH" and pct > max_per_asset:
            corrections.append(
                f"CORRECTED {asset}: {pct:.4f} → {max_per_asset:.4f} (exceeds {max_per_asset*100:.0f}% cap)"
            )
            allocs[asset] = max_per_asset

    # 5. total crypto exposure cap
    crypto_total = sum(v for k, v in allocs.items() if k != "CASH")
    if crypto_total > max_crypto:
        scale = max_crypto / crypto_total
        for asset in list(allocs.keys()):
            if asset != "CASH":
                old = allocs[asset]
                allocs[asset] = round(old * scale, 6)
        corrections.append(
            f"CORRECTED crypto exposure: {crypto_total:.4f} → {max_crypto:.4f} (scaled all crypto positions)"
        )

    # 6. minimum cash
    crypto_sum = sum(v for k, v in allocs.items() if k != "CASH")
    cash_implied = 1.0 - crypto_sum
    if cash_implied < min_cash:
        # scale down crypto to make room for min cash
        scale = (1.0 - min_cash) / crypto_sum if crypto_sum > 0 else 0
        for asset in list(allocs.keys()):
            if asset != "CASH":
                allocs[asset] = round(allocs[asset] * scale, 6)
        corrections.append(
            f"CORRECTED cash: implied {cash_implied:.4f} < minimum {min_cash:.4f} — crypto scaled down"
        )

    # 7. normalize to exactly 1.0
    crypto_sum = sum(v for k, v in allocs.items() if k != "CASH")
    allocs["CASH"] = round(max(1.0 - crypto_sum, 0.0), 6)
    total = sum(allocs.values())
    if abs(total - 1.0) > 0.0001:
        # hard normalize
        factor = 1.0 / total
        for asset in allocs:
            allocs[asset] = round(allocs[asset] * factor, 6)
        allocs["CASH"] = round(allocs["CASH"], 6)
        # fix rounding residual on CASH
        residual = 1.0 - sum(v for k, v in allocs.items() if k != "CASH")
        allocs["CASH"] = round(max(residual, 0.0), 6)

    status = "APPROVED" if not corrections and not rejections else "CORRECTED" if not rejections else "CORRECTED_WITH_REJECTIONS"

    report = {
        "status": status,
        "corrections": corrections,
        "rejections": rejections,
        "allocation_sum": round(sum(allocs.values()), 6),
        "crypto_exposure": round(sum(v for k, v in allocs.items() if k != "CASH"), 6),
        "cash_allocation": round(allocs.get("CASH", 0), 6),
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }

    if corrections or rejections:
        print(f"  [RISK VALIDATOR] {status}")
        for c in corrections:
            print(f"    ⚠  {c}")
        for r_ in rejections:
            print(f"    ✗  {r_}")
    else:
        print(f"  [RISK VALIDATOR] APPROVED — all constraints satisfied")

    decision["target_allocations"] = allocs
    decision["validation_report"] = report
    return decision


def save_decision(decision: dict, day: int, run_dir: Path):
    path = run_dir / "decisions" / f"day_{day:02d}_decision.json"
    with open(path, "w") as f:
        json.dump(decision, f, indent=2)
