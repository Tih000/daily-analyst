"""Tests for SQLite cache service (with goals, chat, milestones)."""

from datetime import date, timedelta

import pytest

from src.models.journal_entry import (
    DailyRecord, DayRating, Goal, Milestone, MilestoneType,
    SleepInfo, TaskEntry, TestikStatus,
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
            total_hours=9.5, tasks_count=5, tasks_completed=4,
            had_workout=True, had_university=False, had_coding=True, had_kate=True,
            journal_text="Full roundtrip test",
        )
        cache_service.upsert_daily_records([record])
        results = cache_service.get_daily_records(date(2026, 6, 1), date(2026, 6, 30))
        assert len(results) == 1
        r = results[0]
        assert r.rating == DayRating.PERFECT
        assert r.sleep.sleep_hours == 8.5
        assert r.journal_text == "Full roundtrip test"

    def test_cache_freshness(self, cache_service: CacheService) -> None:
        assert not cache_service.is_cache_fresh()
        cache_service.mark_synced()
        assert cache_service.is_cache_fresh()

    def test_exclude_weekly(self, cache_service: CacheService) -> None:
        records = [
            DailyRecord(entry_date=date(2026, 3, 1), rating=DayRating.GOOD),
            DailyRecord(entry_date=date(2026, 3, 7), is_weekly_summary=True),
        ]
        cache_service.upsert_daily_records(records)
        result = cache_service.get_daily_records(date(2026, 3, 1), date(2026, 3, 31), exclude_weekly=True)
        assert len(result) == 1


class TestGoalsPersistence:
    def test_upsert_and_get(self, cache_service: CacheService, sample_goals: list[Goal]) -> None:
        for g in sample_goals:
            cache_service.upsert_goal(g)
        assert len(cache_service.get_goals(123)) == 3

    def test_delete_goal(self, cache_service: CacheService, sample_goals: list[Goal]) -> None:
        for g in sample_goals:
            cache_service.upsert_goal(g)
        assert cache_service.delete_goal("g1")
        assert len(cache_service.get_goals(123)) == 2


class TestChatMemory:
    def test_save_and_get(self, cache_service: CacheService) -> None:
        cache_service.save_message(123, "user", "hello")
        cache_service.save_message(123, "assistant", "hi there")
        msgs = cache_service.get_recent_messages(123)
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"

    def test_different_users(self, cache_service: CacheService) -> None:
        cache_service.save_message(123, "user", "hello")
        cache_service.save_message(456, "user", "world")
        assert len(cache_service.get_recent_messages(123)) == 1
        assert len(cache_service.get_recent_messages(456)) == 1

    def test_cleanup(self, cache_service: CacheService) -> None:
        for i in range(10):
            cache_service.save_message(123, "user", f"msg {i}")
        deleted = cache_service.cleanup_messages(123, keep=5)
        assert deleted == 5
        assert len(cache_service.get_recent_messages(123)) == 5

    def test_cleanup_noop(self, cache_service: CacheService) -> None:
        cache_service.save_message(123, "user", "only one")
        assert cache_service.cleanup_messages(123, keep=50) == 0


class TestMilestones:
    def test_add_and_get(self, cache_service: CacheService, sample_milestones) -> None:
        for m in sample_milestones:
            cache_service.add_milestone(m)
        milestones = cache_service.get_milestones(2026)
        assert len(milestones) == 2

    def test_get_by_year(self, cache_service: CacheService, sample_milestones) -> None:
        for m in sample_milestones:
            cache_service.add_milestone(m)
        assert len(cache_service.get_milestones(2025)) == 0
        assert len(cache_service.get_milestones(2026)) == 2

    def test_get_all(self, cache_service: CacheService, sample_milestones) -> None:
        for m in sample_milestones:
            cache_service.add_milestone(m)
        assert len(cache_service.get_milestones()) == 2
