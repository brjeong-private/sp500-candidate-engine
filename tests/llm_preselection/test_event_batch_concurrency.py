from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest

from sp500_candidate_engine.analytics.azure_openai import AzureOpenAIClient, AzureOpenAIResponse
from sp500_candidate_engine.database import _canonical_hash
from sp500_candidate_engine.llm_preselection import service as service_module
from sp500_candidate_engine.llm_preselection.config import (
    LlmPreselectionConfig,
    RateLimits,
    load_llm_preselection_config,
)
from sp500_candidate_engine.llm_preselection.event_ranker import EventPreselectionRanker
from sp500_candidate_engine.llm_preselection.evidence import EvidenceLink, EvidencePacket
from sp500_candidate_engine.llm_preselection.ranker import (
    CachedCompletion,
    LlmRankerSettings,
    LlmRankingError,
    RankingResult,
    _InputTokenBudget,
)
from sp500_candidate_engine.llm_preselection.rate_limits import LlmRateLimiter, TokenReservation
from sp500_candidate_engine.llm_preselection.service import LlmPreselectionService

CUTOFF = datetime(2026, 10, 15, 9, 30, tzinfo=UTC)
SETTINGS = LlmRankerSettings("https://example.openai.azure.com", "test", "test")


def _config() -> LlmPreselectionConfig:
    config = load_llm_preselection_config(
        Path(__file__).resolve().parents[2] / "config" / "llm_preselection" / "policy_event_v2.yaml"
    )
    return replace(config, base_delay_seconds=0)


def _packets(count: int = 20) -> tuple[EvidencePacket, ...]:
    packets = []
    for index in range(1, count + 1):
        payload = {
            "identity": {"instrument_id": str(UUID(int=index))},
            "execution_context_id": str(UUID(int=999)),
            "cutoff_at": CUTOFF.isoformat(),
            "target_session": CUTOFF.date().isoformat(),
            "news": [{"event_revision_id": str(index), "title": "공급 계약 소식"}],
        }
        packets.append(EvidencePacket(
            UUID(int=index), UUID(int=index), f"T{index}", f"Company {index}", "Tech",
            payload, _canonical_hash(payload), 20, {"news": 1}, (), (),
            (EvidenceLink(
                UUID(int=index + 10000), UUID(int=index + 20000), "NEWS", str(index),
                CUTOFF - timedelta(days=1), CUTOFF - timedelta(days=1), None,
            ),),
        ))
    return tuple(packets)


class _Client(AzureOpenAIClient):
    def __init__(
        self, faults: dict[int, tuple[str, ...]] | None = None,
        *, unsupported: frozenset[int] = frozenset(),
    ) -> None:
        self.faults = faults or {}
        self.unsupported = unsupported
        self.active = 0
        self.maximum_active = 0
        self.started: list[int] = []
        self.finished: list[int] = []
        self.cancelled: list[int] = []
        self.counts: dict[int, int] = {}
        self.input_estimates: list[int] = []

    async def complete(
        self, *, messages: list[dict[str, str]], schema_name: str, schema: dict[str, object],
    ) -> AzureOpenAIResponse:
        assert schema_name == "event_assessments_v2"
        rows = json.loads(messages[1]["content"])
        batch_no = (UUID(rows[0]["instrument_id"]).int - 1) // 5
        attempt = self.counts.get(batch_no, 0)
        self.counts[batch_no] = attempt + 1
        self.started.append(batch_no)
        self.input_estimates.append(
            (len(json.dumps(messages)) + len(json.dumps(schema)) + 3) // 4
        )
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            for _ in range(5 - batch_no % 4):
                await asyncio.sleep(0)
            faults = self.faults.get(batch_no, ())
            fault = faults[attempt] if attempt < len(faults) else None
            if fault == "transport":
                raise httpx.ReadTimeout("fake timeout")
            values = []
            for row in rows:
                criteria = ("earnings", "business", "event", "financial", "industry")
                supported_count = 2 if UUID(row["instrument_id"]).int in self.unsupported else 3
                supported = criteria[:supported_count]
                values.append({
                    "instrument_id": row["instrument_id"],
                    "scores": {key: 75 if key in supported else None for key in criteria},
                    "missing_reasons": {
                        key: None if key in supported else "제공된 근거가 부족합니다."
                        for key in criteria
                    },
                    "evidence_quality": "MEDIUM", "uncertainty": "HIGH",
                    "summary": "제공된 뉴스의 변화를 평가했습니다.",
                    "evidence": [
                        {
                            "criterion": key,
                            "evidence_link_id": str(UUID(int=999999)) if fault == "semantic"
                            else row["evidence"][0]["evidence_link_id"],
                            "reason": "제공된 계약 소식을 반영했습니다.",
                        }
                        for key in supported
                    ],
                })
            return AzureOpenAIResponse({"assessments": values}, 10, 5, 15)
        except asyncio.CancelledError:
            self.cancelled.append(batch_no)
            raise
        finally:
            self.active -= 1
            self.finished.append(batch_no)


