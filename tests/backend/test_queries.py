from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.dependencies import get_database
from backend.app.pagination import collection_window, decode_cursor, encode_cursor, page_limit
from backend.app.repositories.base import ReadRepository
from backend.app.repositories.candidates import CandidateRepository
from backend.app.repositories.collection_data import SPECS, CollectionDataRepository
from backend.app.repositories.pipeline_runs import PipelineRunRepository
from backend.app.routers import candidates, collection_data, pipeline_runs
from backend.app.schemas.collection_data import Dataset
from sp500_candidate_engine.database import Database

ID = UUID("10000000-0000-0000-0000-000000000001")
ID2 = UUID("10000000-0000-0000-0000-000000000002")
DAY = date(2026, 10, 1)
NOW = datetime(2026, 10, 1, 18, tzinfo=UTC)


def candidate_row(position=1, session=DAY):
    return {
        "selection_run_id": ID,
        "selection_type": "QUANTITATIVE",
        "price_session_date": session,
        "cutoff_at": NOW,
        "generated_at": NOW,
        "valid_until": None,
        "scoring_run_id": ID,
        "model_version_id": ID,
        "model_name": "test-model",
        "model_version": "v2",
        "model_purpose": "MEDIUM_20D",
        "prediction_horizon_sessions": 20,
        "return_policy": "PRICE_RETURN",
        "promotion_status": "SHADOW",
        "score_semantics": "PREDICTED_20D_RETURN",
        "policy_version": "v2",
        "status": "SUCCEEDED",
        "selected_count": 5,
        "requested_count": 5,
        "instrument_id": ID if position == 1 else ID2,
        "issuer_id": ID,
        "ticker": "ABC",
        "company_name": "Example",
        "sector": "Industrials",
        "position": position,
        "score": 0.12,
        "predicted_return": 0.12,
        "rank_overall": position,
        "score_percentile": 0.9,
        "rank_sector": 1,
        "quality_status": "PASS",
        "latest_data_at": NOW,
        "reasons": [{"reason_code": "TOP_SCORE", "priority": 1, "event_revision_id": None}],
        "_anchor": NOW,
    }


def record_row(dataset: Dataset):
    common = {
        "source_snapshot_id": ID,
        "source_id": 1,
        "source_code": "test",
        "source_available_at": NOW,
        "observed_at": NOW,
        "revision_no": None,
        "_date": DAY,
    }
    identity = {"instrument_id": ID, "issuer_id": ID, "ticker": "ABC"}
    if dataset == Dataset.DAILY_BARS:
        common.update(
            identity,
            session_date=DAY,
            open=Decimal("10"),
            high=Decimal("12"),
            low=Decimal("9"),
            close=Decimal("11"),
            adjusted_close=None,
            volume=200,
            vwap=None,
            currency="USD",
            source_timestamp=NOW,
            price_adjustment_status="UNADJUSTED",
            volume_adjustment_status="UNADJUSTED",
            revision_no=2,
        )
    elif dataset == Dataset.CORPORATE_ACTIONS:
        common.update(
            identity,
            action_id=ID,
            action_type="DIVIDEND",
            effective_date=DAY,
            declaration_date=None,
            record_date=None,
            pay_date=None,
            cash_amount=Decimal("0.1"),
            currency="USD",
            split_from=None,
            split_to=None,
            revision_no=2,
        )
    elif dataset in (Dataset.NEWS, Dataset.EARNINGS):
        common.update(
            identity,
            event_id=ID,
            event_revision_id=ID,
            revision_no=2,
            event_type="NEWS" if dataset == Dataset.NEWS else "EARNINGS",
            title="Example event",
            status=None,
            published_at=NOW,
            scheduled_at=NOW,
        )
    elif dataset == Dataset.SEC_FILINGS:
        common.update(
            filing_id=ID,
            issuer_id=ID,
            accession_no="00001-26-01",
            form_type="10-K",
            period_end=DAY,
            filed_date=DAY,
            accepted_at=NOW,
            is_amendment=False,
        )
    elif dataset == Dataset.SEC_FACTS:
        common.update(
            fact_id=ID,
            filing_id=ID,
            issuer_id=ID,
            taxonomy="us-gaap",
            concept="Assets",
            unit="USD",
            period_start=None,
            period_end=DAY,
            value_numeric=Decimal("200"),
            decimals=None,
            fiscal_year=2026,
            fiscal_period="FY",
            frame=None,
        )
    elif dataset == Dataset.UNIVERSE_MEMBERS:
        common.update(
            identity,
            universe_version_id=ID,
            universe_id=ID,
            universe_code="SP500",
            as_of_date=DAY,
            provider_revision_id="revision",
            announced_at=NOW,
            effective_at=NOW,
            security_name="Example",
            sector=None,
            sub_industry=None,
            provider_symbol="ABC",
        )
    else:
        common.update(
            calendar_version="test",
            exchange_mic="XNYS",
            session_date=DAY,
            open_at=NOW,
            close_at=NOW + timedelta(hours=6),
            is_early_close=False,
            status="OPEN",
        )
    for index in range(len(SPECS[dataset].keys)):
        common[f"_key{index}"] = str(ID) if index == 0 else "1"
    return common


