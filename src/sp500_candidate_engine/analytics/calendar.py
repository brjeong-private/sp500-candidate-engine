from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from importlib.metadata import version

import exchange_calendars

from sp500_candidate_engine.analytics.db import execute_many
from sp500_candidate_engine.database import _canonical_hash


@dataclass(frozen=True)
class ExchangeSession:
    exchange_mic: str
    session_date: date
    open_at: datetime
    close_at: datetime
    is_early_close: bool
    status: str = "OPEN"


@dataclass(frozen=True)
class ExchangeCalendarDataset:
    exchange_mic: str
    start_date: date
    end_date: date
    library_name: str
    library_version: str
    version_hash: str
    sessions: tuple[ExchangeSession, ...]


class ExchangeCalendarRepository:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def persist(
        self,
        *,
        dataset: ExchangeCalendarDataset,
        source_snapshot_id: object,
    ) -> None:
        execute_many(
            self.connection,  # type: ignore[arg-type]
            """
            INSERT INTO ref.exchange_session(
                calendar_version, exchange_mic, session_date,
                open_at, close_at, is_early_close, status, source_snapshot_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (calendar_version, exchange_mic, session_date) DO NOTHING
            """,
            [
                (
                    dataset.version_hash,
                    session.exchange_mic,
                    session.session_date,
                    session.open_at,
                    session.close_at,
                    session.is_early_close,
                    session.status,
                    source_snapshot_id,
                )
                for session in dataset.sessions
            ],
        )


def build_exchange_calendar(
    *,
    exchange_mic: str,
    start_date: date,
    end_date: date,
) -> ExchangeCalendarDataset:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    calendar_name = {"XNYS": "XNYS", "XNAS": "XNAS"}.get(exchange_mic)
    if calendar_name is None:
        raise ValueError(f"Unsupported exchange MIC: {exchange_mic}")

    calendar = exchange_calendars.get_calendar(calendar_name)
    schedule = calendar.schedule.loc[start_date.isoformat() : end_date.isoformat()]
    early_closes = {timestamp.date() for timestamp in calendar.early_closes}
    sessions = tuple(
        ExchangeSession(
            exchange_mic=exchange_mic,
            session_date=index.date(),
            open_at=row["open"].to_pydatetime(),
            close_at=row["close"].to_pydatetime(),
            is_early_close=index.date() in early_closes,
        )
        for index, row in schedule.iterrows()
    )
    library_version = version("exchange-calendars")
    version_hash = _canonical_hash(
        {
            "exchange_mic": exchange_mic,
            "start_date": start_date,
            "end_date": end_date,
            "library": "exchange_calendars",
            "library_version": library_version,
            "sessions": sessions,
        }
    )
    return ExchangeCalendarDataset(
        exchange_mic=exchange_mic,
        start_date=start_date,
        end_date=end_date,
        library_name="exchange_calendars",
        library_version=library_version,
        version_hash=version_hash,
        sessions=sessions,
    )
