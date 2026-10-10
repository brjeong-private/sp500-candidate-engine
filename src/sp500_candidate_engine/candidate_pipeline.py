from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.analytics.phase45_workflow import (
    Phase45Summary,
    run_phase45_workflow,
)
from sp500_candidate_engine.config import Settings


def find_export_for_date(output_root: Path, target_date: date) -> Path:
    matches: list[Path] = []
    for candidate in Path(output_root).glob("*"):
        manifest_path = candidate / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("calendar_end") == target_date.isoformat():
            matches.append(candidate)
    if not matches:
        raise FileNotFoundError(f"No Qlib export ends at {target_date}")
    return max(matches, key=lambda path: path.stat().st_mtime)


def run_candidate_date(
    settings: Settings,
    *,
    target_date: date,
    repository_root: Path,
) -> Phase45Summary:
    root = Path(repository_root)
    model_config = load_versioned_config(
        root / "config" / "analytics" / "model_lightgbm_v2.yaml",
        required_keys=("seed", "model", "walk_forward", "baselines"),
    )
    label_config = load_versioned_config(
        root / "config" / "analytics" / "label_forward_return_5d_v2.yaml",
        required_keys=("horizon_sessions", "entry_rule", "exit_rule"),
    )
    selection_config = load_versioned_config(
        root / "config" / "analytics" / "selection_v1.yaml",
        required_keys=(
            "minimum_candidates",
            "maximum_candidates",
            "sector_cap",
            "relaxed_sector_cap",
        ),
    )
    return run_phase45_workflow(
        settings=settings,
        export_dir=find_export_for_date(
            root / "data" / "output" / "qlib",
            target_date,
        ),
        model_config=model_config,
        label_config=label_config,
        selection_config=selection_config,
        output_root=root / "data" / "output" / "phase45",
    )
