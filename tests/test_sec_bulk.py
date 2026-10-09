from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from sp500_candidate_engine.sec_bulk import parse_sec_bulk

CIK = "0000320193"
CUTOFF = datetime(2026, 10, 9, 9, 30, tzinfo=UTC)


def _zip_json(files: dict[str, object]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, json.dumps(payload))
    return buffer.getvalue()


def _submissions() -> bytes:
    recent = {
        "accessionNumber": [
            "0000320193-26-000001",
            "0000320193-26-000002",
            "0000320193-26-000003",
        ],
        "filingDate": ["2026-10-08", "2026-10-08", "2026-10-09"],
        "reportDate": ["2026-09-30", "2026-09-30", "2026-09-30"],
        "acceptanceDateTime": [
            "2026-10-08T20:00:00Z",
            "2026-10-09T09:00:00Z",
            "2026-10-09T10:00:00Z",
        ],
        "form": ["10-Q", "10-Q/A", "10-Q"],
        "primaryDocument": ["q3.htm", "q3a.htm", "future.htm"],
    }
    return _zip_json(
        {
            "CIK0000320193.json": {
                "cik": 320193,
                "name": "Example",
                "filings": {"recent": recent},
            },
            "CIK0000000001.json": {
                "cik": 1,
                "filings": {"recent": recent},
            },
        }
    )


def _companyfacts() -> bytes:
    current = {
        "start": "2026-07-01",
        "end": "2026-09-30",
        "val": 100,
        "accn": "0000320193-26-000001",
        "fy": 2026,
        "fp": "Q3",
        "form": "10-Q",
        "filed": "2026-10-08",
        "frame": "CY2026Q3",
    }
    duplicate = dict(current)
    amendment = {
        **current,
        "val": 101,
        "accn": "0000320193-26-000002",
        "form": "10-Q/A",
    }
    future = {
        **current,
        "val": 999,
        "accn": "0000320193-26-000003",
    }
    instant = {
        "end": "2026-09-30",
        "val": 500,
        "accn": "0000320193-26-000001",
        "fy": 2026,
        "fp": "Q3",
        "form": "10-Q",
        "filed": "2026-10-08",
        "frame": "CY2026Q3I",
    }
    payload = {
        "cik": 320193,
        "entityName": "Example",
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [current, duplicate, amendment, future]}},
                "Assets": {"units": {"USD": [instant]}},
                "CustomMetric": {"units": {"USD": [current]}},
            }
        },
    }
    return _zip_json({"CIK0000320193.json": payload})


def test_future_filings_and_their_facts_are_excluded() -> None:
    result = parse_sec_bulk(
        _submissions(),
        _companyfacts(),
        allowed_ciks={CIK},
        cutoff_at=CUTOFF,
    )

    assert [filing.accession for filing in result.filings] == [
        "0000320193-26-000001",
        "0000320193-26-000002",
    ]
    assert {fact.accession for fact in result.facts} == {
        "0000320193-26-000001",
        "0000320193-26-000002",
    }
    assert result.summary["filings_after_cutoff"] == 1
    assert result.summary["facts_after_cutoff"] == 1
    assert all(fact.accepted_at <= CUTOFF for fact in result.facts)


def test_amendments_are_separate_and_duplicate_contexts_are_deduped() -> None:
    result = parse_sec_bulk(
        _submissions(),
        _companyfacts(),
        allowed_ciks={320193},
        cutoff_at=CUTOFF,
    )
    revenues = [fact for fact in result.facts if fact.concept == "Revenues"]

    assert len(revenues) == 2
    assert {fact.amendment for fact in revenues} == {False, True}
    assert len({fact.context_hash for fact in revenues}) == 2
    assert all(fact.context_hash for fact in revenues)
    assert result.summary["duplicate_contexts"] == 1


def test_duration_and_cumulative_metadata_are_retained() -> None:
    result = parse_sec_bulk(
        _submissions(),
        _companyfacts(),
        allowed_ciks={CIK},
        cutoff_at=CUTOFF,
    )
    revenue = next(
        fact for fact in result.facts if fact.concept == "Revenues" and not fact.amendment
    )
    assets = next(fact for fact in result.facts if fact.concept == "Assets")

    assert revenue.context_type == "duration"
    assert revenue.period_start.isoformat() == "2026-07-01"
    assert revenue.period_end.isoformat() == "2026-09-30"
    assert revenue.duration_days == 91
    assert (revenue.fy, revenue.fp, revenue.frame) == (2026, "Q3", "CY2026Q3")
    assert assets.context_type == "instant"
    assert assets.period_start is None
    assert assets.duration_days is None
    assert assets.frame == "CY2026Q3I"


def test_results_are_immutable_and_summary_is_sanitized() -> None:
    result = parse_sec_bulk(
        _submissions(),
        _companyfacts(),
        allowed_ciks={CIK},
        cutoff_at=CUTOFF,
    )

    with pytest.raises(FrozenInstanceError):
        result.filings[0].form = "8-K"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.summary["filings_included"] = 0  # type: ignore[index]
    assert all(isinstance(value, int) for value in result.summary.values())
