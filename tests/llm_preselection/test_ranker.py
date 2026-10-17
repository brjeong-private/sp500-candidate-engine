import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sp500_candidate_engine.analytics.azure_openai import AzureOpenAIResponse
from sp500_candidate_engine.database import _canonical_hash, _stable_uuid
from sp500_candidate_engine.llm_preselection.config import (
    load_llm_preselection_config,
)
from sp500_candidate_engine.llm_preselection.evidence import (
    EvidenceLink,
    EvidencePacket,
)
from sp500_candidate_engine.llm_preselection.ranker import (
    AzureOpenAIPreselectionRanker,
    LlmRankerSettings,
    LlmRankingError,
)


class _Client:
    def __init__(
        self,
        *,
        duplicate_final: bool = False,
        malformed_assessment: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self.duplicate_final = duplicate_final
        self.malformed_assessment = malformed_assessment

    async def complete(self, *, messages, schema_name, schema):
        self.calls.append(schema_name)
        if schema_name == "instrument_assessments":
            item = schema["properties"]["assessments"]["items"]
            instrument_ids = item["properties"]["instrument_id"]["enum"]
            evidence_ids = item["properties"]["evidence_ids"]["items"]["enum"]
            values = [
                {
                    "instrument_id": instrument_id,
                    "score": 80 - index,
                    "sub_scores": {
                        "business_momentum": 80,
                        "fundamental_quality": 80,
                        "event_significance": 80,
                        "market_confirmation": 80,
                        "evidence_quality": 80,
                    },
                    "evidence_quality": "HIGH",
                    "uncertainty": "LOW",
                    "reason_codes": ["BUSINESS_MOMENTUM"],
                    "rationale": "Grounded in supplied evidence.",
                    "evidence_ids": [evidence_ids[index]],
                }
                for index, instrument_id in enumerate(instrument_ids)
            ]
            if self.malformed_assessment:
                values[0].pop("score")
            output = {"assessments": values}
        else:
            instrument_ids = schema["properties"]["candidates"]["items"][
                "properties"
            ]["instrument_id"]["enum"]
            if self.duplicate_final:
                instrument_ids = [instrument_ids[0]] * 20
            output = {
                "candidates": [
                    {
                        "instrument_id": instrument_id,
                        "position": index,
                        "score": 90 - index,
                        "reason_codes": ["FUNDAMENTAL_STRENGTH"],
                        "evidence_ids": [
                            str(
                                _stable_uuid(
                                    "test-evidence",
                                    instrument_id,
                                )
                            )
                        ],
                    }
                    for index, instrument_id in enumerate(
                        instrument_ids[:20], start=1
                    )
                ]
            }
        return AzureOpenAIResponse(
            output=output,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )

    async def aclose(self) -> None:
        return None


def _packets() -> tuple[EvidencePacket, ...]:
    result = []
    for index in range(20):
        instrument_id = uuid.UUID(int=index + 1)
        link_id = _stable_uuid("test-evidence", str(instrument_id))
        payload = {
            "identity": {"instrument_id": str(instrument_id)},
            "cutoff_at": datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
            "target_session": "2026-01-01", "news": [{"event_revision_id": str(index)}],
        }
        result.append(
            EvidencePacket(
                instrument_id=instrument_id,
                issuer_id=uuid.UUID(int=index + 101),
                symbol=f"T{index}",
                company_name=f"Company {index}",
                sector="Technology",
                packet=payload,
                packet_hash=_canonical_hash(payload),
                estimated_tokens=10,
                section_counts={"news": 1},
                missing_sections=(),
                truncated_sections=(),
                links=(
                    EvidenceLink(
                        evidence_link_id=link_id,
                        source_snapshot_id=uuid.UUID(int=index + 201),
                        source_kind="NEWS",
                        entity_key=str(index),
                        source_available_at=datetime(2026, 1, 1, tzinfo=UTC),
                        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                        event_at=datetime(2026, 1, 1, tzinfo=UTC),
                    ),
                ),
            )
        )
    return tuple(result)


def _ranker(client: _Client) -> AzureOpenAIPreselectionRanker:
    config = load_llm_preselection_config(
        Path("config/llm_preselection/policy_v1.yaml")
    )
    return AzureOpenAIPreselectionRanker(
        LlmRankerSettings(
            endpoint="https://example.openai.azure.com",
            deployment="ranking",
            api_version="2025-01-01-preview",
        ),
        config,
        client=client,  # type: ignore[arg-type]
    )


def test_ranker_assesses_every_instrument_then_returns_exact_top_20() -> None:
    client = _Client()

    result = asyncio.run(
        _ranker(client).rank(
            llm_ranking_run_id=uuid.uuid4(),
            packets=_packets(),
        )
    )

    assert len(result.assessments) == 20
    assert len(result.candidates) == 20
    assert [item.position for item in result.candidates] == list(range(1, 21))
    assert client.calls == [
        "instrument_assessments",
        "instrument_assessments",
        "instrument_assessments",
        "instrument_assessments",
        "final_preselection",
    ]
    assert len(result.attempts) == 5


def test_ranker_fails_closed_on_duplicate_final_instrument() -> None:
    with pytest.raises(LlmRankingError, match="references are invalid"):
        asyncio.run(
            _ranker(_Client(duplicate_final=True)).rank(
                llm_ranking_run_id=uuid.uuid4(),
                packets=_packets(),
            )
        )


def test_ranker_wraps_malformed_structured_output() -> None:
    with pytest.raises(LlmRankingError, match="output is malformed"):
        asyncio.run(
            _ranker(_Client(malformed_assessment=True)).rank(
                llm_ranking_run_id=uuid.uuid4(),
                packets=_packets(),
            )
        )
