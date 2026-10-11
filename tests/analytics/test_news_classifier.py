import asyncio
import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from sp500_candidate_engine.analytics.news_classifier import (
    AZURE_OPENAI_SCOPE,
    AzureOpenAINewsClassifier,
    NewsClassifierSettings,
)


class _Token:
    token = "entra-token"


class _Credential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, *scopes: str) -> _Token:
        self.scopes.extend(scopes)
        return _Token()


def test_classifier_records_structured_lineage_with_entra_auth() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"labels": ["REGULATORY"], "material": True}
                            )
                        }
                    }
                ]
            },
        )

    credential = _Credential()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    classifier = AzureOpenAINewsClassifier(
        NewsClassifierSettings(
            endpoint="https://example.openai.azure.com",
            deployment="classifier",
            api_version="2025-01-01-preview",
        ),
        credential=credential,
        client=client,
    )
    snapshot_id = uuid.uuid4()
    revision_id = uuid.uuid4()

    async def run() -> object:
        result = await classifier.classify(
            source_snapshot_id=snapshot_id,
            event_revision_id=revision_id,
            title="Regulator opens inquiry",
            summary="The filing describes an inquiry.",
            classified_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert result.status == "SUCCEEDED"
    assert result.source_snapshot_id == snapshot_id
    assert result.input_hash
    assert result.output_hash
    assert result.structured_output == {
        "labels": ["REGULATORY"],
        "material": True,
    }
    assert credential.scopes == [AZURE_OPENAI_SCOPE]
    assert requests[0].headers["Authorization"] == "Bearer entra-token"
    request_body = json.loads(requests[0].content)
    assert request_body["response_format"]["type"] == "json_schema"
    assert request_body["response_format"]["json_schema"]["strict"] is True


def test_classifier_fails_closed_on_schema_violation() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"labels": ["UNAPPROVED"], "material": True}
                                )
                            }
                        }
                    ]
                },
            )
        )
    )
    classifier = AzureOpenAINewsClassifier(
        NewsClassifierSettings(
            endpoint="https://example.openai.azure.com",
            deployment="classifier",
            api_version="2025-01-01-preview",
        ),
        credential=_Credential(),
        client=client,
    )

    async def run() -> object:
        result = await classifier.classify(
            source_snapshot_id=uuid.uuid4(),
            event_revision_id=uuid.uuid4(),
            title="Unknown event",
            summary=None,
            classified_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert result.status == "FAILED"
    assert result.structured_output is None
    assert result.output_hash is None
    assert result.error_code == "CLASSIFICATION_FAILED"


def test_classifier_marks_empty_evidence_missing_without_request() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    classifier = AzureOpenAINewsClassifier(
        NewsClassifierSettings(
            endpoint="https://example.openai.azure.com",
            deployment="classifier",
            api_version="2025-01-01-preview",
        ),
        credential=_Credential(),
        client=client,
    )

    async def run() -> object:
        result = await classifier.classify(
            source_snapshot_id=uuid.uuid4(),
            event_revision_id=uuid.uuid4(),
            title=" ",
            summary=None,
            classified_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert result.status == "MISSING"
    assert result.error_code == "EMPTY_INPUT"
    assert calls == 0


def test_optional_classifier_settings_are_absent_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_API_VERSION",
    ):
        monkeypatch.delenv(name, raising=False)

    assert NewsClassifierSettings.from_env_if_configured() is None
