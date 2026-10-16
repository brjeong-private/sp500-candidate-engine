"""외부 API와 Azure control plane을 제한된 HTTP 계약으로 호출한다."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterable
from copy import deepcopy
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from settings import Settings

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
PORTAL_SUBMIT_TIMEOUT = httpx.Timeout(300.0, connect=5.0)
CANDIDATE_TERMINAL = {"SUCCEEDED", "PARTIAL_SUCCESS", "FAILED"}
PORTAL_JOB_TERMINAL = {"completed", "failed"}
ARM_ENDPOINT = "https://management.azure.com"
ARM_SCOPE = f"{ARM_ENDPOINT}/.default"
STORAGE_SCOPE = "https://storage.azure.com/.default"
LOCK_API_VERSION = "2016-09-01"
APP_SERVICE_API_VERSION = "2024-04-01"
POSTGRES_API_VERSION = "2024-08-01"
MYSQL_API_VERSION = "2023-12-30"
CONTAINER_APP_API_VERSION = "2024-03-01"
STORAGE_API_VERSION = "2023-05-01"
ARM_RECHECK_ATTEMPTS = 30
ARM_RECHECK_SECONDS = 10


class ExternalServiceError(RuntimeError):
    """외부 서비스 호출 또는 응답 계약 위반을 나타낸다."""


class ArmRequestError(ExternalServiceError):
    def __init__(self, status_code: int, code: str):
        super().__init__(f"ARM request failed with HTTP {status_code} ({code})")
        self.status_code = status_code
        self.code = code


def _validate_https_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ExternalServiceError("outbound URL must use HTTPS without credentials or fragment")


def _read_limited_json(response: httpx.Response) -> dict[str, Any]:
    declared = response.headers.get("content-length")
    if declared:
        try:
            if int(declared) > MAX_RESPONSE_BYTES:
                raise ExternalServiceError("response exceeds size limit")
        except ValueError as error:
            raise ExternalServiceError("invalid Content-Length") from error
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise ExternalServiceError("response exceeds size limit")
        chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExternalServiceError("response is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ExternalServiceError("response must be a JSON object")
    return payload


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    expected_statuses: Iterable[int] = (200,),
    timeout: httpx.Timeout = HTTP_TIMEOUT,
) -> dict[str, Any]:
    """리디렉션과 대용량 응답을 거부하는 단일 HTTP 요청을 수행한다."""
    _validate_https_url(url)
    try:
        with (
            httpx.Client(timeout=timeout, follow_redirects=False) as client,
            client.stream(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
            ) as response,
        ):
            if 300 <= response.status_code < 400:
                raise ExternalServiceError("redirect response rejected")
            if response.status_code not in set(expected_statuses):
                raise ExternalServiceError(f"external service returned HTTP {response.status_code}")
            return _read_limited_json(response)
    except httpx.HTTPError as error:
        raise ExternalServiceError("external service request failed") from error


def request_status(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    expected_statuses: Iterable[int] = (200,),
) -> None:
    """응답 본문을 보존하지 않고 제한된 상태 코드만 확인한다."""
    _validate_https_url(url)
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
            response = client.request(method, url, headers=headers)
            if 300 <= response.status_code < 400:
                raise ExternalServiceError("redirect response rejected")
            if response.status_code not in set(expected_statuses):
                raise ExternalServiceError(f"external service returned HTTP {response.status_code}")
    except httpx.HTTPError as error:
        raise ExternalServiceError("external service request failed") from error


def _candidate_headers(settings: Settings) -> dict[str, str]:
    return {"X-API-Key": settings.candidate_api_key, "Accept": "application/json"}


def _portal_headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.portal_api_key}",
        "Accept": "application/json",
    }


def check_exchange_session(analysis_date: str) -> dict[str, Any]:
    settings = Settings.from_env()
    payload = request_json(
        "GET",
        f"{settings.candidate_base_url}/api/v1/pipeline-runs/eligibility",
        headers=_candidate_headers(settings),
        params={"date": analysis_date},
    )
    if (
        payload.get("date") != analysis_date
        or payload.get("exchange_mic") != settings.exchange_mic
        or not isinstance(payload.get("is_session"), bool)
        or not isinstance(payload.get("data_complete"), bool)
    ):
        raise ExternalServiceError("pipeline eligibility response is invalid")
    return {
        "analysis_date": analysis_date,
        "exchange_mic": settings.exchange_mic,
        "is_session": payload["is_session"],
        "data_complete": payload["data_complete"],
    }


def weekly_eligibility() -> dict[str, Any]:
    settings = Settings.from_env()
    payload = request_json(
        "GET",
        f"{settings.candidate_base_url}/api/v1/pipeline-runs/weekly/eligibility",
        headers=_candidate_headers(settings),
    )
    if not isinstance(payload.get("eligible"), bool):
        raise ExternalServiceError("weekly eligibility response is invalid")
    if payload["eligible"] and not all(
        isinstance(payload.get(key), str)
        for key in ("iso_week", "anchor_session", "input_manifest_id", "training_cutoff")
    ):
        raise ExternalServiceError("eligible weekly response is incomplete")
    return payload


def submit_weekly_training(request: dict[str, Any]) -> dict[str, Any]:
    model_purpose = request.get("model_purpose")
    iso_week = request.get("iso_week")
    if model_purpose not in {"SHORT_5D", "MEDIUM_20D"} or not isinstance(iso_week, str):
        raise ExternalServiceError("weekly submission input is invalid")
    settings = Settings.from_env()
    payload = request_json(
        "POST",
        f"{settings.candidate_base_url}/api/v1/pipeline-runs/weekly",
        headers={
            **_candidate_headers(settings),
            "Idempotency-Key": f"weekly:{iso_week}:{model_purpose}",
        },
        json_body={"model_purpose": model_purpose},
        expected_statuses=(202,),
    )
    if (
        not isinstance(payload.get("weekly_run_id"), str)
        or payload.get("model_purpose") != model_purpose
        or not isinstance(payload.get("status"), str)
    ):
        raise ExternalServiceError("weekly acceptance response is invalid")
    return {
        "weekly_run_id": payload["weekly_run_id"],
        "model_purpose": model_purpose,
        "status": payload["status"],
    }


def weekly_training_status(weekly_run_id: str) -> dict[str, Any]:
    settings = Settings.from_env()
    status_url = (
        f"{settings.candidate_base_url}/api/v1/pipeline-runs/weekly/"
        f"{quote(weekly_run_id, safe='')}"
    )
    payload = request_json(
        "GET",
        status_url,
        headers=_candidate_headers(settings),
    )
    if payload.get("weekly_run_id") != weekly_run_id or not isinstance(
        payload.get("status"), str
    ):
        raise ExternalServiceError("weekly status response is invalid")
    return payload


def activation_smoke(weekly_run_id: str) -> dict[str, Any]:
    settings = Settings.from_env()
    payload = request_json(
        "POST",
        (
            f"{settings.candidate_base_url}/api/v1/pipeline-runs/weekly/"
            f"{quote(weekly_run_id, safe='')}/activation-smoke"
        ),
        headers=_candidate_headers(settings),
        expected_statuses=(200,),
    )
    if payload.get("weekly_run_id") != weekly_run_id or not isinstance(
        payload.get("passed"), bool
    ):
        raise ExternalServiceError("activation smoke response is invalid")
    return payload


def _training_job_resource_id() -> str:
    value = os.environ.get("CANDIDATE_TRAINING_JOB_RESOURCE_ID", "").strip()
    if (
        not value.startswith("/subscriptions/")
        or ".." in value
        or "?" in value
        or "#" in value
        or any(character.isspace() for character in value)
    ):
        raise ExternalServiceError("CANDIDATE_TRAINING_JOB_RESOURCE_ID is invalid")
    return value


def _weekly_job_template(
    resource: dict[str, Any],
    *,
    weekly_run_id: str,
    model_purpose: str,
) -> dict[str, Any]:
    properties = resource.get("properties")
    template = properties.get("template") if isinstance(properties, dict) else None
    if not isinstance(template, dict):
        raise ExternalServiceError("training job template is invalid")
    result = {
        key: deepcopy(value)
        for key, value in template.items()
        if key in {"containers", "initContainers"} and value is not None
    }
    containers = result.get("containers")
    if not isinstance(containers, list):
        raise ExternalServiceError("training job containers are invalid")
    container = next(
        (
            candidate
            for candidate in containers
            if isinstance(candidate, dict)
            and candidate.get("name") == "candidate-training"
        ),
        None,
    )
    if container is None:
        raise ExternalServiceError("training job container is missing")
    environment = container.get("env")
    if not isinstance(environment, list):
        raise ExternalServiceError("training job environment is invalid")
    overrides = {
        "WEEKLY_RUN_ID": weekly_run_id,
        "MODEL_PURPOSE": model_purpose,
    }
    container["env"] = [
        entry
        for entry in environment
        if isinstance(entry, dict) and entry.get("name") not in overrides
    ] + [
        {"name": name, "value": value}
        for name, value in overrides.items()
    ]
    return result


def start_weekly_training_job(request: dict[str, Any]) -> dict[str, str]:
    from azure.identity import DefaultAzureCredential

    weekly_run_id = request.get("weekly_run_id")
    model_purpose = request.get("model_purpose")
    if not isinstance(weekly_run_id, str) or model_purpose not in {
        "SHORT_5D",
        "MEDIUM_20D",
    }:
        raise ExternalServiceError("training job input is invalid")
    settings = Settings.from_env()
    resource_id = _training_job_resource_id()
    credential = DefaultAzureCredential()
    resource = _arm_resource(resource_id, CONTAINER_APP_API_VERSION, credential)
    template = _weekly_job_template(
        resource,
        weekly_run_id=weekly_run_id,
        model_purpose=model_purpose,
    )
    token = credential.get_token(ARM_SCOPE).token
    payload = request_json(
        "POST",
        f"{ARM_ENDPOINT}{resource_id}/start?api-version={CONTAINER_APP_API_VERSION}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        json_body=template,
        expected_statuses=(200, 202),
    )
    execution_name = payload.get("name")
    if not isinstance(execution_name, str) or not execution_name:
        raise ExternalServiceError("training job start response is invalid")
    binding = request_json(
        "POST",
        (
            f"{settings.candidate_base_url}/api/v1/pipeline-runs/weekly/"
            f"{quote(weekly_run_id, safe='')}/execution"
        ),
        headers=_candidate_headers(settings),
        json_body={"execution_name": execution_name},
    )
    if binding.get("container_job_execution_name") != execution_name:
        raise ExternalServiceError("training job execution binding response is invalid")
    return {"execution_name": execution_name}


def weekly_training_job_status(execution_name: str) -> dict[str, Any]:
    from azure.identity import DefaultAzureCredential

    if not execution_name or "/" in execution_name or "\\" in execution_name:
        raise ExternalServiceError("training job execution name is invalid")
    resource_id = _training_job_resource_id()
    credential = DefaultAzureCredential()
    token = credential.get_token(ARM_SCOPE).token
    payload = request_json(
        "GET",
        (
            f"{ARM_ENDPOINT}{resource_id}/executions/{quote(execution_name, safe='')}"
            f"?api-version={CONTAINER_APP_API_VERSION}"
        ),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    properties = payload.get("properties")
    status = properties.get("status") if isinstance(properties, dict) else None
    if not isinstance(status, str):
        raise ExternalServiceError("training job status response is invalid")
    return {
        "execution_name": execution_name,
        "status": status,
        "terminal": status.casefold() in {"succeeded", "failed", "stopped"},
        "succeeded": status.casefold() == "succeeded",
    }


def _arm_resource(resource_id: str, api_version: str, credential: Any) -> dict[str, Any]:
    token = credential.get_token(ARM_SCOPE).token
    return request_json(
        "GET",
        f"{ARM_ENDPOINT}{resource_id}?api-version={api_version}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )


def _arm_request(
    method: str,
    resource_path: str,
    api_version: str,
    credential: Any,
    *,
    json_body: dict[str, Any] | None = None,
    expected_statuses: Iterable[int] = (200, 201, 202, 204),
) -> None:
    token = credential.get_token(ARM_SCOPE).token
    url = f"{ARM_ENDPOINT}{resource_path}?api-version={api_version}"
    _validate_https_url(url)
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
            response = client.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                json=json_body,
            )
    except httpx.HTTPError as error:
        raise ExternalServiceError("ARM request failed") from error
    if response.status_code in set(expected_statuses):
        return
    code = "Unknown"
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        candidate = error.get("code") if isinstance(error, dict) else None
        if isinstance(candidate, str) and candidate.replace("_", "").isalnum():
            code = candidate[:64]
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    raise ArmRequestError(response.status_code, code)


def _resource_readonly_locks(resource_id: str, credential: Any) -> list[dict[str, Any]]:
    payload = _arm_resource(
        f"{resource_id}/providers/Microsoft.Authorization/locks",
        LOCK_API_VERSION,
        credential,
    )
    locks = payload.get("value")
    if not isinstance(locks, list):
        raise ExternalServiceError("resource lock response is invalid")
    prefix = f"{resource_id}/providers/Microsoft.Authorization/locks/".casefold()
    return [
        lock
        for lock in locks
        if isinstance(lock, dict)
        and isinstance(lock.get("id"), str)
        and lock["id"].casefold().startswith(prefix)
        and isinstance(lock.get("properties"), dict)
        and str(lock["properties"].get("level", "")).casefold() == "readonly"
    ]


def _with_readonly_lock_retry(
    resource_id: str,
    credential: Any,
    operation: Callable[[], None],
) -> bool:
    try:
        operation()
        return False
    except ArmRequestError as error:
        if error.code.casefold() not in {"scopelocked", "lockviolation"}:
            raise
    removed: list[dict[str, Any]] = []
    try:
        for lock in _resource_readonly_locks(resource_id, credential):
            _arm_request("DELETE", lock["id"], LOCK_API_VERSION, credential)
            removed.append(lock)
        if not removed:
            raise ExternalServiceError("ARM remediation was blocked")
        operation()
        return True
    finally:
        for lock in removed:
            _arm_request(
                "PUT",
                lock["id"],
                LOCK_API_VERSION,
                credential,
                json_body={"properties": lock["properties"]},
            )


def _wait_for_resource(
    name: str,
    getter: Callable[[], dict[str, Any]],
    ready: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    for attempt in range(ARM_RECHECK_ATTEMPTS):
        resource = getter()
        if ready(resource):
            return resource
        if attempt + 1 < ARM_RECHECK_ATTEMPTS:
            time.sleep(ARM_RECHECK_SECONDS)
    raise ExternalServiceError(f"{name} remediation did not reach ready state")


def _require_state(
    name: str,
    resource: dict[str, Any],
    expected: str,
    *,
    property_name: str = "state",
) -> dict[str, Any]:
    properties = resource.get("properties")
    if not isinstance(properties, dict):
        raise ExternalServiceError(f"{name} ARM response is invalid")
    state = str(properties.get(property_name, "")).upper()
    if state != expected:
        raise ExternalServiceError(f"{name} is not {expected}")
    return properties


def _require_database_network(
    name: str,
    properties: dict[str, Any],
    expected_public_network_access: str,
) -> None:
    network = properties.get("network")
    if not isinstance(network, dict):
        raise ExternalServiceError(f"{name} network configuration is unavailable")
    if network.get("publicNetworkAccess") != expected_public_network_access:
        raise ExternalServiceError(f"{name} network configuration differs from contract")


def _properties(resource: dict[str, Any]) -> dict[str, Any]:
    properties = resource.get("properties")
    if not isinstance(properties, dict):
        raise ExternalServiceError("ARM response is invalid")
    return properties


def _ensure_started(
    name: str,
    resource_id: str,
    api_version: str,
    expected_state: str,
    credential: Any,
    remediated: list[str],
) -> dict[str, Any]:
    def get_resource() -> dict[str, Any]:
        return _arm_resource(resource_id, api_version, credential)

    resource = get_resource()
    state = str(_properties(resource).get("state", "")).upper()
    if state == "STOPPED":
        lock_removed = _with_readonly_lock_retry(
            resource_id,
            credential,
            lambda: _arm_request(
                "POST",
                f"{resource_id}/start",
                api_version,
                credential,
            ),
        )
        remediated.append(f"{name}:start")
        if lock_removed:
            remediated.append(f"{name}:readonly_lock_restored")
    elif state not in {expected_state, "STARTING"}:
        raise ExternalServiceError(f"{name} is not safely startable")
    return _wait_for_resource(
        name,
        get_resource,
        lambda value: str(_properties(value).get("state", "")).upper() == expected_state,
    )


def _ensure_tradingagents(
    settings: Settings,
    credential: Any,
    remediated: list[str],
) -> None:
    resource_id = settings.tradingagents_resource_id

    def get_resource() -> dict[str, Any]:
        return _arm_resource(resource_id, CONTAINER_APP_API_VERSION, credential)

    resource = get_resource()
    properties = _properties(resource)
    template = properties.get("template")
    scale = template.get("scale") if isinstance(template, dict) else None
    min_replicas = scale.get("minReplicas") if isinstance(scale, dict) else None
    if (
        not isinstance(template, dict)
        or not isinstance(scale, dict)
        or not isinstance(min_replicas, int)
        or isinstance(min_replicas, bool)
        or min_replicas < 0
    ):
        raise ExternalServiceError("TradingAgents scale configuration is invalid")
    running_status = str(properties.get("runningStatus", "")).upper()
    if min_replicas < settings.tradingagents_min_replicas:
        updated_template = {
            **template,
            "scale": {
                **scale,
                "minReplicas": settings.tradingagents_min_replicas,
            },
        }
        lock_removed = _with_readonly_lock_retry(
            resource_id,
            credential,
            lambda: _arm_request(
                "PATCH",
                resource_id,
                CONTAINER_APP_API_VERSION,
                credential,
                json_body={
                    "properties": {
                        "template": updated_template,
                    }
                },
            ),
        )
        remediated.append("tradingagents:min_replicas")
        if lock_removed:
            remediated.append("tradingagents:readonly_lock_restored")
        resource = get_resource()
        running_status = str(_properties(resource).get("runningStatus", "")).upper()
    if running_status == "STOPPED":
        lock_removed = _with_readonly_lock_retry(
            resource_id,
            credential,
            lambda: _arm_request(
                "POST",
                f"{resource_id}/start",
                CONTAINER_APP_API_VERSION,
                credential,
            ),
        )
        remediated.append("tradingagents:start")
        if lock_removed:
            remediated.append("tradingagents:readonly_lock_restored")
    elif running_status not in {"RUNNING", "STARTING", "PROGRESSING"}:
        raise ExternalServiceError("TradingAgents is not safely startable")

    def ready(value: dict[str, Any]) -> bool:
        current = _properties(value)
        current_template = current.get("template")
        current_scale = (
            current_template.get("scale") if isinstance(current_template, dict) else None
        )
        current_min = current_scale.get("minReplicas") if isinstance(current_scale, dict) else None
        return (
            str(current.get("runningStatus", "")).upper() == "RUNNING"
            and isinstance(current_min, int)
            and not isinstance(current_min, bool)
            and current_min >= settings.tradingagents_min_replicas
        )

    _wait_for_resource("TradingAgents", get_resource, ready)


def _storage_contract_matches(properties: dict[str, Any], settings: Settings) -> bool:
    network_acls = properties.get("networkAcls")
    return (
        isinstance(network_acls, dict)
        and properties.get("allowBlobPublicAccess") is False
        and properties.get("allowSharedKeyAccess") is False
        and properties.get("publicNetworkAccess")
        == settings.orchestrator_storage_public_network_access
        and network_acls.get("defaultAction")
        == settings.orchestrator_storage_network_default_action
    )


def _check_storage(
    settings: Settings,
    credential: Any,
    remediated: list[str],
) -> None:
    resource_id = settings.orchestrator_storage_resource_id

    def get_resource() -> dict[str, Any]:
        return _arm_resource(resource_id, STORAGE_API_VERSION, credential)

    storage = get_resource()
    properties = _properties(storage)
    if not _storage_contract_matches(properties, settings):
        network_acls = properties.get("networkAcls")
        preserved_network_acls = network_acls if isinstance(network_acls, dict) else {}
        lock_removed = _with_readonly_lock_retry(
            resource_id,
            credential,
            lambda: _arm_request(
                "PATCH",
                resource_id,
                STORAGE_API_VERSION,
                credential,
                json_body={
                    "properties": {
                        "allowBlobPublicAccess": False,
                        "allowSharedKeyAccess": False,
                        "publicNetworkAccess": (
                            settings.orchestrator_storage_public_network_access
                        ),
                        "networkAcls": {
                            **preserved_network_acls,
                            "defaultAction": (settings.orchestrator_storage_network_default_action),
                        },
                    }
                },
            ),
        )
        remediated.append("orchestrator_storage:restore_contract")
        if lock_removed:
            remediated.append("orchestrator_storage:readonly_lock_restored")
        storage = _wait_for_resource(
            "orchestrator storage",
            get_resource,
            lambda value: (
                str(_properties(value).get("provisioningState", "")).upper() == "SUCCEEDED"
                and _storage_contract_matches(_properties(value), settings)
            ),
        )
    properties = _require_state(
        "orchestrator storage",
        storage,
        "SUCCEEDED",
        property_name="provisioningState",
    )
    network_acls = properties.get("networkAcls")
    if not isinstance(network_acls, dict):
        raise ExternalServiceError("orchestrator storage network configuration is unavailable")
    expected = {
        "allowBlobPublicAccess": False,
        "allowSharedKeyAccess": False,
        "defaultToOAuthAuthentication": True,
        "supportsHttpsTrafficOnly": True,
        "minimumTlsVersion": "TLS1_2",
        "publicNetworkAccess": settings.orchestrator_storage_public_network_access,
    }
    if any(properties.get(key) != value for key, value in expected.items()):
        raise ExternalServiceError("orchestrator storage configuration differs from contract")
    if network_acls.get("defaultAction") != settings.orchestrator_storage_network_default_action:
        raise ExternalServiceError(
            "orchestrator storage network configuration differs from contract"
        )
    primary_endpoints = properties.get("primaryEndpoints")
    if not isinstance(primary_endpoints, dict):
        raise ExternalServiceError("orchestrator storage endpoints are unavailable")
    endpoints = {name: primary_endpoints.get(name) for name in ("blob", "queue", "table")}
    if any(not isinstance(endpoint, str) for endpoint in endpoints.values()):
        raise ExternalServiceError("orchestrator storage endpoints are unavailable")
    token = credential.get_token(STORAGE_SCOPE).token
    headers = {
        "Authorization": f"Bearer {token}",
        "x-ms-version": "2023-11-03",
    }
    access_checks = (
        (
            "HEAD",
            f"{str(endpoints['blob']).rstrip('/')}/"
            f"{quote(settings.orchestrator_storage_container_name, safe='')}"
            "?restype=container",
        ),
        ("GET", f"{str(endpoints['queue']).rstrip('/')}?comp=list&maxresults=1"),
        ("GET", f"{str(endpoints['table']).rstrip('/')}/Tables?$top=1"),
    )
    for method, url in access_checks:
        request_status(method, url, headers=headers)


def readiness_preflight() -> dict[str, str]:
    from azure.identity import DefaultAzureCredential

    settings = Settings.from_env()
    credential = DefaultAzureCredential()
    remediated: list[str] = []
    _ensure_started(
        "candidate_app",
        settings.candidate_resource_id,
        APP_SERVICE_API_VERSION,
        "RUNNING",
        credential,
        remediated,
    )
    _ensure_started(
        "portal_app",
        settings.portal_resource_id,
        APP_SERVICE_API_VERSION,
        "RUNNING",
        credential,
        remediated,
    )
    postgres = _ensure_started(
        "candidate_postgresql",
        settings.candidate_postgres_resource_id,
        POSTGRES_API_VERSION,
        "READY",
        credential,
        remediated,
    )
    postgres_properties = _properties(postgres)
    _require_database_network(
        "candidate PostgreSQL",
        postgres_properties,
        settings.candidate_postgres_public_network_access,
    )
    mysql = _ensure_started(
        "portal_mysql",
        settings.portal_mysql_resource_id,
        MYSQL_API_VERSION,
        "READY",
        credential,
        remediated,
    )
    mysql_properties = _properties(mysql)
    _require_database_network(
        "portal MySQL",
        mysql_properties,
        settings.portal_mysql_public_network_access,
    )
    _ensure_tradingagents(settings, credential, remediated)
    _check_storage(settings, credential, remediated)
    candidate_health = request_json(
        "GET",
        f"{settings.candidate_base_url}/health/ready",
        headers=_candidate_headers(settings),
    )
    portal_health = request_json("GET", f"{settings.portal_base_url}/readyz")
    if candidate_health.get("status") != "ready" or portal_health.get("status") != "ready":
        raise ExternalServiceError("application readiness check failed")
    checked = [
        "candidate",
        "candidate_postgresql",
        "portal",
        "portal_mysql",
        "orchestrator_storage",
    ]
    if settings.tradingagents_base_url:
        tradingagents_health = request_json("GET", f"{settings.tradingagents_base_url}/readyz")
        if tradingagents_health.get("status") != "ready":
            raise ExternalServiceError("TradingAgents readiness check failed")
        checked.append("tradingagents")
    return {
        "status": "ready",
        "checked": ",".join(checked),
        "remediated": ",".join(remediated) if remediated else "none",
    }


def submit_candidate_daily(request: dict[str, str]) -> dict[str, Any]:
    settings = Settings.from_env()
    analysis_date = request["analysis_date"]
    model_purpose = request["model_purpose"]
    existing_candidates = fetch_and_verify_candidates({**request, "existing_only": True})
    if existing_candidates:
        return {
            "status": "SKIPPED_EXISTING",
            "selection_run_id": existing_candidates[0]["selection_run_id"],
            "candidate_count": len(existing_candidates),
        }
    idempotency_key = f"orchestrator-daily-{analysis_date}-{model_purpose.lower()}"
    if model_purpose == "MEDIUM_20D":
        idempotency_key += "-top20-v1"
    payload = request_json(
        "POST",
        f"{settings.candidate_base_url}/api/v1/pipeline-runs",
        headers={
            **_candidate_headers(settings),
            "Idempotency-Key": idempotency_key,
        },
        json_body={
            "mode": "DAILY",
            "date": analysis_date,
            "with_candidates": True,
            "model_purpose": model_purpose,
        },
        expected_statuses=(202,),
        timeout=PORTAL_SUBMIT_TIMEOUT,
    )
    run_id = payload.get("process_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ExternalServiceError("Candidate response omitted process_run_id")
    return {"process_run_id": run_id, "status": str(payload.get("status", "PENDING"))}


def fetch_and_verify_llm_preselection(
    *,
    analysis_date: str,
    existing_only: bool = False,
) -> dict[str, Any] | None:
    settings = Settings.from_env()
    page = request_json(
        "GET",
        f"{settings.candidate_base_url}/api/v1/llm-preselections",
        headers=_candidate_headers(settings),
        params={"date": analysis_date, "limit": 1},
    )
    items = page.get("items")
    if not isinstance(items, list) or len(items) != 1:
        if existing_only:
            return None
        raise ExternalServiceError("LLM preselection response is invalid")
    run = items[0]
    candidates = run.get("candidates") if isinstance(run, dict) else None
    valid = (
        isinstance(run, dict)
        and run.get("price_session_date") == analysis_date
        and run.get("status") == "SUCCEEDED"
        and run.get("ranking_status") == "SUCCEEDED"
        and run.get("requested_count") == 20
        and run.get("selected_count") == 20
        and isinstance(candidates, list)
        and len(candidates) == 20
        and [item.get("position") for item in candidates if isinstance(item, dict)]
        == list(range(1, 21))
    )
    if not valid:
        if existing_only:
            return None
        raise ExternalServiceError("LLM preselection verification failed")
    return run


def candidate_run_status(process_run_id: str) -> dict[str, Any]:
    settings = Settings.from_env()
    payload = request_json(
        "GET",
        f"{settings.candidate_base_url}/api/v1/pipeline-runs/{quote(process_run_id, safe='')}",
        headers=_candidate_headers(settings),
    )
    status = payload.get("status")
    if not isinstance(status, str):
        raise ExternalServiceError("Candidate status response is invalid")
    status = status.upper()
    return {
        "process_run_id": process_run_id,
        "status": status,
        "terminal": status in CANDIDATE_TERMINAL,
        "failure_reason": payload.get("failure_reason"),
    }


def fetch_and_verify_candidates(request: dict[str, Any]) -> list[dict[str, Any]]:
    settings = Settings.from_env()
    analysis_date = request["analysis_date"]
    model_purpose = request["model_purpose"]
    existing_only = request.get("existing_only") is True
    cursor: str | None = None
    seen_cursors: set[str] = set()
    items: list[dict[str, Any]] = []
    while True:
        params: dict[str, Any] = {
            "date": analysis_date,
            "model_purpose": model_purpose,
            "limit": 100,
        }
        if cursor:
            params["cursor"] = cursor
        page = request_json(
            "GET",
            f"{settings.candidate_base_url}/api/v1/candidates",
            headers=_candidate_headers(settings),
            params=params,
        )
        page_items = page.get("items")
        if not isinstance(page_items, list):
            if existing_only:
                return []
            raise ExternalServiceError("Candidate list response is invalid")
        items.extend(item for item in page_items if isinstance(item, dict))
        cursor = page.get("next_cursor")
        if cursor is None:
            break
        if not isinstance(cursor, str) or cursor in seen_cursors:
            if existing_only:
                return []
            raise ExternalServiceError("Candidate cursor is invalid")
        seen_cursors.add(cursor)

    try:
        return _verify_candidate_items(
            items,
            analysis_date=analysis_date,
            model_purpose=model_purpose,
            allowed_statuses={"SUCCEEDED"} if existing_only else {"SUCCEEDED", "SHORTFALL"},
        )
    except ExternalServiceError:
        if existing_only:
            return []
        raise


def _verify_candidate_items(
    items: list[dict[str, Any]],
    *,
    analysis_date: str,
    model_purpose: str,
    allowed_statuses: set[str],
) -> list[dict[str, Any]]:
    expected_counts = (
        {20} if model_purpose == "MEDIUM_20D" else set(range(5, 11))
    )
    if len(items) not in expected_counts:
        raise ExternalServiceError(
            "Candidate selection count does not match the model-purpose policy"
        )
    tickers: set[str] = set()
    instruments: set[str] = set()
    selection_runs: set[str] = set()
    verified: list[dict[str, Any]] = []
    for position, item in enumerate(sorted(items, key=lambda value: value.get("position", 0)), 1):
        ticker = item.get("ticker")
        instrument_id = item.get("instrument_id")
        selection_run_id = item.get("selection_run_id")
        if (
            item.get("price_session_date") != analysis_date
            or item.get("status") not in allowed_statuses
            or item.get("model_purpose") != model_purpose
            or item.get("selected_count") != len(items)
            or item.get("requested_count") not in expected_counts
            or item.get("position") != position
            or not isinstance(ticker, str)
            or not isinstance(instrument_id, str)
            or not isinstance(selection_run_id, str)
            or ticker in tickers
            or instrument_id in instruments
        ):
            raise ExternalServiceError("Candidate selection verification failed")
        tickers.add(ticker)
        instruments.add(instrument_id)
        selection_runs.add(selection_run_id)
        verified.append(
            {
                "ticker": ticker,
                "instrument_id": instrument_id,
                "selection_run_id": selection_run_id,
                "model_purpose": model_purpose,
                "position": position,
            }
        )
    if len(selection_runs) != 1:
        raise ExternalServiceError("Candidate items must belong to one selection run")
    return verified


def _portal_aggregate(
    payload: dict[str, Any],
    *,
    expected_analysis_date: str,
    expected_selection_run_id: str,
    expected_model_purpose: str,
    expected_candidate_count: int,
) -> dict[str, Any]:
    daily_analysis_id = payload.get("daily_analysis_id")
    jobs = payload.get("jobs")
    if (
        not isinstance(daily_analysis_id, int)
        or payload.get("analysis_date") != expected_analysis_date
        or payload.get("selection_run_id") != expected_selection_run_id
        or payload.get("model_purpose") != expected_model_purpose
        or not isinstance(jobs, list)
        or len(jobs) != expected_candidate_count
        or not 5 <= len(jobs) <= 10
    ):
        raise ExternalServiceError("Portal candidate analysis response is invalid")
    normalized_jobs: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict) or job.get("status") not in {
            "pending",
            "running",
            "completed",
            "failed",
        }:
            raise ExternalServiceError("Portal job summary is invalid")
        normalized_jobs.append(
            {
                "status": job["status"],
                "decision": job.get("decision"),
                "has_result": job.get("has_result") is True,
                "error": job.get("error"),
            }
        )
    terminal = all(job["status"] in PORTAL_JOB_TERMINAL for job in normalized_jobs)
    succeeded = sum(job["status"] == "completed" and job["has_result"] for job in normalized_jobs)
    failed = sum(
        job["status"] == "failed" or job["status"] == "completed" and not job["has_result"]
        for job in normalized_jobs
    )
    return {
        "daily_analysis_id": daily_analysis_id,
        "analysis_date": expected_analysis_date,
        "selection_run_id": expected_selection_run_id,
        "model_purpose": expected_model_purpose,
        "candidate_count": expected_candidate_count,
        "jobs": normalized_jobs,
        "terminal": terminal,
        "succeeded": succeeded,
        "failed": failed,
    }


def submit_portal_candidate_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    settings = Settings.from_env()
    analysis_date = str(payload["analysis_date"])
    selection_run_id = str(payload["selection_run_id"])
    model_purpose = str(payload["model_purpose"])
    candidate_count = int(payload["candidate_count"])
    response = request_json(
        "POST",
        f"{settings.portal_base_url}/api/automation/candidate-analyses",
        headers=_portal_headers(settings),
        json_body={
            "analysis_date": analysis_date,
            "selection_run_id": selection_run_id,
            "model_purpose": model_purpose,
        },
        expected_statuses=(202,),
    )
    return _portal_aggregate(
        response,
        expected_analysis_date=analysis_date,
        expected_selection_run_id=selection_run_id,
        expected_model_purpose=model_purpose,
        expected_candidate_count=candidate_count,
    )


def portal_candidate_analysis_status(analysis: dict[str, Any]) -> dict[str, Any]:
    settings = Settings.from_env()
    daily_analysis_id = int(analysis["daily_analysis_id"])
    response = request_json(
        "GET",
        f"{settings.portal_base_url}/api/automation/candidate-analyses/"
        f"{quote(str(daily_analysis_id), safe='')}",
        headers=_portal_headers(settings),
    )
    return _portal_aggregate(
        response,
        expected_analysis_date=str(analysis["analysis_date"]),
        expected_selection_run_id=str(analysis["selection_run_id"]),
        expected_model_purpose=str(analysis["model_purpose"]),
        expected_candidate_count=int(analysis["candidate_count"]),
    )


def send_email(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        settings = Settings.from_env()
        if not settings.email_enabled:
            return {"sent": False, "disabled": True}

        from azure.communication.email import EmailClient
        from azure.identity import DefaultAzureCredential

        client = EmailClient(settings.acs_endpoint, DefaultAzureCredential())
        message = {
            "senderAddress": settings.email_sender,
            "recipients": {
                "to": [{"address": address} for address in settings.email_recipients],
            },
            "content": {
                "subject": str(payload["subject"])[:200],
                "plainText": str(payload["body"])[:20_000],
            },
        }
        result = client.begin_send(message).result(timeout=60)
        return {"sent": True, "id": getattr(result, "id", None)}
    except Exception as error:
        return {"sent": False, "error": type(error).__name__}
