"""Pydantic models matching the real Notion 'Tasks' database structure."""

from __future__ import annotations

from datetime import date, time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ───────────────────────────────────────────────────────────────────


class DayRating(str, Enum):
    """Daily rating written at the bottom of MARK entry as 'MARK: <value>'."""

    PERFECT = "perfect"
    VERY_GOOD = "very good"
    GOOD = "good"
    NORMAL = "normal"
    BAD = "bad"
    VERY_BAD = "very bad"

    @property
    def score(self) -> int:
        """Numeric score (6 = best, 1 = worst)."""
        return {
            DayRating.PERFECT: 6,
            DayRating.VERY_GOOD: 5,
            DayRating.GOOD: 4,
            DayRating.NORMAL: 3,
            DayRating.BAD: 2,
            DayRating.VERY_BAD: 1,
        }[self]

    @property
    def emoji(self) -> str:
        return {
            DayRating.PERFECT: "🤩",
            DayRating.VERY_GOOD: "😁",
            DayRating.GOOD: "😊",
            DayRating.NORMAL: "😐",
            DayRating.BAD: "😔",
            DayRating.VERY_BAD: "😫",
        }[self]


class TestikStatus(str, Enum):
    """TESTIK status parsed from MARK entry body text."""

    PLUS = "PLUS"                # воздержание
    MINUS = "MINUS"              # мастурбация (solo)
    MINUS_KATE = "MINUS_KATE"    # половой акт с девушкой

    @property
    def score(self) -> int:
        """Positive = good for analytics."""
        return {
            TestikStatus.PLUS: 1,
            TestikStatus.MINUS: -2,
            TestikStatus.MINUS_KATE: -1,
        }[self]

    @property
    def label(self) -> str:
        return {
            TestikStatus.PLUS: "PLUS ✅",
            TestikStatus.MINUS: "MINUS (solo) 🔴",
            TestikStatus.MINUS_KATE: "MINUS (Kate) 🟡",
        }[self]


# ── Task Entry (single Notion page) ────────────────────────────────────────


class TaskEntry(BaseModel):
    """One row / page from the Notion 'Tasks' database."""

    id: str = Field(description="Notion page ID")
    title: str = Field(description="Page title (MARK, CODING, GYM, ...)")
    entry_date: date
    tags: list[str] = Field(default_factory=list, description="Multi-select Tags")
    checkbox: bool = False
    hours: Optional[float] = Field(default=None, ge=0, description="It took (hours)")
    body_text: str = Field(default="", description="Plain text from page content blocks")

    @field_validator("hours", mode="before")
    @classmethod
    def coerce_hours(cls, v: object) -> Optional[float]:
        if v is None:
            return None
        return float(v)


# ── Sleep Info (parsed from MARK body) ──────────────────────────────────────


class SleepInfo(BaseModel):
    """Sleep data parsed from MARK entry body text."""

    woke_up_at: Optional[str] = None          # "12:30"
    sleep_duration: Optional[str] = None       # "8:54" (hours:minutes)
    sleep_hours: Optional[float] = None        # 8.9 (decimal)
    recovery: Optional[int] = None             # Apple Watch recovery score


# ── Daily Record (aggregated from all tasks for one day) ────────────────────


class DailyRecord(BaseModel):
    """
    Aggregated daily view built from all TaskEntry pages for a single date.

    The MARK entry provides: rating, testik, sleep info, body journal text.
    Other entries provide: activities, total hours, categories.
    """

    entry_date: date
    rating: Optional[DayRating] = None
    testik: Optional[TestikStatus] = None
    sleep: SleepInfo = Field(default_factory=SleepInfo)

    # Aggregated from all tasks of the day
    activities: list[str] = Field(default_factory=list, description="All tag names for the day")
    total_hours: float = Field(default=0, description="Sum of 'It took (hours)' across all tasks")
    tasks_count: int = Field(default=0, description="Number of tasks / entries for the day")
    tasks_completed: int = Field(default=0, description="Number of checked tasks")

    # Specific activity flags
    had_workout: bool = False
    had_university: bool = False
    had_coding: bool = False
    had_kate: bool = False

    # MARK entry body (full journal text for GPT)
    journal_text: str = ""

    # Weekly summary flag
    is_weekly_summary: bool = False

    @property
    def productivity_score(self) -> float:
        """Composite productivity metric (0-100)."""
        rating_score = (self.rating.score / 6 * 25) if self.rating else 12.5
        hours_score = min(self.total_hours / 10 * 25, 25)
        sleep_score = 0.0
        if self.sleep.sleep_hours is not None:
            if self.sleep.sleep_hours >= 4:
                sleep_score = min(self.sleep.sleep_hours / 8 * 20, 20)
        else:
            sleep_score = 10.0  # neutral when unknown
        activity_score = min(self.tasks_count / 6 * 15, 15)
        bonus = (
            (5 if self.had_workout else 0)
            + (5 if self.had_university else 0)
            + (5 if self.had_coding else 0)
        )
        return round(rating_score + hours_score + sleep_score + activity_score + bonus, 1)


# ── Analytics Models ────────────────────────────────────────────────────────


class DaySummary(BaseModel):
    """Short summary for ranking."""

    entry_date: date
    productivity_score: float
    rating: Optional[DayRating]
    total_hours: float
    activities: list[str]


class BurnoutRisk(BaseModel):
    risk_level: str = Field(description="low / medium / high / critical")
    risk_score: float = Field(ge=0, le=100)
    factors: list[str]
    recommendation: str


class MonthAnalysis(BaseModel):
    month: str
    total_days: int
    avg_rating_score: float
    avg_hours: float
    avg_sleep_hours: Optional[float]
    total_tasks: int
    workout_rate: float
    university_rate: float
    coding_rate: float
    kate_rate: float
    best_day: Optional[DaySummary] = None
    worst_day: Optional[DaySummary] = None
    ai_insights: str = ""
    activity_breakdown: dict[str, int] = Field(default_factory=dict)
