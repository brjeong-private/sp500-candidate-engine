"""DST를 고려한 실행 게이트와 인스턴스 식별자를 계산한다."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


def scheduled_analysis_date(now_utc: datetime) -> date | None:
    """뉴욕 현지 시각 05:30에만 직전 달력 날짜를 반환한다."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    local = now_utc.astimezone(NEW_YORK)
    if (local.hour, local.minute) != (5, 30):
        return None
    return local.date() - timedelta(days=1)


def orchestration_instance_id(analysis_date: date) -> str:
    """날짜별로 재사용되는 결정적 Durable 인스턴스 ID를 반환한다."""
    return f"candidate-daily-{analysis_date.isoformat()}"
