"""DST를 고려한 실행 게이트와 인스턴스 식별자를 계산한다."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
MODEL_PURPOSES = frozenset({"SHORT_5D", "MEDIUM_20D"})
TIMER_MODEL_PURPOSE = "MEDIUM_20D"


def scheduled_analysis_date(now_utc: datetime) -> date | None:
    """뉴욕 현지 시각 05:30에만 직전 달력 날짜를 반환한다."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    local = now_utc.astimezone(NEW_YORK)
    if (local.hour, local.minute) != (5, 30):
        return None
    return local.date() - timedelta(days=1)


def validate_target_date(value: object, *, today: date | None = None) -> date:
    """완료된 과거 날짜의 엄격한 ISO 문자열만 허용한다."""
    if not isinstance(value, str):
        raise ValueError("target_date must be a YYYY-MM-DD string")
    try:
        target_date = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("target_date must be a valid YYYY-MM-DD date") from error
    if target_date.isoformat() != value:
        raise ValueError("target_date must use YYYY-MM-DD format")
    if target_date >= (today or datetime.now(UTC).date()):
        raise ValueError("target_date must be a completed historical date")
    return target_date


def validate_model_purpose(value: object) -> str:
    if not isinstance(value, str) or value not in MODEL_PURPOSES:
        raise ValueError("model_purpose must be SHORT_5D or MEDIUM_20D")
    return value


def orchestration_instance_id(analysis_date: date, model_purpose: str) -> str:
    """날짜와 모델 목적 조합별 결정적 Durable 인스턴스 ID를 반환한다."""
    validated_purpose = validate_model_purpose(model_purpose)
    return f"candidate-daily-{analysis_date.isoformat()}-{validated_purpose.lower()}"
