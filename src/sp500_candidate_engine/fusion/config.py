from __future__ import annotations

import os
from pathlib import Path

from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.fusion.policy import FusionPolicy


def fusion_enabled() -> bool:
    value = os.getenv("FUSION_ENABLED", "false").strip().lower()
    if value not in {"true", "false"}:
        raise ValueError("FUSION_ENABLED must be true or false")
    return value == "true"


def load_fusion_policy(root: Path) -> FusionPolicy:
    config = load_versioned_config(root / "config" / "analytics" / "fusion_v1.yaml")
    data = config.payload
    if data.get("model_purpose") != "MEDIUM_20D" or data.get("selection_type") != "FUSION":
        raise ValueError("Fusion supports MEDIUM_20D/FUSION only")
    values = {}
    for key in ("k", "sector_cap", "relaxed_sector_cap", "requested_count"):
        value = data.get(key)
        if type(value) is not int:
            raise ValueError(f"Fusion {key} must be an integer")
        values[key] = value
    policy = FusionPolicy(
        version=f"{config.name}:{config.version}", k=values["k"],
        sector_cap=values["sector_cap"], relaxed_sector_cap=values["relaxed_sector_cap"],
        requested_count=values["requested_count"],
    )
    for key, expected in {
        "RRF_K": policy.k, "FUSION_SECTOR_CAP": policy.sector_cap,
        "FUSION_RELAXED_SECTOR_CAP": policy.relaxed_sector_cap,
        "QUANT_TOP_N": 20, "LLM_TOP_N": 20, "FUSION_TOP_N": 20,
    }.items():
        if key in os.environ and os.environ[key] != str(expected):
            raise ValueError(f"{key} conflicts with the versioned Fusion policy")
    return policy
