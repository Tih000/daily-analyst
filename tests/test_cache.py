"""Tests for SQLite cache service."""

from datetime import date, timedelta

import pytest

from src.models.journal_entry import (
    DailyRecord,
    DayRating,
    SleepInfo,
    TaskEntry,
    TestikStatus,
)
from src.utils.cache import CacheService


class TestCacheService:
    def test_init(self, cache_service: CacheService) -> None:
        assert cache_service.get_daily_records() == []

    def test_upsert_and_get_tasks(self, cache_service: CacheService, sample_tasks: list[TaskEntry]) -> None:
        count = cache_service.upsert_tasks(sample_tasks)
        assert count == 3
        tasks = cache_service.get_tasks(date(2026, 2, 1), date(2026, 2, 28))
        assert len(tasks) == 3

    def test_tasks_idempotent(self, cache_service: CacheService, sample_tasks: list[TaskEntry]) -> None:
        cache_service.upsert_tasks(sample_tasks)
        cache_service.upsert_tasks(sample_tasks)
        tasks = cache_service.get_tasks(date(2026, 2, 1), date(2026, 2, 28))
        assert len(tasks) == 3

    def test_upsert_daily_records(self, cache_service: CacheService, sample_records: list[DailyRecord]) -> None:
        count = cache_service.upsert_daily_records(sample_records)
        assert count == len(sample_records)

        retrieved = cache_service.get_daily_records()
        assert len(retrieved) == len(sample_records)

    def test_daily_fields_roundtrip(self, cache_service: CacheService) -> None:
        record = DailyRecord(
            entry_date=date(2026, 6, 15),
            rating=DayRating.PERFECT,
            testik=TestikStatus.PLUS,
            sleep=SleepInfo(woke_up_at="10:00", sleep_hours=8.5, recovery=85),
            activities=["MARK", "CODING", "GYM"],
            total_hours=9.5,
            tasks_count=5,
            tasks_completed=4,
            had_workout=True,
            had_university=False,
            had_coding=True,
            had_kate=True,
            journal_text="Full roundtrip test",
        )
        cache_service.upsert_daily_records([record])
        results = cache_service.get_daily_records(date(2026, 6, 1), date(2026, 6, 30))
        assert len(results) == 1
        r = results[0]
        assert r.rating == DayRating.PERFECT
        assert r.testik == TestikStatus.PLUS
        assert r.sleep.sleep_hours == 8.5
        assert r.sleep.recovery == 85
        assert "CODING" in r.activities
        assert r.total_hours == 9.5
        assert r.had_workout is True
        assert r.had_kate is True
        assert r.journal_text == "Full roundtrip test"

    def test_cache_freshness(self, cache_service: CacheService) -> None:
        assert not cache_service.is_cache_fresh()
        cache_service.mark_synced()
        assert cache_service.is_cache_fresh()

    def test_get_recent(self, cache_service: CacheService, sample_records: list[DailyRecord]) -> None:
        cache_service.upsert_daily_records(sample_records)
        recent = cache_service.get_recent_daily(days=7)
        for r in recent:
            assert r.entry_date >= date.today() - timedelta(days=7)

    def test_monthly(self, cache_service: CacheService) -> None:
        records = [
            DailyRecord(entry_date=date(2026, 3, d), rating=DayRating.GOOD)
            for d in range(1, 11)
        ]
        cache_service.upsert_daily_records(records)
        march = cache_service.get_daily_for_month(2026, 3)
        assert len(march) == 10

    def test_exclude_weekly(self, cache_service: CacheService) -> None:
        records = [
            DailyRecord(entry_date=date(2026, 3, 1), rating=DayRating.GOOD),
            DailyRecord(entry_date=date(2026, 3, 7), is_weekly_summary=True),
        ]
        cache_service.upsert_daily_records(records)
        result = cache_service.get_daily_records(date(2026, 3, 1), date(2026, 3, 31), exclude_weekly=True)
        assert len(result) == 1
        assert result[0].entry_date == date(2026, 3, 1)
