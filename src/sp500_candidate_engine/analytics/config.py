from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from sp500_candidate_engine.database import _canonical_hash


class AnalyticsConfigError(ValueError):
    """Raised when a versioned analytics configuration is invalid."""


@dataclass(frozen=True)
class VersionedConfig:
    path: Path
    name: str
    version: str
    payload: dict[str, object]
    config_hash: str


def load_versioned_config(
    path: Path,
    *,
    required_keys: tuple[str, ...] = (),
) -> VersionedConfig:
    path = Path(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AnalyticsConfigError(f"Config must be a mapping: {path}")
    missing = [key for key in ("name", "version", *required_keys) if key not in payload]
    if missing:
        raise AnalyticsConfigError(f"Missing config keys {missing}: {path}")
    name = str(payload["name"]).strip()
    version = str(payload["version"]).strip()
    if not name or not version:
        raise AnalyticsConfigError(f"Config name and version are required: {path}")
    return VersionedConfig(
        path=path,
        name=name,
        version=version,
        payload=payload,
        config_hash=_canonical_hash(payload),
    )
