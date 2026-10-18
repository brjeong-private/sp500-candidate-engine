import asyncio
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from psycopg import sql

from sp500_candidate_engine.llm_preselection import evidence, temporal
from sp500_candidate_engine.llm_preselection.config import (
    RateLimits,
    load_llm_preselection_config,
)
from sp500_candidate_engine.llm_preselection.rate_limits import LlmRateLimiter
from sp500_candidate_engine.llm_preselection.service import LlmPreselectionService

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("fails", [False, True])
def test_parallel_reads_share_snapshot_preserve_order_and_close_connections(monkeypatch, fails):
    config = load_llm_preselection_config(ROOT / "config" / "llm_preselection" / "policy_v1.yaml")
    source = MagicMock()
    source.read_context.return_value = {
        "cutoff_at": datetime(2026, 10, 15, 9, 30, tzinfo=UTC),
        "knowledge_mode": "HISTORICAL_RECONSTRUCTION",
    }
    source.read_universe_members.return_value = [
        {"instrument_id": str(uuid.UUID(int=index))} for index in range(1, 9)
    ]
    source.read_bars.return_value = []
    source.connection.execute.return_value.fetchall.side_effect = [
        [{"isolation": "repeatable read", "read_only": "on"}],
        [{"snapshot_id": "shared-snapshot"}],
    ]
    connections = []
    barrier = threading.Barrier(2, timeout=5)
    lock = threading.Lock()
    active = peak = 0

    class Connection:
        closed = False

        def __init__(self):
            self.statements = []

        def execute(self, statement):
            self.statements.append(
                statement.as_string() if isinstance(statement, sql.Composable) else statement
            )

    @contextmanager
    def connect():
        connection = Connection()
        connections.append(connection)
        try:
            yield connection
        finally:
            connection.closed = True

    def build_one(builder, *, member, **kwargs):
        nonlocal active, peak
        assert builder.repository.connection.statements == [
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
            "SET TRANSACTION SNAPSHOT 'shared-snapshot'",
        ]
        if fails:
            raise RuntimeError("database read failed")
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait()
        with lock:
            active -= 1
        return SimpleNamespace(
            instrument_id=uuid.UUID(member["instrument_id"]), estimated_tokens=10,
        )

    monkeypatch.setattr(evidence, "SourceRepository", lambda conn: SimpleNamespace(connection=conn))
    monkeypatch.setattr(evidence.EvidencePacketBuilder, "_build_one", build_one)
    validator = MagicMock()
    monkeypatch.setattr(temporal, "validate_packet", validator)
    builder = evidence.EvidencePacketBuilder(source, config)

    def execute():
        return builder.build_all(
            execution_context_id=uuid.uuid4(), target_session=date(2026, 10, 14),
            database=SimpleNamespace(connect=connect), max_workers=2,
        )

    if fails:
        with pytest.raises(RuntimeError, match="database read failed"):
            execute()
        validator.assert_not_called()
    else:
        packets = execute()
        assert [packet.instrument_id.int for packet in packets] == list(range(1, 9))
        assert peak == 2
        assert validator.call_count == 8
    assert 1 <= len(connections) <= 2
    if not fails:
        assert len(connections) == 2
    assert len({id(connection) for connection in connections}) == len(connections)
    assert all(connection.closed for connection in connections)


def test_parallel_reads_reject_inconsistent_parent_snapshot():
    config = load_llm_preselection_config(ROOT / "config" / "llm_preselection" / "policy_v1.yaml")
    source = MagicMock()
    source.connection.execute.return_value.fetchall.return_value = [
        {"isolation": "read committed", "read_only": "on"},
    ]
    with pytest.raises(ValueError, match="read-only parent"):
        evidence.EvidencePacketBuilder(source, config).build_all(
            execution_context_id=uuid.uuid4(), target_session=date(2026, 10, 14),
            database=MagicMock(), max_workers=2,
        )
    source.read_context.assert_not_called()


def test_input_preparation_does_not_block_other_dates(monkeypatch):
    config = load_llm_preselection_config(ROOT / "config" / "llm_preselection" / "policy_v1.yaml")
    service = LlmPreselectionService(MagicMock(), config, MagicMock(), ranker=MagicMock())
    barrier = threading.Barrier(2, timeout=5)

    def prepare(**kwargs):
        barrier.wait()
        return (
            {"cutoff_at": datetime(2026, 10, 15, tzinfo=UTC)},
            MagicMock(), (), None,
        )

    monkeypatch.setattr(service, "_prepare_inputs", prepare)
    rank = AsyncMock(return_value="ranked")
    monkeypatch.setattr(service, "_rank_inputs", rank)

    async def execute():
        return await asyncio.gather(*(
            service._run(target_session=date(2026, 10, day), execution_context_id=uuid.uuid4())
            for day in (14, 15)
        ))

    assert asyncio.run(execute()) == ["ranked", "ranked"]
    assert rank.await_count == 2


def test_quota_usage_updates_its_own_request_out_of_order_and_after_expiry():
    clock = [0.0]
    limiter = LlmRateLimiter(RateLimits(10, 200, 10), clock=lambda: clock[0])

    async def execute():
        first = await limiter.acquire(10)
        second = await limiter.acquire(20)
        limiter.record_usage(45, second)
        limiter.record_usage(60, first)
        assert [call.tokens for call in limiter.calls] == [60, 45]
        clock[0] = 61
        third = await limiter.acquire(10)
        limiter.record_usage(80, first)
        assert list(limiter.calls)[0] is third
        assert [call.tokens for call in limiter.calls] == [20, 20]

    asyncio.run(execute())
