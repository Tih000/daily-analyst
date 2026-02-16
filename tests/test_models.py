"""Tests for Pydantic models and computed properties."""

from datetime import date, datetime

import pytest

from src.models.journal_entry import (
    ActivityCorrelation,
    CorrelationMatrix,
    DailyRecord,
    DayRating,
    DaySummary,
    Goal,
    GoalProgress,
    MetricDelta,
    MonthComparison,
    SleepInfo,
    StreakInfo,
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

    def test_is_good(self) -> None:
        assert DayRating.PERFECT.is_good is True
        assert DayRating.GOOD.is_good is True
        assert DayRating.NORMAL.is_good is False
        assert DayRating.BAD.is_good is False


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


class TestStreakInfo:
    def test_basic(self) -> None:
        s = StreakInfo(name="GYM", emoji="🏋️", current=5, record=12)
        assert s.current == 5
        assert s.record == 12

    def test_defaults(self) -> None:
        s = StreakInfo(name="X", emoji="?")
        assert s.current == 0
        assert s.record == 0


class TestGoal:
    def test_basic(self) -> None:
        g = Goal(id="g1", user_id=123, name="GYM", target_activity="GYM", target_count=4, period="week")
        assert g.label == "GYM 4/week"


class TestGoalProgress:
    def test_bar(self) -> None:
        g = Goal(id="g1", user_id=1, name="X", target_activity="X", target_count=4, period="week")
        p = GoalProgress(goal=g, current=3, target=4, percentage=75.0)
        assert "█" in p.bar
        assert p.is_complete is False

    def test_complete(self) -> None:
        g = Goal(id="g2", user_id=1, name="Y", target_activity="Y", target_count=3, period="week")
        p = GoalProgress(goal=g, current=3, target=3, percentage=100.0)
        assert p.is_complete is True


class TestMetricDelta:
    def test_positive(self) -> None:
        m = MetricDelta(name="Rating", emoji="⭐", value_a=3.0, value_b=4.5)
        assert m.delta == 1.5
        assert m.arrow == "↑"
        assert m.trend_emoji == "🟢"

    def test_negative(self) -> None:
        m = MetricDelta(name="Sleep", emoji="😴", value_a=7.0, value_b=6.0)
        assert m.delta == -1.0
        assert m.arrow == "↓"

    def test_zero(self) -> None:
        m = MetricDelta(name="X", emoji="?", value_a=5.0, value_b=5.0)
        assert m.delta == 0
        assert m.arrow == "→"


class TestCorrelationMatrix:
    def test_basic(self) -> None:
        corr = CorrelationMatrix(
            baseline_rating=3.5,
            correlations=[
                ActivityCorrelation(activity="GYM", avg_rating=4.5, count=10, vs_baseline=1.0),
            ],
        )
        assert corr.baseline_rating == 3.5
        assert len(corr.correlations) == 1
