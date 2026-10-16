import asyncio
import json

import httpx

from sp500_candidate_engine.analytics.azure_openai import (
    AZURE_OPENAI_SCOPE,
    AzureOpenAIClient,
)


class _Token:
    token = "entra-token"


class _Credential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, *scopes: str) -> _Token:
        self.scopes.extend(scopes)
        return _Token()


def test_client_uses_entra_and_strict_structured_output() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"value": 1})}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                },
            },
        )

    credential = _Credential()
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AzureOpenAIClient(
        endpoint="https://example.openai.azure.com",
        deployment="ranking",
        api_version="2025-01-01-preview",
        timeout_seconds=30,
        credential=credential,
        client=http_client,
    )

    async def run():
        result = await client.complete(
            messages=[{"role": "user", "content": "{}"}],
            schema_name="test_schema",
            schema={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )
        await http_client.aclose()
        return result

    result = asyncio.run(run())

    assert result.output == {"value": 1}
    assert result.total_tokens == 12
    assert credential.scopes == [AZURE_OPENAI_SCOPE]
    assert requests[0].headers["Authorization"] == "Bearer " + _Token.token
    body = json.loads(requests[0].content)
    assert "temperature" not in body
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
