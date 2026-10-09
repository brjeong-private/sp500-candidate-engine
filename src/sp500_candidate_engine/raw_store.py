from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class RawObject:
    uri: str
    content_hash: str
    byte_size: int


class RawSnapshotWriter:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, dataset: str, target_date: date, payload: dict[str, object]) -> RawObject:
        target_dir = self.root / target_date.isoformat()
        target_dir.mkdir(parents=True, exist_ok=True)
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        content_hash = hashlib.sha256(canonical).hexdigest()
        compressed = gzip.compress(canonical, mtime=0)
        target = target_dir / f"{dataset}-{content_hash}.json.gz"
        if not target.exists():
            fd, temp_name = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(compressed)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
        return RawObject(
            uri=target.resolve().as_uri(),
            content_hash=content_hash,
            byte_size=target.stat().st_size,
        )

    def write_bytes(
        self,
        dataset: str,
        target_date: date,
        content: bytes,
        *,
        extension: str,
    ) -> RawObject:
        target_dir = self.root / target_date.isoformat()
        target_dir.mkdir(parents=True, exist_ok=True)
        content_hash = hashlib.sha256(content).hexdigest()
        target = target_dir / f"{dataset}-{content_hash}.{extension.lstrip('.')}"
        if not target.exists():
            fd, temp_name = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
        return RawObject(
            uri=target.resolve().as_uri(),
            content_hash=content_hash,
            byte_size=target.stat().st_size,
        )

    def delete_date(self, target_date: date) -> int:
        root = self.root.resolve()
        target_dir = (root / target_date.isoformat()).resolve()
        if target_dir.parent != root or target_dir.name != target_date.isoformat():
            raise ValueError(f"Unsafe raw-data deletion target: {target_dir}")
        if not target_dir.exists():
            return 0
        deleted = 0
        for path in target_dir.iterdir():
            if not path.is_file():
                raise ValueError(f"Unexpected non-file in raw date directory: {path}")
            path.unlink()
            deleted += 1
        target_dir.rmdir()
        return deleted
