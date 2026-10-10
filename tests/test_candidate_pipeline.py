import json
from datetime import date

import pytest

from sp500_candidate_engine.candidate_pipeline import find_export_for_date
from sp500_candidate_engine.cli import build_parser


def test_find_export_requires_explicit_matching_date(tmp_path) -> None:
    export = tmp_path / "run"
    export.mkdir()
    (export / "manifest.json").write_text(
        json.dumps({"calendar_end": "2026-10-09"}),
        encoding="utf-8",
    )

    assert find_export_for_date(tmp_path, date(2026, 10, 9)) == export
    with pytest.raises(FileNotFoundError):
        find_export_for_date(tmp_path, date(2026, 10, 8))


def test_candidate_cli_requires_explicit_date() -> None:
    parser = build_parser()

    args = parser.parse_args(["run-candidates", "--date", "2026-10-09"])

    assert args.date == date(2026, 10, 9)
