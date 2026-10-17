from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from azure.identity import DefaultAzureCredential

from sp500_candidate_engine.llm_preselection.asof import NEW_YORK, llm_cutoff, publication_bound

AZURE_OPENAI_SCOPE = "https://cognitiveservices.azure.com/.default"
AZURE_AI_SCOPE = "https://ai.azure.com/.default"


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


@dataclass(frozen=True)
class BingGroundingConnection:
    project_endpoint: str
    connection_id: str
    lookback_days: int = 30

    def __post_init__(self) -> None:
        endpoint = urlsplit(self.project_endpoint)
        if (
            endpoint.scheme != "https"
            or not endpoint.hostname
            or not endpoint.hostname.endswith((".services.ai.azure.com", ".ai.azure.com"))
            or endpoint.query
            or endpoint.fragment
            or endpoint.username
            or not re.fullmatch(r"/api/projects/[A-Za-z0-9_-]+", endpoint.path)
            or not re.fullmatch(
                r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/"
                r"Microsoft\.CognitiveServices/accounts/[^/]+/projects/"
                r"[^/]+/connections/[^/]+",
                self.connection_id,
            )
            or not 1 <= self.lookback_days <= 365
        ):
            raise ValueError("Invalid period-grounding connection")

    def freshness(self, cutoff_at: datetime) -> str:
        end = llm_cutoff(cutoff_at).astimezone(NEW_YORK).date()
        return f"{end - timedelta(days=self.lookback_days)}..{end}"


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
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    @property
    def binding_key(self) -> str:
        return json.dumps(
            {"endpoint": self.endpoint, "deployment": self.deployment}, sort_keys=True
        )

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, object],
    ) -> AzureOpenAIResponse:
        token = self.credential.get_token(AZURE_OPENAI_SCOPE)
        response = await self.client.post(
            (f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions"),
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

    async def search(
        self,
        *,
        instructions: str,
        public_input: dict[str, object],
        max_tool_calls: int,
        max_response_bytes: int,
        grounding: BingGroundingConnection | None = None,
    ) -> dict[str, object]:
        """Use provider-hosted search; never fetch source URLs in this process."""
        if set(public_input) != {"company_name", "ticker", "cik", "cutoff_at", "archive_sources"}:
            raise ValueError("Native search accepts only the public metadata whitelist")
        if (
            not isinstance(public_input["company_name"], str)
            or not 1 <= len(public_input["company_name"]) <= 256
            or not isinstance(public_input["ticker"], str)
            or not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,31}", public_input["ticker"])
            or not isinstance(public_input["cik"], str)
            or not re.fullmatch(r"\d{1,10}", public_input["cik"])
            or not isinstance(public_input["cutoff_at"], str)
        ):
            raise ValueError("Native search public fields must be bounded scalar metadata")
        cutoff = datetime.fromisoformat(public_input["cutoff_at"])
        if cutoff.utcoffset() is None:
            raise ValueError("Native search cutoff must be timezone-aware")
        anchors = public_input["archive_sources"]
        if (
            not isinstance(anchors, list)
            or not 1 <= len(anchors) <= 20
            or any(
                not isinstance(anchor, dict)
                or set(anchor) != {"accession", "form", "published_at", "archive_path"}
                for anchor in anchors
            )
        ):
            raise ValueError("Native search archive metadata is malformed")
        for anchor in anchors:
            if (
                any(not isinstance(value, str) for value in anchor.values())
                or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", anchor["accession"])
                or not 1 <= len(anchor["form"]) <= 20
                or anchor["archive_path"]
                != (
                    f"/Archives/edgar/data/{int(public_input['cik'])}/"
                    f"{anchor['accession'].replace('-', '')}/"
                )
            ):
                raise ValueError("Native search archive fields are not public scalar metadata")
            publication_bound(anchor["published_at"], cutoff)
        body: dict[str, object] = {
            "model": self.deployment,
            "instructions": instructions,
            "input": json.dumps(public_input, ensure_ascii=False, sort_keys=True),
            "max_output_tokens": 4096,
            "store": False,
        }
        if grounding is not None:
            url = grounding.project_endpoint + "/openai/v1/responses"
            body.update(
                tool_choice="required",
                tools=[
                    {
                        "type": "bing_grounding",
                        "bing_grounding": {
                            "search_configurations": [
                                {
                                    "project_connection_id": grounding.connection_id,
                                    "count": 10,
                                    "market": "en-US",
                                    "set_lang": "en",
                                    "freshness": grounding.freshness(cutoff),
                                }
                            ]
                        },
                    }
                ],
            )
        else:
            url = self.endpoint + "/openai/v1/responses"
            body.update(
                tools=[
                    {
                        "type": "web_search",
                        "filters": {"allowed_domains": ["sec.gov"]},
                        "search_context_size": "low",
                    }
                ],
                tool_choice={"type": "web_search"},
                max_tool_calls=max_tool_calls,
                include=["web_search_call.action.sources"],
            )
        token = self.credential.get_token(AZURE_AI_SCOPE)
        response = await self.client.post(
            url,
            headers={"Authorization": "Bearer " + token.token, "Content-Type": "application/json"},
            json=body,
        )
        response.raise_for_status()
        if len(response.content) > max_response_bytes:
            raise ValueError("Native search response exceeds its byte budget")
        payload = response.json()
        if (
            not isinstance(payload, dict)
            or payload.get("status") != "completed"
            or payload.get("error") is not None
            or payload.get("previous_response_id") is not None
        ):
            raise ValueError("Native search did not complete as an isolated response")
        return payload


class BingGroundingSearchClient:
    def __init__(self, client: AzureOpenAIClient, connection: BingGroundingConnection) -> None:
        self.client = client
        self.connection = connection
        self.endpoint = connection.project_endpoint
        self.deployment = client.deployment

    @property
    def binding_key(self) -> str:
        return json.dumps(
            {
                "endpoint": self.endpoint,
                "connection": self.connection.connection_id,
                "lookback_days": self.connection.lookback_days,
            },
            sort_keys=True,
        )

    async def search(
        self,
        *,
        instructions: str,
        public_input: dict[str, object],
        max_tool_calls: int,
        max_response_bytes: int,
    ) -> dict[str, object]:
        return await self.client.search(
            instructions=instructions,
            public_input=public_input,
            max_tool_calls=max_tool_calls,
            max_response_bytes=max_response_bytes,
            grounding=self.connection,
        )
