from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import date

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

# A single-worker deployment deliberately invalidates cursors on restart.
_CURSOR_KEY = secrets.token_bytes(32)


class Cursor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int
    scope: str
    binding: str
    position: list[str]


def binding(filters: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(filters, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def encode_cursor(scope: str, filters: dict[str, object], position: list[str]) -> str:
    payload = (
        Cursor(version=1, scope=scope, binding=binding(filters), position=position)
        .model_dump_json()
        .encode()
    )
    signature = hmac.digest(_CURSOR_KEY, payload, "sha256")
    return base64.urlsafe_b64encode(signature + payload).decode().rstrip("=")


def decode_cursor(
    cursor: str | None, scope: str, filters: dict[str, object], key_count: int
) -> list[str] | None:
    if cursor is None:
        return None
    try:
        if len(cursor) > 4096:
            raise ValueError
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        signature, payload = raw[:32], raw[32:]
        if not hmac.compare_digest(signature, hmac.digest(_CURSOR_KEY, payload, "sha256")):
            raise ValueError
        parsed = Cursor.model_validate_json(payload)
        if (
            parsed.version != 1
            or parsed.scope != scope
            or parsed.binding != binding(filters)
            or len(parsed.position) != key_count
        ):
            raise ValueError
        return parsed.position
    except (ValueError, ValidationError):
        raise HTTPException(422, "Invalid cursor for these filters") from None


def date_filters(
    exact_date: date | None, start_date: date | None, end_date: date | None
) -> tuple[date | None, date | None]:
    if exact_date is not None:
        if start_date is not None or end_date is not None:
            raise HTTPException(422, "date and start_date/end_date are mutually exclusive")
        return exact_date, exact_date
    if (start_date is None) != (end_date is None):
        raise HTTPException(422, "start_date and end_date must be provided together")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(422, "start_date must not exceed end_date")
    return start_date, end_date


def collection_window(start_date: date, end_date: date) -> None:
    if not 0 <= (end_date - start_date).days <= 9:
        raise HTTPException(422, "Collection range must contain 1 to 10 inclusive calendar days")


def page_limit(limit: int) -> None:
    if not 1 <= limit <= 500:
        raise HTTPException(422, "Page size must be between 1 and 500")
