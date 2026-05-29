import yaml
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path


def load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)
    _validate(cfg)
    return cfg


def _validate(cfg: dict):
    r = cfg.get("risk", {})
    assert r.get("max_asset_allocation", 0) <= 1.0, "max_asset_allocation must be <= 1.0"
    assert r.get("max_total_crypto_exposure", 0) <= 1.0, "max_total_crypto_exposure must be <= 1.0"
    assert not r.get("leverage_enabled", True), "Leverage must be disabled for episode 1"
    assert not r.get("shorting_enabled", True), "Shorting must be disabled for episode 1"
    universe = cfg.get("assets", {}).get("universe", [])
    assert len(universe) > 0, "Asset universe cannot be empty"


def finalize_config(cfg: dict, start_date: str, end_date: str, config_path: str) -> dict:
    """Lock dates and generate run_id. Writes the final config back to disk."""
    run_id = f"ep01_{start_date.replace('-', '')}_{uuid.uuid4().hex[:6]}"
    cfg["episode"]["run_id"] = run_id
    cfg["episode"]["start_date"] = start_date
    cfg["episode"]["end_date"] = end_date
    cfg["episode"]["locked_at"] = datetime.now(timezone.utc).isoformat()

    with open(config_path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    return cfg


def get_run_dir(cfg: dict, base: str = "runs") -> Path:
    run_id = cfg["episode"]["run_id"]
    run_dir = Path(base) / run_id
    for sub in ["market_packets", "claude_raw", "decisions", "portfolio_states", "exports/snapshots", "exports/charts"]:
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    return run_dir
