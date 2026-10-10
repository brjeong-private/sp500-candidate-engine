from pathlib import Path

import pytest

from sp500_candidate_engine.analytics.config import (
    AnalyticsConfigError,
    load_versioned_config,
)


def test_versioned_config_hash_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("name: model\nversion: '1'\nseed: 42\n", encoding="utf-8")

    first = load_versioned_config(path, required_keys=("seed",))
    second = load_versioned_config(path, required_keys=("seed",))

    assert first.config_hash == second.config_hash


def test_versioned_config_rejects_missing_required_key(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("name: model\nversion: '1'\n", encoding="utf-8")

    with pytest.raises(AnalyticsConfigError, match="seed"):
        load_versioned_config(path, required_keys=("seed",))
