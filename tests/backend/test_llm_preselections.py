from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.repositories.llm_preselections import LLMPreselectionRepository
from backend.app.routers import llm_preselections
from sp500_candidate_engine.database import Database

RUN_ID = UUID("10000000-0000-0000-0000-000000000001")
OTHER_RUN_ID = UUID("10000000-0000-0000-0000-000000000002")
RANKING_RUN_ID = UUID("20000000-0000-0000-0000-000000000001")
CONTEXT_ID = UUID("30000000-0000-0000-0000-000000000001")
INSTRUMENT_ID = UUID("40000000-0000-0000-0000-000000000001")
DAY = date(2026, 10, 1)
NOW = datetime(2026, 10, 1, 18, tzinfo=UTC)


def preselection_row(
    *,
    run_id: UUID = RUN_ID,
    session: date = DAY,
    status: str = "SUCCEEDED",
    failure_code: str | None = None,
    candidates: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if candidates is None:
        candidates = [
            {
                "run_id": run_id,
                "instrument_id": INSTRUMENT_ID,
                "position": 1,
                "score": Decimal("91.2500"),
                "first_stage_rank": 2,
                "final_rank": 1,
                "evidence_quality": "HIGH",
                "reason_codes": ["EARNINGS_MOMENTUM"],
                "symbol": "OLD",
                "company_name": "Stored Identity Inc.",
                "sector": "Industrials",
            }
        ]
    return {
        "run_id": run_id,
        "llm_ranking_run_id": RANKING_RUN_ID,
        "execution_context_id": CONTEXT_ID,
        "price_session_date": session,
        "cutoff_at": NOW,
        "generated_at": NOW,
        "valid_until": None,
        "policy_version": "llm-preselection-v1",
        "prompt_version": "prompt-v1",
        "deployment": "gpt-test",
        "evidence_schema_version": "evidence-v1",
        "requested_count": 20,
        "selected_count": len(candidates),
        "status": status,
        "ranking_status": status,
        "failure_code": failure_code,
        "created_at": NOW,
        "candidates": candidates,
        "_anchor": NOW,
    }


@pytest.fixture
def database():
    return MagicMock(spec=Database)


@pytest.fixture
def client(database):
    application = FastAPI()
    application.state.database = database
    application.include_router(llm_preselections.router)
    return TestClient(application)


def capture(monkeypatch, rows):
    calls = []

    def fetch(self, sql, parameters):
        calls.append((sql, parameters))
        return [dict(row) for row in rows]

    monkeypatch.setattr(LLMPreselectionRepository, "fetch", fetch)
    return calls


def test_list_defaults_to_latest_success_per_date_and_stored_identity(monkeypatch, database):
    calls = capture(
        monkeypatch,
        [
            preselection_row(),
            preselection_row(run_id=OTHER_RUN_ID, session=DAY - timedelta(days=1)),
        ],
    )

    page = LLMPreselectionRepository(database).list_preselections(limit=1)

    assert len(page.items) == 1
    assert page.next_cursor
    assert page.items[0].candidates[0].symbol == "OLD"
    sql, parameters = calls[0]
    assert "r.status = 'SUCCEEDED'" in sql
    assert "PARTITION BY r.price_session_date" in sql
    assert "r.generated_at DESC, r.created_at DESC, r.run_id DESC" in sql
    assert "'symbol', c.symbol" in sql
    assert "ref.instrument" not in sql
    assert parameters == [None, 2]


def test_list_cursor_and_date_filters_are_bound(monkeypatch, database):
    first_calls = capture(
        monkeypatch,
        [
            preselection_row(),
            preselection_row(run_id=OTHER_RUN_ID, session=DAY - timedelta(days=1)),
        ],
    )
    first = LLMPreselectionRepository(database).list_preselections(
        start_date=DAY - timedelta(days=2),
        end_date=DAY,
        limit=1,
    )
    assert first_calls[0][1] == [None, DAY - timedelta(days=2), DAY, 2]

    calls = capture(monkeypatch, [])
    result = LLMPreselectionRepository(database).list_preselections(
        start_date=DAY - timedelta(days=2),
        end_date=DAY,
        cursor=first.next_cursor,
        limit=1,
    )

    assert result.items == []
    sql, parameters = calls[0]
    assert "r.price_session_date BETWEEN %s AND %s" in sql
    assert (
        "(r.price_session_date, r.generated_at, r.created_at, r.run_id) "
        "< (%s, %s, %s, %s)"
    ) in sql
    assert parameters == [
        NOW,
        DAY - timedelta(days=2),
        DAY,
        DAY,
        NOW,
        NOW,
        RUN_ID,
        2,
    ]


@pytest.mark.parametrize(
    ("status", "failure_code"),
    [("FAILED", "LLM_REQUEST_FAILED"), ("SHORTFALL", "INSUFFICIENT_ELIGIBLE")],
)
def test_explicit_run_inspects_non_successful_results(
    monkeypatch, database, status, failure_code
):
    row = preselection_row(
        status=status,
        failure_code=failure_code,
        candidates=[] if status == "FAILED" else None,
    )
    calls = capture(monkeypatch, [row])

    result = LLMPreselectionRepository(database).get_preselection(RUN_ID)

    assert result.status == status
    assert result.failure_code == failure_code
    assert "r.status = 'SUCCEEDED'" not in calls[0][0]
    assert "WHERE run_id = %s" in calls[0][0]
    assert calls[0][1] == [RUN_ID]


def test_list_explicit_run_includes_non_successful_result(monkeypatch, database):
    calls = capture(
        monkeypatch,
        [
            preselection_row(
                status="FAILED",
                failure_code="LLM_REQUEST_FAILED",
                candidates=[],
            )
        ],
    )

    page = LLMPreselectionRepository(database).list_preselections(run_id=RUN_ID)

    assert page.items[0].status == "FAILED"
    sql, parameters = calls[0]
    assert "r.run_id = %s" in sql
    assert "r.status = 'SUCCEEDED'" not in sql
    assert parameters == [None, RUN_ID, 101]


def test_explicit_run_not_found(monkeypatch, client):
    capture(monkeypatch, [])

    response = client.get(f"/api/v1/llm-preselections/{RUN_ID}")

    assert response.status_code == 404


def test_router_output_and_validation_before_sql(monkeypatch, client, database):
    capture(monkeypatch, [preselection_row()])

    response = client.get("/api/v1/llm-preselections")

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["execution_context_id"] == str(CONTEXT_ID)
    assert item["candidates"][0]["company_name"] == "Stored Identity Inc."
    assert client.get(
        "/api/v1/llm-preselections",
        params={"date": DAY.isoformat(), "start_date": DAY.isoformat()},
    ).status_code == 422
    assert client.get("/api/v1/llm-preselections/not-a-uuid").status_code == 422