def _rank(
    ranker: EventPreselectionRanker, packets: tuple[EvidencePacket, ...] | None = None,
) -> RankingResult:
    return asyncio.run(ranker.rank(
        llm_ranking_run_id=UUID(int=1000), packets=_packets() if packets is None else packets,
    ))


def _cache(result: RankingResult) -> dict[str, CachedCompletion]:
    cache = {}
    for attempt in result.attempts:
        assert attempt.response_output is not None and attempt.output_hash is not None
        cache[attempt.input_hash] = CachedCompletion(
            attempt.response_output, attempt.output_hash, attempt.call_attempt_id,
        )
    return cache


@pytest.mark.parametrize("concurrency", [1, 2, 3, 4])
def test_concurrency_is_bounded_and_outputs_keep_serial_contract(concurrency: int) -> None:
    packets = _packets(30)
    serial = _rank(EventPreselectionRanker(
        SETTINGS, _config(), client=_Client(unsupported=frozenset({30})),
    ), packets)
    client = _Client(unsupported=frozenset({30}))
    result = _rank(EventPreselectionRanker(
        SETTINGS, _config(), client=client, assessment_concurrency=concurrency,
    ), tuple(reversed(packets)))
    assert client.maximum_active == concurrency
    assert client.active == 0
    assert result.assessments == serial.assessments
    assert result.candidates == serial.candidates
    assert [item.batch_no for item in result.attempts] == list(range(6))
    assert [item.input_hash for item in result.attempts] == [
        item.input_hash for item in serial.attempts
    ]
    assert [item.output_hash for item in result.attempts] == [
        item.output_hash for item in serial.attempts
    ]
    assert [item.call_attempt_id for item in result.attempts] == [
        item.call_attempt_id for item in serial.attempts
    ]
    assert [item.instrument_id.int for item in result.candidates] == list(range(1, 21))
    assert result.assessments[-1].score is None
    assert result.assessments[-1].supported_count == 2
    for item in result.assessments[:-1]:
        assert item.supported_count == 3 and item.weight_denominator == 70
        assert item.sub_scores["financial"] is None
        assert item.missing_reasons["financial"]
        assert item.evidence_ids == (UUID(int=item.instrument_id.int + 10000),)
    if concurrency > 1:
        assert client.finished != client.started


@pytest.mark.parametrize("value", [0, 5, -1, True, 1.5, "3", None])
def test_invalid_concurrency_fails_before_client_creation(value: object) -> None:
    with pytest.raises(ValueError, match="assessment_concurrency"):
        EventPreselectionRanker(
            SETTINGS, _config(), assessment_concurrency=value,  # type: ignore[arg-type]
        )


def test_default_is_serial_and_stops_at_first_failed_batch() -> None:
    client = _Client({0: ("semantic",) * 3})
    ranker = EventPreselectionRanker(SETTINGS, _config(), client=client)
    assert ranker.assessment_concurrency == 1
    with pytest.raises(LlmRankingError, match="malformed") as failed:
        _rank(ranker)
    assert client.maximum_active == 1
    assert client.started == [0, 0, 0]
    assert [attempt.attempt_no for attempt in failed.value.attempts] == [1, 2, 3]
    assert all(item.error_code == "OUTPUT_VALIDATION_FAILED" for item in failed.value.attempts)


