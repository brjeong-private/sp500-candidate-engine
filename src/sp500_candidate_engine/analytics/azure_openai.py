from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import httpx
from azure.identity import DefaultAzureCredential

AZURE_OPENAI_SCOPE = "https://cognitiveservices.azure.com/.default"


class AccessToken(Protocol):
    @property
    def token(self) -> str: ...


class TokenCredential(Protocol):
    def get_token(self, *scopes: str) -> AccessToken: ...


@dataclass(frozen=True)
class AzureOpenAIResponse:
    output: dict[str, object]
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


class AzureOpenAIClient:
    def __init__(
        self,
        *,
        endpoint: str,
        deployment: str,
        api_version: str,
        timeout_seconds: float,
        credential: TokenCredential | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("Azure OpenAI endpoint must use HTTPS")
        if not deployment or "/" in deployment:
            raise ValueError("Azure OpenAI deployment is invalid")
        if not api_version:
            raise ValueError("Azure OpenAI API version is required")
        if timeout_seconds <= 0:
            raise ValueError("Azure OpenAI timeout must be positive")
        self.endpoint = endpoint.rstrip("/")
        self.deployment = deployment
        self.api_version = api_version
        self.credential = credential or DefaultAzureCredential()
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds)
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, object],
    ) -> AzureOpenAIResponse:
        token = self.credential.get_token(AZURE_OPENAI_SCOPE)
        response = await self.client.post(
            (
                f"{self.endpoint}/openai/deployments/"
                f"{self.deployment}/chat/completions"
            ),
            params={"api-version": self.api_version},
            headers={
                "Authorization": "Bearer " + token.token,
                "Content-Type": "application/json",
            },
            json={
                "messages": messages,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    },
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        output = json.loads(content)
        if not isinstance(output, dict):
            raise ValueError("Azure OpenAI structured output must be an object")
        usage = payload.get("usage") or {}
        return AzureOpenAIResponse(
            output=output,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
