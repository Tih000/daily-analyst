"""Tests for Pydantic models and computed properties."""

from datetime import date

import pytest

from src.models.journal_entry import (
    DailyRecord,
    DayRating,
    DaySummary,
    SleepInfo,
    TaskEntry,
    TestikStatus,
)


class TestDayRating:
    def test_scores(self) -> None:
        assert DayRating.PERFECT.score == 6
        assert DayRating.VERY_GOOD.score == 5
        assert DayRating.GOOD.score == 4
        assert DayRating.NORMAL.score == 3
        assert DayRating.BAD.score == 2
        assert DayRating.VERY_BAD.score == 1

    def test_emojis(self) -> None:
        assert DayRating.PERFECT.emoji == "🤩"
        assert DayRating.VERY_BAD.emoji == "😫"


class TestTestikStatus:
    def test_scores(self) -> None:
        assert TestikStatus.PLUS.score == 1
        assert TestikStatus.MINUS.score == -2
        assert TestikStatus.MINUS_KATE.score == -1

    def test_labels(self) -> None:
        assert "PLUS" in TestikStatus.PLUS.label
        assert "solo" in TestikStatus.MINUS.label
        assert "Kate" in TestikStatus.MINUS_KATE.label


class TestTaskEntry:
    def test_basic(self) -> None:
        t = TaskEntry(id="t1", title="CODING", entry_date=date(2026, 2, 15), tags=["CODING"], hours=3.0)
        assert t.title == "CODING"
        assert t.hours == 3.0

    def test_none_hours(self) -> None:
        t = TaskEntry(id="t2", title="MARK", entry_date=date(2026, 2, 15))
        assert t.hours is None

    def test_coerce_hours(self) -> None:
        t = TaskEntry(id="t3", title="X", entry_date=date(2026, 2, 15), hours="2.5")  # type: ignore
        assert t.hours == 2.5


class TestDailyRecord:
    def test_productivity_score_high(self) -> None:
        r = DailyRecord(
            entry_date=date(2026, 2, 15),
            rating=DayRating.PERFECT,
            sleep=SleepInfo(sleep_hours=8.0),
            total_hours=10,
            tasks_count=6,
            had_workout=True,
            had_university=True,
            had_coding=True,
        )
        assert r.productivity_score >= 80

    def test_productivity_score_low(self) -> None:
        r = DailyRecord(
            entry_date=date(2026, 2, 15),
            rating=DayRating.VERY_BAD,
            sleep=SleepInfo(sleep_hours=3.0),
            total_hours=0,
            tasks_count=1,
        )
        assert r.productivity_score < 25

    def test_defaults(self) -> None:
        r = DailyRecord(entry_date=date(2026, 2, 15))
        assert r.total_hours == 0
        assert r.activities == []
        assert r.had_workout is False
        assert r.is_weekly_summary is False


class TestSleepInfo:
    def test_defaults(self) -> None:
        s = SleepInfo()
        assert s.sleep_hours is None
        assert s.woke_up_at is None
        assert s.recovery is None

    def test_with_values(self) -> None:
        s = SleepInfo(woke_up_at="12:30", sleep_duration="8:54", sleep_hours=8.9, recovery=81)
        assert s.sleep_hours == 8.9
        assert s.recovery == 81
