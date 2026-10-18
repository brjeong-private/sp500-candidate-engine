import asyncio
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sp500_candidate_engine import batch_pipeline


@pytest.mark.parametrize("failed_day", [None, 15, 16])
def test_collection_overlaps_fetches_but_commits_chronologically_and_isolates_failure(
    monkeypatch, failed_day,
):
    active = peak = 0
    committed = []

    async def collect(settings, *, collection_date, persist_after, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.02 if collection_date.day == 15 else 0.001)
            if collection_date.day == failed_day:
                raise RuntimeError("collection failed")
            if persist_after is not None:
                await persist_after.wait()
            committed.append(collection_date.day)
            return SimpleNamespace(collected_counts=lambda: {"bars": 1})
        finally:
            active -= 1

    monkeypatch.setattr(batch_pipeline, "_collect_backfill_date", collect)
    tracker, writer = MagicMock(), MagicMock()
    dates = tuple(date(2026, 10, day) for day in (17, 16, 15))
    asyncio.run(batch_pipeline._run_date_attempts(
        SimpleNamespace(backfill_max_concurrency=2), dates=dates, event_type="COLLECTION",
        process_run_id=uuid.uuid4(), tracker=tracker, writer=writer,
        reference_client=MagicMock(), massive=MagicMock(), raw_writer=MagicMock(),
        repository=MagicMock(), range_data=MagicMock(), parent_snapshot_ids={},
        sec_result=MagicMock(),
    ))
    assert peak == 2
    assert committed == [day for day in (15, 16, 17) if day != failed_day]
    assert tracker.start_attempt.call_count == 3
    assert writer.write.call_count == 3
    failures = [
        call for call in tracker.finish_attempt.call_args_list if not call.kwargs["success"]
    ]
    assert len(failures) == (0 if failed_day is None else 1)
