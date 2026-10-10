from __future__ import annotations

import argparse
import json
from pathlib import Path

from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.analytics.phase45_workflow import run_phase45_workflow
from sp500_candidate_engine.config import Settings


def discover_export(root: Path, export_run_id: str | None) -> Path:
    output = root / "data" / "output" / "qlib"
    if export_run_id:
        candidate = output / export_run_id
        if (candidate / "manifest.json").is_file():
            return candidate
        raise FileNotFoundError(f"Qlib export does not exist: {candidate}")
    candidates = sorted(
        (
            path
            for path in output.glob("*")
            if path.is_dir() and (path / "manifest.json").is_file()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No Qlib exports found under {output}")
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--export-run-id")
    parser.add_argument(
        "--model-config",
        default="config/analytics/model_lightgbm_v1.yaml",
    )
    parser.add_argument(
        "--selection-config",
        default="config/analytics/selection_v1.yaml",
    )
    parser.add_argument("--output-root", default="data/output/phase45")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    model_config = load_versioned_config(
        root / args.model_config,
        required_keys=("seed", "model", "walk_forward", "baselines"),
    )
    selection_config = load_versioned_config(
        root / args.selection_config,
        required_keys=(
            "minimum_candidates",
            "maximum_candidates",
            "sector_cap",
            "relaxed_sector_cap",
        ),
    )
    summary = run_phase45_workflow(
        settings=Settings.from_env(root / args.env_file),
        export_dir=discover_export(root, args.export_run_id),
        model_config=model_config,
        selection_config=selection_config,
        output_root=root / args.output_root,
    )
    print(json.dumps(summary.__dict__, default=str, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
