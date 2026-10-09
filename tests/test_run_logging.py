import json
from datetime import date

from sp500_candidate_engine.run_logging import PipelineLogger


def test_pipeline_logger_writes_one_json_object_per_line(tmp_path) -> None:
    logger = PipelineLogger(tmp_path)
    with logger.stage(date(2026, 10, 1), "market_collection", requested=503) as stage:
        stage.add_details(received=502)

    files = list(tmp_path.glob("*.log"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["collection_date"] == "2026-10-01"
    assert payload["pipeline_name"] == "market_collection"
    assert payload["status"] == "SUCCESS"
    assert payload["failure_reason"] is None
    assert payload["details"] == {"received": 502, "requested": 503}
    assert payload["duration_ms"] >= 0


def test_pipeline_logger_records_failure_reason(tmp_path) -> None:
    logger = PipelineLogger(tmp_path)
    try:
        with logger.stage(date(2026, 10, 1), "market_collection"):
            raise RuntimeError("provider unavailable")
    except RuntimeError:
        pass

    line = next(tmp_path.glob("*.log")).read_text(encoding="utf-8").strip()
    payload = json.loads(line)
    assert payload["status"] == "FAILURE"
    assert payload["failure_reason"] == "RuntimeError: provider unavailable"


def test_pipeline_logger_records_partial_success(tmp_path) -> None:
    logger = PipelineLogger(tmp_path)
    with logger.stage(date(2026, 10, 1), "market_collection") as stage:
        stage.mark_partial_success("1 symbols failed: PSKY")

    line = next(tmp_path.glob("*.log")).read_text(encoding="utf-8").strip()
    payload = json.loads(line)
    assert payload["status"] == "PARTIAL_SUCCESS"
    assert payload["failure_reason"] == "1 symbols failed: PSKY"
