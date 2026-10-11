from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx
from azure.identity import AzureCliCredential, DefaultAzureCredential

AZURE_OPENAI_SCOPE = "https://cognitiveservices.azure.com/.default"
ALLOWED_LABELS = (
    "EARNINGS",
    "LITIGATION",
    "M_AND_A",
    "REGULATORY",
    "FINANCING",
    "MANAGEMENT",
    "PRODUCT",
    "OTHER",
)


class TokenCredential(Protocol):
    def get_token(self, *scopes: str) -> AccessToken: ...


class AccessToken(Protocol):
    token: str


@dataclass(frozen=True)
class NewsClassifierSettings:
    endpoint: str
    deployment: str
    api_version: str
    prompt_version: str = "news-event-v1"
    credential_mode: str = "default"
    tenant_id: str | None = None
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> NewsClassifierSettings:
        def required(name: str) -> str:
            value = os.getenv(name, "").strip()
            if not value:
                raise ValueError(f"Required environment variable is missing: {name}")
            return value

        settings = cls(
            endpoint=required("AZURE_OPENAI_ENDPOINT"),
            deployment=required("AZURE_OPENAI_DEPLOYMENT"),
            api_version=required("AZURE_OPENAI_API_VERSION"),
            prompt_version=os.getenv(
                "AZURE_OPENAI_NEWS_PROMPT_VERSION", "news-event-v1"
            ).strip(),
            credential_mode=os.getenv("AZURE_CREDENTIAL_MODE", "default").strip(),
            tenant_id=os.getenv("AZURE_TENANT_ID", "").strip() or None,
            timeout_seconds=float(
                os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "30")
            ),
        )
        settings.validate()
        return settings

    @classmethod
    def from_env_if_configured(cls) -> NewsClassifierSettings | None:
        names = (
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_DEPLOYMENT",
            "AZURE_OPENAI_API_VERSION",
        )
        configured = [bool(os.getenv(name, "").strip()) for name in names]
        if not any(configured):
            return None
        if not all(configured):
            missing = [
                name
                for name, present in zip(names, configured, strict=True)
                if not present
            ]
            raise ValueError(
                "Partial optional Azure OpenAI configuration; missing: "
                + ", ".join(missing)
            )
        return cls.from_env()

    def validate(self) -> None:
        if not self.endpoint.startswith("https://"):
            raise ValueError("AZURE_OPENAI_ENDPOINT must use HTTPS")
        if not self.deployment or "/" in self.deployment:
            raise ValueError("AZURE_OPENAI_DEPLOYMENT is invalid")
        if not self.api_version or not self.prompt_version:
            raise ValueError("API and prompt versions are required")
        if self.credential_mode not in {"default", "azure_cli"}:
            raise ValueError("AZURE_CREDENTIAL_MODE must be 'default' or 'azure_cli'")
        if self.timeout_seconds <= 0:
            raise ValueError("AZURE_OPENAI_TIMEOUT_SECONDS must be positive")


@dataclass(frozen=True)
class NewsClassification:
    source_snapshot_id: uuid.UUID
    event_revision_id: uuid.UUID
    status: str
    input_hash: str
    prompt_version: str
    deployment: str
    structured_output: dict[str, object] | None
    output_hash: str | None
    classified_at: datetime
    error_code: str | None = None


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


class AzureOpenAINewsClassifier:
    def __init__(
        self,
        settings: NewsClassifierSettings,
        *,
        credential: TokenCredential | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings.validate()
        self.settings = settings
        if credential is None:
            if settings.credential_mode == "azure_cli":
                credential = AzureCliCredential(tenant_id=settings.tenant_id)
            else:
                credential = DefaultAzureCredential()
        self.credential = credential
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout_seconds)
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def classify(
        self,
        *,
        source_snapshot_id: uuid.UUID,
        event_revision_id: uuid.UUID,
        title: str,
        summary: str | None,
        classified_at: datetime,
    ) -> NewsClassification:
        evidence = {"title": title.strip(), "summary": (summary or "").strip()}
        input_hash = _canonical_hash(
            {
                "source_snapshot_id": source_snapshot_id,
                "event_revision_id": event_revision_id,
                "evidence": evidence,
            }
        )
        base = {
            "source_snapshot_id": source_snapshot_id,
            "event_revision_id": event_revision_id,
            "input_hash": input_hash,
            "prompt_version": self.settings.prompt_version,
            "deployment": self.settings.deployment,
            "classified_at": classified_at,
        }
        if not evidence["title"] and not evidence["summary"]:
            return NewsClassification(
                **base,
                status="MISSING",
                structured_output=None,
                output_hash=None,
                error_code="EMPTY_INPUT",
            )

        schema = {
            "type": "object",
            "properties": {
                "labels": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(ALLOWED_LABELS)},
                    "uniqueItems": True,
                },
                "material": {"type": "boolean"},
            },
            "required": ["labels", "material"],
            "additionalProperties": False,
        }
        body = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classify only the supplied evidence. Do not use external "
                        f"knowledge. Prompt version: {self.settings.prompt_version}."
                    ),
                },
                {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "news_event",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        url = (
            f"{self.settings.endpoint.rstrip('/')}/openai/deployments/"
            f"{self.settings.deployment}/chat/completions"
        )
        try:
            token = self.credential.get_token(AZURE_OPENAI_SCOPE)
            response = await self.client.post(
                url,
                params={"api-version": self.settings.api_version},
                headers={
                    "Authorization": f"Bearer {token.token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            output = json.loads(content)
            self._validate_output(output)
        except Exception:
            return NewsClassification(
                **base,
                status="FAILED",
                structured_output=None,
                output_hash=None,
                error_code="CLASSIFICATION_FAILED",
            )
        return NewsClassification(
            **base,
            status="SUCCEEDED",
            structured_output=output,
            output_hash=_canonical_hash(output),
        )

    @staticmethod
    def _validate_output(output: object) -> None:
        if not isinstance(output, dict) or set(output) != {"labels", "material"}:
            raise ValueError("invalid structured output keys")
        labels = output["labels"]
        if (
            not isinstance(labels, list)
            or len(labels) != len(set(labels))
            or any(label not in ALLOWED_LABELS for label in labels)
            or not isinstance(output["material"], bool)
        ):
            raise ValueError("invalid structured output values")