@pytest.mark.parametrize("fault", ["semantic", "transport"])
def test_parallel_failure_drains_successes_and_preserves_all_attempts(fault: str) -> None:
    client = _Client({0: (fault,) * 3})
    with pytest.raises(LlmRankingError) as failed:
        _rank(EventPreselectionRanker(
            SETTINGS, _config(), client=client, assessment_concurrency=3,
        ))
    assert client.maximum_active == 3 and client.active == 0 and not client.cancelled
    assert set(client.started) == {0, 1, 2}
    attempts = failed.value.attempts
    assert [(item.batch_no, item.attempt_no) for item in attempts] == [
        (0, 1), (0, 2), (0, 3), (1, 1), (2, 1),
    ]
    assert [item.status for item in attempts] == ["FAILED"] * 3 + ["SUCCEEDED"] * 2
    assert all(item.response_output is not None for item in attempts[-2:])
    assert len({item.call_attempt_id for item in attempts}) == 5


def test_parallel_semantic_and_transport_retries_stay_bounded_and_ordered() -> None:
    client = _Client({0: ("semantic",), 1: ("transport",)})
    result = _rank(EventPreselectionRanker(
        SETTINGS, _config(), client=client, assessment_concurrency=3,
    ))
    assert [(item.batch_no, item.attempt_no) for item in result.attempts] == [
        (0, 1), (0, 2), (1, 1), (1, 2), (2, 1), (3, 1),
    ]
    assert result.attempts[0].error_code == "OUTPUT_VALIDATION_FAILED"
    assert result.attempts[2].error_code == "ReadTimeout"
    assert len(result.candidates) == 20
    assert max(client.counts.values()) <= _config().max_attempts


@pytest.mark.parametrize("limits", [RateLimits(1, 1000000, 1), RateLimits(100, 12000, 1)])
def test_parallel_dates_and_batches_share_one_rpm_tpm_limiter(limits: RateLimits) -> None:
    clock = [0.0]
    delays: list[float] = []
    snapshots: list[tuple[int, int]] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)
        await asyncio.sleep(0)
        clock[0] += seconds

    class RecordingLimiter(LlmRateLimiter):
        async def acquire(self, estimated_input_tokens: int) -> TokenReservation:
            reservation = await super().acquire(estimated_input_tokens)
            snapshots.append((len(self.calls), sum(call.tokens for call in self.calls)))
            return reservation

    limiter = RecordingLimiter(limits, clock=lambda: clock[0], sleep=sleep)
    rankers = [
        EventPreselectionRanker(
            SETTINGS, _config(), client=_Client({0: ("transport",)}),
            assessment_concurrency=3,
        )
        for _ in range(2)
    ]
    for ranker in rankers:
        ranker.rate_limiter = limiter

    async def run() -> list[RankingResult]:
        return await asyncio.gather(*(
            ranker.rank(llm_ranking_run_id=UUID(int=1000 + index), packets=_packets())
            for index, ranker in enumerate(rankers)
        ))

    results = asyncio.run(run())
    assert len(snapshots) == sum(len(result.attempts) for result in results) == 10
    assert delays
    assert all(count <= limits.requests_per_minute and tokens <= limits.tokens_per_minute
               for count, tokens in snapshots)
    assert all(ranker.rate_limiter is limiter for ranker in rankers)