def run_row():
    return {
        "process_run_id": ID,
        "parent_process_run_id": None,
        "process_type": "RANGE",
        "status": "FAILED",
        "range_start": DAY,
        "range_end": DAY,
        "total_dates": 1,
        "completed_dates": 1,
        "success_dates": 0,
        "failed_dates": 1,
        "retry_required_dates": 1,
        "retry_attempted_dates": 0,
        "started_at": NOW,
        "heartbeat_at": NOW,
        "finished_at": NOW,
        "failure_reason": "Pipeline stage failed",
    }


@pytest.fixture
def database():
    return MagicMock(spec=Database)


@pytest.fixture
def client(database):
    application = FastAPI()
    application.state.database = database
    for module in (candidates, collection_data, pipeline_runs):
        application.include_router(module.router)
    return TestClient(application)


def capture(monkeypatch, repository, rows):
    calls = []

    def fetch(self, sql, parameters):
        calls.append((sql, parameters))
        return [dict(row) for row in rows]

    monkeypatch.setattr(repository, "fetch", fetch)
    return calls


def test_database_dependency_uses_existing_instance(client, database):
    assert get_database(MagicMock(app=client.app)) is database


def test_read_only_transaction(database):
    connection = database.connect.return_value.__enter__.return_value
    connection.execute.return_value.fetchall.return_value = [{"value": 1}]
    assert ReadRepository(database).fetch("SELECT value FROM example WHERE id = %s", [ID]) == [
        {"value": 1}
    ]
    assert connection.execute.call_args_list[0].args == ("SET TRANSACTION READ ONLY",)
    assert connection.execute.call_args_list[1].args[1] == [ID]
    connection.transaction.assert_called_once()


def test_cursor_binding_tampering_scope_and_key_count():
    filters = {"start": DAY, "instrument": ID}
    cursor = encode_cursor("news", filters, [str(DAY), str(ID)])
    assert decode_cursor(cursor, "news", filters, 2) == [str(DAY), str(ID)]
    for value, scope, bound, count in (
        (cursor, "earnings", filters, 2),
        (cursor, "news", {"start": DAY}, 2),
        ("!" + cursor, "news", filters, 2),
        (cursor, "news", filters, 1),
        (cursor[:-5] + "xxxxx", "news", filters, 2),
        ("A" * 5000, "news", filters, 2),
    ):
        with pytest.raises(HTTPException) as error:
            decode_cursor(value, scope, bound, count)
        assert error.value.status_code == 422


def test_inclusive_window():
    collection_window(DAY, DAY + timedelta(days=9))
    for end in (DAY - timedelta(days=1), DAY + timedelta(days=10)):
        with pytest.raises(HTTPException):
            collection_window(DAY, end)


@pytest.mark.parametrize("limit", [0, -1, 501])
def test_page_limit_at_repository_boundary(limit):
    with pytest.raises(HTTPException):
        page_limit(limit)


def test_candidates_default_all_dates_latest_success_and_opaque_keyset(monkeypatch, database):
    calls = capture(
        monkeypatch,
        CandidateRepository,
        [
            candidate_row(1),
            candidate_row(2),
            candidate_row(1, DAY - timedelta(days=1)),
        ],
    )
    repository = CandidateRepository(database)
    page = repository.list_candidates(limit=2)
    assert len(page.items) == 2 and page.next_cursor
    sql, parameters = calls[0]
    assert "PARTITION BY s.price_session_date, m.model_purpose" in sql
    assert "s.status = 'SUCCEEDED'" in sql
    assert "m.model_purpose = %s" in sql
    assert "s.generated_at DESC, s.created_at DESC, s.selection_run_id DESC" in sql
    assert "price_session_date BETWEEN" not in sql
    assert "um.universe_version_id = sc.universe_version_id" in sql
    assert "reason_detail" not in sql
    assert parameters == [None, "MEDIUM_20D", 3]
    continuation_calls = capture(
        monkeypatch, CandidateRepository, [candidate_row(1, DAY - timedelta(days=1))]
    )
    last_page = repository.list_candidates(cursor=page.next_cursor, limit=2)
    assert last_page.next_cursor is None
    assert last_page.items[0].price_session_date < DAY
    assert continuation_calls[0][1] == [
        NOW,
        "MEDIUM_20D",
        DAY,
        DAY,
        2,
        ID2,
        3,
    ]
    assert "s.created_at <= boundary.anchor" in continuation_calls[0][0]
    assert "(c.position, c.instrument_id) > (%s, %s)" in continuation_calls[0][0]


