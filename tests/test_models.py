"""Tests for Pydantic models and computed properties."""

from datetime import date, datetime

import pytest

from src.models.journal_entry import (
    ActivityCorrelation, Anomaly, ChatMessage, CorrelationMatrix, DailyRecord,
    DayRating, DaySummary, Goal, GoalProgress, LifeDimension, LifeScore,
    MetricDelta, Milestone, MilestoneType, MonthComparison,
    SleepInfo, StreakInfo, TaskEntry, TestikStatus,
)


class TestDayRating:
    def test_scores(self) -> None:
        assert DayRating.PERFECT.score == 6
        assert DayRating.VERY_BAD.score == 1

    def test_is_good(self) -> None:
        assert DayRating.PERFECT.is_good is True
        assert DayRating.NORMAL.is_good is False


class TestTestikStatus:
    def test_scores(self) -> None:
        assert TestikStatus.PLUS.score == 1
        assert TestikStatus.MINUS.score == -2


class TestDailyRecord:
    def test_productivity_high(self) -> None:
        r = DailyRecord(
            entry_date=date(2026, 2, 15), rating=DayRating.PERFECT,
            sleep=SleepInfo(sleep_hours=8.0), total_hours=10, tasks_count=6,
            had_workout=True, had_university=True, had_coding=True,
        )
        assert r.productivity_score >= 80

    def test_productivity_low(self) -> None:
        r = DailyRecord(
            entry_date=date(2026, 2, 15), rating=DayRating.VERY_BAD,
            sleep=SleepInfo(sleep_hours=3.0), total_hours=0, tasks_count=1,
        )
        assert r.productivity_score < 25


class TestLifeScore:
    def test_basic(self) -> None:
        ls = LifeScore(total=75.0, trend_delta=3.0, dimensions=[
            LifeDimension(name="Test", emoji="🧪", score=75.0, trend="↑"),
        ])
        assert ls.total == 75.0
        assert ls.dimensions[0].bar.count("█") == 8


class TestAnomaly:
    def test_basic(self) -> None:
        a = Anomaly(entry_date=date(2026, 2, 15), score=90, avg_score=60,
                    direction="high", activities=["GYM"])
        assert a.direction == "high"


class TestChatMessage:
    def test_basic(self) -> None:
        m = ChatMessage(id="1", user_id=123, role="user", content="hello")
        assert m.role == "user"


class TestMilestone:
    def test_basic(self) -> None:
        m = Milestone(id="m1", entry_date=date(2026, 1, 1),
                      milestone_type=MilestoneType.RECORD, emoji="🟢", title="Best!")
        assert m.milestone_type == MilestoneType.RECORD


class TestGoalProgress:
    def test_bar(self) -> None:
        g = Goal(id="g1", user_id=1, name="X", target_activity="X", target_count=4, period="week")
        p = GoalProgress(goal=g, current=3, target=4, percentage=75.0)
        assert "█" in p.bar
        assert not p.is_complete

    def test_complete(self) -> None:
        g = Goal(id="g2", user_id=1, name="Y", target_activity="Y", target_count=3, period="week")
        p = GoalProgress(goal=g, current=3, target=3, percentage=100.0)
        assert p.is_complete


class TestMetricDelta:
    def test_positive(self) -> None:
        m = MetricDelta(name="R", emoji="⭐", value_a=3.0, value_b=4.5)
        assert m.delta == 1.5
        assert m.arrow == "↑"

    def test_negative(self) -> None:
        m = MetricDelta(name="S", emoji="😴", value_a=7.0, value_b=6.0)
        assert m.delta == -1.0
        assert m.arrow == "↓"
