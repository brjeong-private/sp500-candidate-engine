from __future__ import annotations

from datetime import date


def should_create_challenger(
    *,
    last_training_date: date | None,
    target_date: date,
    minimum_days: int = 28,
) -> bool:
    if minimum_days < 1:
        raise ValueError("minimum_days must be positive")
    if last_training_date is None:
        return True
    if target_date < last_training_date:
        raise ValueError("target_date cannot precede last_training_date")
    return (target_date - last_training_date).days >= minimum_days