@pytest.mark.parametrize("fault", ["semantic", "transport"])
def test_total_input_budget_is_shared_and_charges_retries(
    fault: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    probe = EventPreselectionRanker(SETTINGS, config, client=_Client())
    batches = [_packets()[start:start + 5] for start in range(0, 20, 5)]
    estimates = [
        (len(json.dumps(probe._assessment_messages(list(batch))))
         + len(json.dumps(probe._assessment_schema(list(batch)))) + 3) // 4
        for batch in batches
    ]
    limit = sum(estimates[:3])
    reservations: list[int] = []
    reserve = _InputTokenBudget.reserve

    def record(budget: _InputTokenBudget, tokens: int) -> None:
        try:
            reserve(budget, tokens)
        finally:
            reservations.append(budget.reserved)

    monkeypatch.setattr(_InputTokenBudget, "reserve", record)
    client = _Client({0: (fault,)})
    with pytest.raises(LlmRankingError) as failed:
        _rank(EventPreselectionRanker(
            SETTINGS, replace(config, limits=replace(config.limits, total_input_tokens=limit)),
            client=client, assessment_concurrency=3,
        ))
    assert sum(client.input_estimates) == limit
    assert max(reservations) == limit and all(value <= limit for value in reservations)
    assert client.counts == {0: 1, 1: 1, 2: 1}
    assert [(item.batch_no, item.attempt_no) for item in failed.value.attempts] == [
        (0, 1), (0, 2), (1, 1), (2, 1),
    ]
    assert failed.value.attempts[1].error_code == "ValueError"
    assert all(item.status == "SUCCEEDED" for item in failed.value.attempts[-2:])


def test_cache_hits_do_not_consume_request_budget_or_quota_and_keep_hashes() -> None:
    initial = _rank(EventPreselectionRanker(SETTINGS, _config(), client=_Client()))
    cache = _cache(initial)
    config = _config()
    client = _Client()
    ranker = EventPreselectionRanker(
        SETTINGS, replace(config, limits=replace(config.limits, total_input_tokens=1)),
        client=client, assessment_concurrency=3,
    )
    def cached(input_hash: str, context: UUID, include_failed: bool) -> CachedCompletion | None:
        assert context == UUID(int=999) and include_failed
        return cache.get(input_hash)

    ranker.response_cache = cached
    assert ranker.rate_limiter is not None
    result = _rank(ranker)
    assert not client.started and not ranker.rate_limiter.calls
    assert result.assessments == initial.assessments
    assert all(item.total_tokens == 0 and item.cache_source_attempt_id for item in result.attempts)
    assert [item.input_hash for item in result.attempts] == [
        item.input_hash for item in initial.attempts
    ]


def test_parallel_request_budget_subtracts_search_usage_without_precharging_retries() -> None:
    config = _config()
    initial_client = _Client()
    _rank(EventPreselectionRanker(SETTINGS, config, client=initial_client))
    request_total = sum(initial_client.input_estimates)
    external = config.limits.total_input_tokens - request_total
    client = _Client()
    ranker = EventPreselectionRanker(
        SETTINGS, config, client=client, assessment_concurrency=3,
    )
    result = asyncio.run(ranker.rank(
        llm_ranking_run_id=UUID(int=1000), packets=_packets(), external_input_tokens=external,
    ))
    assert len(result.candidates) == 20 and len(client.started) == 4
    assert sum(client.input_estimates) + external == config.limits.total_input_tokens
    retry_client = _Client({0: ("transport",)})
    retry = EventPreselectionRanker(
        SETTINGS, config, client=retry_client, assessment_concurrency=3,
    )
    with pytest.raises(LlmRankingError):
        asyncio.run(retry.rank(
            llm_ranking_run_id=UUID(int=1000), packets=_packets(), external_input_tokens=external,
        ))
    assert sum(retry_client.input_estimates) + external <= config.limits.total_input_tokens


@pytest.mark.parametrize("external", [-1, True, 1.5])
def test_external_budget_rejects_invalid_usage_before_call(external: object) -> None:
    client = _Client()
    ranker = EventPreselectionRanker(
        SETTINGS, _config(), client=client, assessment_concurrency=3,
    )
    with pytest.raises(ValueError, match="external_input_tokens"):
        asyncio.run(ranker.rank(
            llm_ranking_run_id=UUID(int=1000), packets=_packets(),
            external_input_tokens=external,  # type: ignore[arg-type]
        ))
    assert not client.started


@pytest.mark.parametrize("concurrency", [1, 3])
def test_service_passes_search_budget_only_for_opt_in_parallel_ranker(
    concurrency: int, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_llm_preselection_config(
        Path(__file__).resolve().parents[2] / "config" / "llm_preselection"
        / "policy_event_optional_search_v6.yaml"
    )
    repository = MagicMock()
    repository.find_successful_run.return_value = None
    monkeypatch.setattr(service_module, "LlmPreselectionRepository", lambda _connection: repository)
    ranker = EventPreselectionRanker(
        SETTINGS, config, client=_Client(), assessment_concurrency=concurrency,
    )
    rank = AsyncMock(side_effect=LlmRankingError("fake failure", ()))
    monkeypatch.setattr(ranker, "rank", rank)
    enricher = MagicMock()
    enricher.search_input_tokens = 12345
    service = LlmPreselectionService(
        MagicMock(), config, SETTINGS, ranker=ranker, enricher=enricher,
    )
    builder = MagicMock()
    builder.screening_audit = []
    summary = asyncio.run(service._rank_inputs(
        target_session=CUTOFF.date(), execution_context_id=UUID(int=999), started_at=CUTOFF,
        context={"cutoff_at": CUTOFF, "knowledge_mode": "HISTORICAL_RECONSTRUCTION"},
        builder=builder, packets=_packets(), cache_source_id=None,
    ))
    assert summary.status == "FAILED"
    assert repository.persist.call_count == 1
    kwargs = rank.await_args.kwargs
    if concurrency > 1:
        assert kwargs["external_input_tokens"] == 12345
    else:
        assert set(kwargs) == {"llm_ranking_run_id", "packets"}


def test_failed_cached_output_is_revalidated_and_repaired_without_cache_loop() -> None:
    invalid_client = _Client({0: ("semantic",)})
    with pytest.raises(LlmRankingError) as failed:
        _rank(EventPreselectionRanker(
            SETTINGS, replace(_config(), max_attempts=1), client=invalid_client,
        ))
    attempt = failed.value.attempts[0]
    assert attempt.response_output is not None and attempt.output_hash is not None
    cache = {attempt.input_hash: CachedCompletion(
        attempt.response_output, attempt.output_hash, attempt.call_attempt_id,
    )}
    modes: list[tuple[str, bool]] = []

    def cached(input_hash: str, context: UUID, include_failed: bool) -> CachedCompletion | None:
        assert context == UUID(int=999)
        modes.append((input_hash, include_failed))
        return cache.get(input_hash) if include_failed else None

    client = _Client()
    ranker = EventPreselectionRanker(
        SETTINGS, _config(), client=client, assessment_concurrency=3,
    )
    ranker.response_cache = cached
    result = _rank(ranker)
    assert result.attempts[0].cache_source_attempt_id == attempt.call_attempt_id
    assert result.attempts[0].error_code == "OUTPUT_VALIDATION_FAILED"
    assert result.attempts[1].attempt_no == 2 and result.attempts[1].http_status == 200
    assert len(client.started) == 4
    assert sum(not include_failed for _, include_failed in modes) == 1


def test_unexpected_parallel_validation_failure_retains_completed_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranker = EventPreselectionRanker(
        SETTINGS, _config(), client=_Client(), assessment_concurrency=3,
    )
    parse = ranker._parse_assessments

    def broken(
        *, output: dict[str, object], output_hash: str, batch_no: int,
        packets: list[EvidencePacket],
    ):
        if batch_no == 0:
            raise RuntimeError("fake parser failure")
        return parse(output=output, output_hash=output_hash, batch_no=batch_no, packets=packets)

    monkeypatch.setattr(ranker, "_parse_assessments", broken)
    with pytest.raises(LlmRankingError, match="batch failed") as failed:
        _rank(ranker)
    assert [item.batch_no for item in failed.value.attempts] == [0, 1, 2]
    assert all(item.response_output is not None for item in failed.value.attempts)


def test_parallel_time_gate_rejects_input_before_any_call() -> None:
    packets = _packets()
    future = replace(
        packets[0], links=(replace(
            packets[0].links[0], source_available_at=CUTOFF + timedelta(seconds=1),
        ),),
    )
    client = _Client()
    with pytest.raises(ValueError, match="cutoff"):
        _rank(EventPreselectionRanker(
            SETTINGS, _config(), client=client, assessment_concurrency=3,
        ), (future, *packets[1:]))
    assert not client.started


def test_progress_logging_contains_only_safe_counts_and_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="sp500_candidate_engine.llm_preselection.event_ranker")
    _rank(EventPreselectionRanker(
        SETTINGS, _config(), client=_Client(), assessment_concurrency=3,
    ))
    records = [record for record in caplog.records if record.message == "Event assessment batch"]
    assert len(records) == 8
    for record in records:
        assert record.batch_no in range(4)
        assert record.assessed_count in {0, 5}
        assert record.status in {"RUNNING", "SUCCEEDED"}
        assert record.args == ()
        assert not any(value in record.getMessage() for value in ("공급 계약", "instrument_id"))
