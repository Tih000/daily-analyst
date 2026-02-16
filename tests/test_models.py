"""Tests for Pydantic models and their computed properties."""

from datetime import date

import pytest

from src.models.journal_entry import (
    BurnoutRisk,
    DaySummary,
    JournalEntry,
    MonthAnalysis,
    Mood,
    Testik,
)


class TestMoodEnum:
    def test_scores(self) -> None:
        assert Mood.PERFECT.score == 5
        assert Mood.GOOD.score == 4
        assert Mood.NORMAL.score == 3
        assert Mood.BAD.score == 2
        assert Mood.VERY_BAD.score == 1

    def test_emojis(self) -> None:
        assert Mood.PERFECT.emoji == "🤩"
        assert Mood.VERY_BAD.emoji == "😫"


class TestTestikEnum:
    def test_scores(self) -> None:
        assert Testik.PLUS.score == 1
        assert Testik.MINUS_KATE.score == -1
        assert Testik.MINUS_SOLO.score == -2


class TestJournalEntry:
    def test_basic_creation(self) -> None:
        entry = JournalEntry(
            id="test-1",
            entry_date=date(2025, 1, 15),
            mood=Mood.GOOD,
            hours_worked=8,
            tasks_completed=5,
            sleep_hours=7.5,
        )
        assert entry.id == "test-1"
        assert entry.mood == Mood.GOOD
        assert entry.hours_worked == 8.0

    def test_defaults(self) -> None:
        entry = JournalEntry(id="test-2", entry_date=date(2025, 1, 1))
        assert entry.hours_worked == 0
        assert entry.tasks_completed == 0
        assert entry.workout is False
        assert entry.earnings_usd == 0

    def test_coerce_none_to_zero(self) -> None:
        entry = JournalEntry(
            id="test-3",
            entry_date=date(2025, 1, 1),
            hours_worked=None,  # type: ignore[arg-type]
            tasks_completed=None,  # type: ignore[arg-type]
            sleep_hours=None,  # type: ignore[arg-type]
        )
        assert entry.hours_worked == 0.0
        assert entry.tasks_completed == 0
        assert entry.sleep_hours == 0.0

    def test_productivity_score_high(self) -> None:
        entry = JournalEntry(
            id="high",
            entry_date=date(2025, 1, 1),
            mood=Mood.PERFECT,
            hours_worked=10,
            tasks_completed=8,
            sleep_hours=8,
            workout=True,
            university=True,
            earnings_usd=100,
        )
        score = entry.productivity_score
        assert 85 <= score <= 100

    def test_productivity_score_low(self) -> None:
        entry = JournalEntry(
            id="low",
            entry_date=date(2025, 1, 1),
            mood=Mood.VERY_BAD,
            hours_worked=0,
            tasks_completed=0,
            sleep_hours=3,  # < 4, so sleep_score = 0
        )
        score = entry.productivity_score
        assert score < 15

    def test_validation_bounds(self) -> None:
        with pytest.raises(Exception):
            JournalEntry(
                id="bad",
                entry_date=date(2025, 1, 1),
                hours_worked=-1,
            )


class TestBurnoutRisk:
    def test_creation(self) -> None:
        risk = BurnoutRisk(
            risk_level="high",
            risk_score=75,
            factors=["Low sleep", "Bad mood"],
            recommendation="Take a break.",
        )
        assert risk.risk_level == "high"
        assert len(risk.factors) == 2


class TestDaySummary:
    def test_creation(self) -> None:
        summary = DaySummary(
            entry_date=date(2025, 1, 15),
            productivity_score=82.5,
            mood=Mood.GOOD,
            hours_worked=8,
            tasks_completed=6,
        )
        assert summary.productivity_score == 82.5
