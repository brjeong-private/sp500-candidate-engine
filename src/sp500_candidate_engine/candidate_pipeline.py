from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.analytics.phase45_workflow import (
    Phase45Summary,
    run_phase45_workflow,
)
from sp500_candidate_engine.config import Settings

_ANALYTICS_CONFIGS_BY_HORIZON = {
    5: ("model_lightgbm_v2.yaml", "label_forward_return_5d_v2.yaml"),
    20: ("model_lightgbm_20d_v1.yaml", "label_forward_return_20d_v1.yaml"),
}


def _manifest_cutoff(manifest: dict[str, object], manifest_path: Path) -> datetime:
    value = manifest.get("cutoff_at")
    if not isinstance(value, str):
        raise ValueError(f"Export manifest has no cutoff_at: {manifest_path}")
    cutoff_at = datetime.fromisoformat(value)
    if cutoff_at.tzinfo is None:
        raise ValueError(f"Export manifest cutoff_at must be timezone-aware: {manifest_path}")
    return cutoff_at


def find_export_for_date(
    output_root: Path,
    target_date: date,
    *,
    decision_cutoff: datetime | None = None,
) -> Path:
    if decision_cutoff is not None and decision_cutoff.tzinfo is None:
        raise ValueError("decision_cutoff must be timezone-aware")
    matches: list[tuple[Path, datetime, date]] = []
    for candidate in Path(output_root).glob("*"):
        manifest_path = candidate / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("calendar_end") == target_date.isoformat():
            cutoff_at = _manifest_cutoff(manifest, manifest_path)
            if decision_cutoff is None or cutoff_at <= decision_cutoff:
                calendar_start = manifest.get("calendar_start")
                if calendar_start is None:
                    calendar_start = target_date.isoformat()
                if not isinstance(calendar_start, str):
                    raise ValueError(f"Invalid calendar_start: {manifest_path}")
                matches.append(
                    (candidate, cutoff_at, date.fromisoformat(calendar_start))
                )
    if not matches:
        raise FileNotFoundError(
            f"No Qlib export ends at {target_date} within the requested cutoff"
        )
    distinct_cutoffs = {cutoff_at for _, cutoff_at, _ in matches}
    if decision_cutoff is None and len(distinct_cutoffs) > 1:
        raise RuntimeError(
            f"Multiple cutoffs exist for {target_date}; decision_cutoff is required"
        )
    return max(
        matches,
        key=lambda match: (match[1], -match[2].toordinal(), match[0].name),
    )[0]


def run_candidate_date(
    settings: Settings,
    *,
    target_date: date,
    repository_root: Path,
    horizon_sessions: int = 5,
    decision_cutoff: datetime | None = None,
) -> Phase45Summary:
    root = Path(repository_root)
    try:
        model_filename, label_filename = _ANALYTICS_CONFIGS_BY_HORIZON[
            horizon_sessions
        ]
    except KeyError as error:
        supported = ", ".join(str(value) for value in _ANALYTICS_CONFIGS_BY_HORIZON)
        raise ValueError(
            f"Unsupported candidate horizon {horizon_sessions}; expected one of {supported}"
        ) from error
    required_model_keys = [
        "seed",
        "prediction_semantics",
        "model",
        "walk_forward",
        "baselines",
    ]
    if horizon_sessions == 20:
        required_model_keys.extend(("model_purpose", "return_policy", "experiment"))
    model_config = load_versioned_config(
        root / "config" / "analytics" / model_filename,
        required_keys=tuple(required_model_keys),
    )
    label_config = load_versioned_config(
        root / "config" / "analytics" / label_filename,
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
            decision_cutoff=decision_cutoff,
        ),
        model_config=model_config,
        label_config=label_config,
        selection_config=selection_config,
        output_root=root / "data" / "output" / "phase45",
    )
