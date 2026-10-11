from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict

T = TypeVar("T")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


UTCDateTime = Annotated[datetime, AfterValidator(_utc)]


class ReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(ReadModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