def test_candidates_explicit_run_filters_and_sql_parameterization(monkeypatch, database):
    injection = "'; DROP TABLE selection.candidate; --"
    calls = capture(monkeypatch, CandidateRepository, [])
    assert (
        CandidateRepository(database)
        .list_candidates(
            selection_run_id=ID,
            start_date=DAY,
            end_date=DAY,
            ticker=injection,
            instrument_id=ID,
            issuer_id=ID,
        )
        .items
        == []
    )
    sql, values = calls[0]
    assert "s.selection_run_id = %s" in sql and "s.status = 'SUCCEEDED'" not in sql
    assert "m.model_purpose = %s" not in sql
    assert injection not in sql and injection in values
    assert values == [None, ID, DAY, DAY, injection, ID, ID, 101]


def test_candidates_explicit_short_model_has_no_fallback(monkeypatch, database):
    calls = capture(monkeypatch, CandidateRepository, [])

    page = CandidateRepository(database).list_candidates(model_purpose="SHORT_5D")

    assert page.items == []
    sql, values = calls[0]
    assert "m.model_purpose = %s" in sql
    assert values == [None, "SHORT_5D", 101]
    assert "COALESCE(m.model_purpose" not in sql


@pytest.mark.parametrize("dataset", list(Dataset))
def test_collection_schemas_provenance_and_sql(monkeypatch, client, dataset):
    calls = capture(monkeypatch, CollectionDataRepository, [record_row(dataset)])
    response = client.get(
        f"/api/v1/collection-data/{dataset}",
        params={
            "start_date": DAY.isoformat(),
            "end_date": (DAY + timedelta(days=9)).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["dataset"] == dataset
    assert item["source_snapshot_id"] == str(ID)
    assert item["source_available_at"].endswith("Z")
    assert not {"metadata", "storage_uri", "payload_hash", "source_url"} & item.keys()
    sql, parameters = calls[0]
    assert "BETWEEN %s AND %s" in sql
    assert (
        " AT TIME ZONE 'UTC'" in sql
        if dataset in (Dataset.NEWS, Dataset.EARNINGS, Dataset.SEC_FACTS)
        else True
    )
    assert "metadata" not in sql and "storage_uri" not in sql
    assert parameters == [DAY, DAY + timedelta(days=9), 101]
    if dataset == Dataset.DAILY_BARS:
        assert "DISTINCT ON (instrument_id, session_date, source_id)" in sql
        assert "revision_no DESC" in sql
    if dataset in (Dataset.NEWS, Dataset.EARNINGS):
        assert f"e.event_type = '{dataset.name}'" in sql
        assert "event.event_instrument" in sql


def test_collection_cursor_continuation_binds_entities(monkeypatch, database):
    calls = capture(
        monkeypatch,
        CollectionDataRepository,
        [
            record_row(Dataset.DAILY_BARS),
            record_row(Dataset.DAILY_BARS),
        ],
    )
    repository = CollectionDataRepository(database)
    page = repository.list_records(
        Dataset.DAILY_BARS,
        start_date=DAY,
        end_date=DAY,
        instrument_id=ID,
        limit=1,
    )
    assert page.next_cursor
    repository.list_records(
        Dataset.DAILY_BARS,
        start_date=DAY,
        end_date=DAY,
        instrument_id=ID,
        cursor=page.next_cursor,
        limit=1,
    )
    assert "(_key0, _key1) > (%s, %s)" in calls[1][0]
    assert calls[1][1] == [DAY, DAY, ID, DAY, DAY, str(ID), "1", 2]
    with pytest.raises(HTTPException):
        repository.list_records(
            Dataset.DAILY_BARS,
            start_date=DAY,
            end_date=DAY,
            instrument_id=ID2,
            cursor=page.next_cursor,
        )


@pytest.mark.parametrize("dataset", [Dataset.SEC_FILINGS, Dataset.SEC_FACTS])
def test_issuer_level_filters_do_not_duplicate_rows(monkeypatch, database, dataset):
    calls = capture(monkeypatch, CollectionDataRepository, [])
    CollectionDataRepository(database).list_records(
        dataset,
        start_date=DAY,
        end_date=DAY,
        ticker="ABC",
        instrument_id=ID,
        issuer_id=ID2,
    )
    sql, values = calls[0]
    assert "EXISTS (SELECT 1 FROM ref.instrument fi" in sql
    assert "ident.valid_from <=" in sql
    assert values == [DAY, DAY, ID2, ID, "ABC", 101]


def test_collection_ticker_is_a_parameter_not_sql(monkeypatch, database):
    ticker = "'; DROP TABLE market.daily_bar; --"
    calls = capture(monkeypatch, CollectionDataRepository, [])
    CollectionDataRepository(database).list_records(
        Dataset.DAILY_BARS, start_date=DAY, end_date=DAY, ticker=ticker
    )
    assert ticker not in calls[0][0]
    assert calls[0][1] == [DAY, DAY, ticker, 101]


def test_events_keep_unassociated_events(monkeypatch, database):
    row = record_row(Dataset.NEWS)
    row.update(instrument_id=None, issuer_id=None, ticker=None, _key1="")
    calls = capture(monkeypatch, CollectionDataRepository, [row])
    result = CollectionDataRepository(database).list_records(
        Dataset.NEWS,
        start_date=DAY,
        end_date=DAY,
    )
    assert result.items[0].instrument_id is None
    assert "LEFT JOIN event.event_instrument" in calls[0][0]


@pytest.mark.parametrize(
    "path,parameters",
    [
        ("/api/v1/candidates", {"date": "2026-10-01", "start_date": "2026-10-01"}),
        ("/api/v1/candidates", {"start_date": "2026-10-01"}),
        ("/api/v1/candidates", {"start_date": "2026-10-02", "end_date": "2026-10-01"}),
        ("/api/v1/candidates", {"selection_run_id": "bad-uuid"}),
        ("/api/v1/candidates", {"model_purpose": "UNKNOWN"}),
        ("/api/v1/candidates", {"limit": 501}),
        ("/api/v1/candidates", {"limit": 0}),
        ("/api/v1/collection-data/news", {"start_date": "2026-10-01", "end_date": "2026-10-11"}),
        ("/api/v1/collection-data/news", {}),
        (
            "/api/v1/collection-data/not-a-table",
            {"start_date": "2026-10-01", "end_date": "2026-10-01"},
        ),
        (
            "/api/v1/collection-data/exchange-sessions",
            {
                "start_date": "2026-10-01",
                "end_date": "2026-10-01",
                "ticker": "ABC",
            },
        ),
        ("/api/v1/pipeline-runs", {"status": "WRONG"}),
        ("/api/v1/pipeline-runs", {"process_type": "SQL TABLE"}),
        ("/api/v1/pipeline-runs", {"end_date": "2026-10-01"}),
        ("/api/v1/pipeline-runs/not-a-uuid", {}),
    ],
)
def test_validation_before_sql(client, database, path, parameters):
    assert client.get(path, params=parameters).status_code == 422
    database.connect.assert_not_called()


def test_api_candidate_output_and_openapi_shapes(monkeypatch, client):
    capture(monkeypatch, CandidateRepository, [candidate_row()])
    response = client.get("/api/v1/candidates")
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["predicted_return"] == 0.12
    assert item["model_purpose"] == "MEDIUM_20D"
    assert item["prediction_horizon_sessions"] == 20
    assert item["return_policy"] == "PRICE_RETURN"
    assert item["promotion_status"] == "SHADOW"
    assert item["reasons"] == [
        {"reason_code": "TOP_SCORE", "priority": 1, "event_revision_id": None}
    ]
    schema = client.get("/openapi.json").json()
    assert schema["components"]["schemas"]["Candidate"]["properties"]["instrument_id"] == {
        "type": "string",
        "format": "uuid",
        "title": "Instrument Id",
    }
    assert (
        schema["components"]["schemas"]["DailyBar"]["properties"]["session_date"]["format"]
        == "date"
    )
    assert schema["components"]["schemas"]["PipelineRun"]["properties"]["started_at"]["format"] == (
        "date-time"
    )
    collection_pages = [
        definition
        for name, definition in schema["components"]["schemas"].items()
        if name.startswith("Page_") and "discriminator" in str(definition)
    ]
    assert len(collection_pages) == 1
    assert "oneOf" in collection_pages[0]["properties"]["items"]["items"]
    for module in (candidates, collection_data, pipeline_runs):
        for route in module.router.routes:
            assert not inspect.iscoroutinefunction(route.endpoint)


def test_api_candidate_model_purpose_filter(monkeypatch, client):
    calls = capture(monkeypatch, CandidateRepository, [])

    response = client.get(
        "/api/v1/candidates",
        params={"model_purpose": "SHORT_5D"},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert calls[0][1] == [None, "SHORT_5D", 101]


def test_runs_api_status_overlay_filters_and_cursor(monkeypatch, client):
    first = run_row()
    second = dict(first, process_run_id=ID2)
    calls = capture(monkeypatch, PipelineRunRepository, [first, second])
    response = client.get(
        "/api/v1/pipeline-runs",
        params={
            "date": DAY.isoformat(),
            "status": "FAILED",
            "process_type": "RANGE",
            "limit": 1,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["next_cursor"]
    assert payload["items"][0]["status"] == "FAILED"
    assert "log_uri" not in payload["items"][0]
    assert "COALESCE(r.status, p.status) = %s" in calls[0][0]
    assert "ops.backend_pipeline_request" in calls[0][0]
    assert calls[0][1] == [DAY, DAY, "FAILED", "RANGE", 2]
    continuation = client.get(
        "/api/v1/pipeline-runs",
        params={
            "date": DAY.isoformat(),
            "status": "FAILED",
            "process_type": "RANGE",
            "limit": 1,
            "cursor": payload["next_cursor"],
        },
    )
    assert continuation.status_code == 200
    assert "(p.started_at, p.process_run_id) < (%s, %s)" in calls[1][0]


def test_running_api_job_does_not_inherit_collection_finished_at(monkeypatch, client):
    running = dict(run_row(), status="RUNNING", finished_at=None, failure_reason=None)
    calls = capture(monkeypatch, PipelineRunRepository, [running])
    response = client.get(f"/api/v1/pipeline-runs/{ID}")
    assert response.status_code == 200
    assert response.json()["status"] == "RUNNING"
    assert response.json()["finished_at"] is None
    sql = calls[0][0]
    assert "CASE WHEN r.process_run_id IS NOT NULL THEN r.finished_at" in sql
    assert "ELSE p.finished_at END AS finished_at" in sql
    assert "COALESCE(r.finished_at, p.finished_at)" not in sql


def test_missing_run_and_dates_are_404(monkeypatch, client):
    capture(monkeypatch, PipelineRunRepository, [])
    assert client.get(f"/api/v1/pipeline-runs/{ID}").status_code == 404
    assert client.get(f"/api/v1/pipeline-runs/{ID}/dates").status_code == 404


def test_range_child_dates_counts_and_cursor(monkeypatch, client):
    child = {
        "process_run_id": ID2,
        "collection_date": DAY,
        "attempt_no": 1,
        "event_type": "COLLECTION",
        "status": "FAILED",
        "started_at": NOW,
        "finished_at": NOW,
        "duration_ms": Decimal("123.1"),
        "collected_item_count": 2,
        "collected_counts": {"daily_bars": 2},
        "failure_reason": "Collection attempt failed",
        "retry_required": True,
        "retry_status": "PENDING",
        "completed": True,
        "updated_at": NOW,
    }
    calls = []

    def fetch(self, sql, parameters):
        calls.append((sql, parameters))
        if "FROM ops.process_date_status" in sql:
            return [dict(child), dict(child, attempt_no=2)]
        return [run_row()]

    monkeypatch.setattr(PipelineRunRepository, "fetch", fetch)
    response = client.get(f"/api/v1/pipeline-runs/{ID}/dates", params={"limit": 1})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["items"][0]["process_run_id"] == str(ID2)
    assert payload["items"][0]["collected_counts"]["daily_bars"] == 2
    assert payload["next_cursor"]
    sql = calls[1][0]
    assert "p.parent_process_run_id = %s" in sql
    assert "'bars'" in sql and "'facts'" in sql
    assert "d.failure_reason AS" not in sql
    assert calls[1][1] == [ID, ID, 2]
    continuation = client.get(
        f"/api/v1/pipeline-runs/{ID}/dates",
        params={
            "limit": 1,
            "cursor": payload["next_cursor"],
        },
    )
    assert continuation.status_code == 200
    assert "(d.attempt_no, d.process_run_id) > (%s, %s)" in calls[3][0]
