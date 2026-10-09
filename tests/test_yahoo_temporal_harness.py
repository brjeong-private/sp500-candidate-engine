from datetime import date, datetime

import httpx
import pytest

from sp500_candidate_engine.collectors.yahoo import YahooDailyBarCollector
from sp500_candidate_engine.models import UTC, KnowledgeMode, RunSpec, UniverseMember
from sp500_candidate_engine.temporal import FutureDataViolation


def _response_with_dates(*values: datetime) -> httpx.Response:
    count = len(values)
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"exchangeTimezoneName": "America/New_York"},
                    "timestamp": [int(value.timestamp()) for value in values],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0] * count,
                                "high": [102.0] * count,
                                "low": [99.0] * count,
                                "close": [101.0] * count,
                                "volume": [1_000_000] * count,
                            }
                        ],
                        "adjclose": [{"adjclose": [101.0] * count}],
                    },
                }
            ],
        }
    }
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("GET", "https://example.invalid"),
    )


def test_yahoo_parser_fails_if_response_contains_future_bar() -> None:
    run_spec = RunSpec.for_date(date(2026, 10, 1), KnowledgeMode.HISTORICAL_RECONSTRUCTION)
    member = UniverseMember("TEST", "TEST", "Test", None, None, None)
    response = _response_with_dates(
        datetime(2026, 10, 1, 20, 0, tzinfo=UTC),
        datetime(2026, 10, 2, 20, 0, tzinfo=UTC),
    )
    with pytest.raises(FutureDataViolation):
        YahooDailyBarCollector._parse_bar(response, run_spec, member)


def test_yahoo_parser_accepts_only_target_bar() -> None:
    run_spec = RunSpec.for_date(date(2026, 10, 1), KnowledgeMode.HISTORICAL_RECONSTRUCTION)
    member = UniverseMember("TEST", "TEST", "Test", None, None, None)
    response = _response_with_dates(datetime(2026, 10, 1, 20, 0, tzinfo=UTC))
    bar = YahooDailyBarCollector._parse_bar(response, run_spec, member)
    assert bar.session_date == date(2026, 10, 1)
    assert bar.close == 101.0
