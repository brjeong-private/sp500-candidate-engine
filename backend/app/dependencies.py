from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from backend.app.config import BackendSettings
from sp500_candidate_engine.database import Database

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_database(request: Request) -> Database:
    return request.app.state.database


def require_api_key(
    request: Request,
    supplied: Annotated[str | None, Security(api_key_header)],
) -> None:
    settings: BackendSettings = request.app.state.backend_settings
    if supplied is None or not secrets.compare_digest(
        supplied.encode("utf-8"), settings.api_key.encode("utf-8")
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
