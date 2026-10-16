from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.app.services.pipeline_execution import PipelineExecutionService


class Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


def _service(database, loader) -> PipelineExecutionService:
    return PipelineExecutionService(
        database,
        MagicMock(),
        workspace_dir=Path("workspace"),
        model_artifact_loader=loader,
    )


def test_daily_binding_is_persisted_and_reused_after_pointer_change() -> None:
    process_run_id = uuid.uuid4()
    model_version_id = uuid.uuid4()
    weekly_run_id = uuid.uuid4()
    metadata: dict[str, object] = {}
    first_assignment = {
        "model_purpose": "SHORT_5D",
        "model_version_id": model_version_id,
        "artifact_uri": "https://models.blob.core.windows.net/artifacts/manifest.json",
        "artifact_hash": "a" * 64,
        "blob_etag": '"etag-1"',
        "blob_version_id": "version-1",
        "generation": 4,
        "weekly_run_id": weekly_run_id,
    }
    pointer = {"row": first_assignment}

    def execute(query, params):
        if "SELECT metadata" in query:
            return Result({"metadata": metadata})
        if "active_model_assignment" in query:
            return Result(pointer["row"])
        if "UPDATE ops.process_run" in query:
            metadata.update(__import__("json").loads(params[0]))
            return Result(None)
        raise AssertionError(query)

    connection = MagicMock()
    connection.execute.side_effect = execute
    database = MagicMock()
    database.connect.return_value.__enter__.return_value = connection
    artifact = SimpleNamespace(
        manifest=SimpleNamespace(model_version_id=model_version_id),
        manifest_path=Path("cache") / "manifest.json",
        model_path=Path("cache") / "lightgbm.txt",
        manifest_sha256="a" * 64,
    )
    loader = MagicMock()
    loader.load.return_value = artifact
    service = _service(database, loader)

    first = service._resolve_daily_artifact_binding(
        process_run_id=process_run_id,
        model_purpose="SHORT_5D",
    )
    pointer["row"] = {**first_assignment, "generation": 5, "artifact_hash": "b" * 64}
    second = service._resolve_daily_artifact_binding(
        process_run_id=process_run_id,
        model_purpose="SHORT_5D",
    )

    assert first is second is artifact
    assert loader.load.call_count == 2
    assert loader.load.call_args_list[1].args[0].artifact_hash == "a" * 64
    assert connection.execute.call_args_list[1].args[0].find(
        "active_model_assignment"
    ) >= 0
    assert sum(
        "active_model_assignment" in call.args[0]
        for call in connection.execute.call_args_list
    ) == 1


def test_daily_binding_falls_back_only_when_assignment_is_absent() -> None:
    connection = MagicMock()
    connection.execute.side_effect = [
        Result({"metadata": {}}),
        Result(None),
    ]
    database = MagicMock()
    database.connect.return_value.__enter__.return_value = connection
    loader = MagicMock()

    artifact = _service(database, loader)._resolve_daily_artifact_binding(
        process_run_id=uuid.uuid4(),
        model_purpose="MEDIUM_20D",
    )

    assert artifact is None
    loader.load.assert_not_called()
