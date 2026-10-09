import json
import uuid
from pathlib import Path

from sp500_candidate_engine.cli import build_parser
from sp500_candidate_engine.process_tracking import ProcessLogWriter


def test_process_log_uses_one_file_per_execution_and_flushes_lines(tmp_path: Path) -> None:
    process_run_id = uuid.uuid4()
    writer = ProcessLogWriter(tmp_path, process_run_id)
    writer.write(
        {
            "process_run_id": str(process_run_id),
            "event_type": "COLLECTION",
            "collection_date": "2026-07-09",
            "status": "FAILURE",
            "retry_required": True,
            "completed": True,
        }
    )
    writer.write(
        {
            "process_run_id": str(process_run_id),
            "event_type": "RETRY",
            "collection_date": "2026-07-09",
            "status": "SUCCESS",
            "retry_required": False,
            "retry_status": "SUCCEEDED",
            "completed": True,
        }
    )
    files = list((tmp_path / "processes").glob("*.jsonl"))
    assert files == [writer.path]
    rows = [json.loads(line) for line in writer.path.read_text(encoding="utf-8").splitlines()]
    assert [row["event_type"] for row in rows] == ["COLLECTION", "RETRY"]


def test_cli_exposes_daily_batch_retry_and_status_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["run-daily", "--date", "2026-10-08"]).command == "run-daily"
    assert (
        parser.parse_args(["run-backfill", "--start", "2026-07-09", "--end", "2026-10-08"]).command
        == "run-backfill"
    )
    process_run_id = str(uuid.uuid4())
    assert (
        parser.parse_args(
            [
                "retry-backfill",
                "--process-run-id",
                process_run_id,
                "--start",
                "2026-07-09",
                "--end",
                "2026-10-08",
            ]
        ).command
        == "retry-backfill"
    )
    assert (
        parser.parse_args(["show-process", "--process-run-id", process_run_id]).command
        == "show-process"
    )
