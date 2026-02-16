"""Pydantic models for journal entries and analytics responses."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ───────────────────────────────────────────────────────────────────

class Mood(str, Enum):
    PERFECT = "PERFECT"
    GOOD = "GOOD"
    NORMAL = "NORMAL"
    BAD = "BAD"
    VERY_BAD = "VERY_BAD"

    @property
    def score(self) -> int:
        """Numeric score for analytics (5 = best)."""
        return {
            Mood.PERFECT: 5,
            Mood.GOOD: 4,
            Mood.NORMAL: 3,
            Mood.BAD: 2,
            Mood.VERY_BAD: 1,
        }[self]

    @property
    def emoji(self) -> str:
        return {
            Mood.PERFECT: "🤩",
            Mood.GOOD: "😊",
            Mood.NORMAL: "😐",
            Mood.BAD: "😔",
            Mood.VERY_BAD: "😫",
        }[self]


class Testik(str, Enum):
    PLUS = "PLUS"
    MINUS_KATE = "MINUS_KATE"
    MINUS_SOLO = "MINUS_SOLO"

    @property
    def score(self) -> int:
        return {
            Testik.PLUS: 1,
            Testik.MINUS_KATE: -1,
            Testik.MINUS_SOLO: -2,
        }[self]


# ── Journal Entry ───────────────────────────────────────────────────────────

class JournalEntry(BaseModel):
    """Single daily journal entry from Notion."""

    id: str = Field(description="Notion page ID")
    entry_date: date = Field(description="Date of the entry")
    mood: Optional[Mood] = None
    hours_worked: float = Field(default=0, ge=0, le=24)
    tasks_completed: int = Field(default=0, ge=0)
    testik: Optional[Testik] = None
    workout: bool = False
    university: bool = False
    earnings_usd: float = Field(default=0, ge=0)
    sleep_hours: float = Field(default=0, ge=0, le=24)
    notes: str = ""

    @field_validator("hours_worked", "sleep_hours", mode="before")
    @classmethod
    def coerce_float(cls, v: object) -> float:
        if v is None:
            return 0.0
        return float(v)

    @field_validator("tasks_completed", mode="before")
    @classmethod
    def coerce_int(cls, v: object) -> int:
        if v is None:
            return 0
        return int(v)

    @property
    def productivity_score(self) -> float:
        """Composite productivity metric (0-100)."""
        mood_score = (self.mood.score / 5 * 25) if self.mood else 12.5
        work_score = min(self.hours_worked / 10 * 25, 25)
        tasks_score = min(self.tasks_completed / 8 * 20, 20)
        sleep_score = min(self.sleep_hours / 8 * 15, 15) if self.sleep_hours >= 4 else 0
        bonus = (5 if self.workout else 0) + (5 if self.university else 0) + (5 if self.earnings_usd > 0 else 0)
        return round(mood_score + work_score + tasks_score + sleep_score + bonus, 1)


# ── Analytics Models ────────────────────────────────────────────────────────

class DaySummary(BaseModel):
    """Summarized view for best-days ranking."""

    entry_date: date
    productivity_score: float
    mood: Optional[Mood]
    hours_worked: float
    tasks_completed: int


class BurnoutRisk(BaseModel):
    """Burnout risk assessment result."""

    risk_level: str = Field(description="low / medium / high / critical")
    risk_score: float = Field(ge=0, le=100)
    factors: list[str]
    recommendation: str


class MonthAnalysis(BaseModel):
    """Monthly analytics summary."""

    month: str
    total_entries: int
    avg_mood_score: float
    avg_hours_worked: float
    avg_sleep_hours: float
    total_earnings: float
    total_tasks: int
    workout_rate: float
    university_rate: float
    best_day: Optional[DaySummary] = None
    worst_day: Optional[DaySummary] = None
    ai_insights: str = ""


class CorrelationResult(BaseModel):
    """Correlation analysis result."""

    factor_a: str
    factor_b: str
    correlation: float = Field(ge=-1, le=1)
    interpretation: str


class ForecastResult(BaseModel):
    """Prediction / forecast result."""

    period: str
    predicted_value: float
    confidence: float = Field(ge=0, le=1)
    reasoning: str


class WeakSpot(BaseModel):
    """Identified weak spot in productivity."""

    area: str
    severity: str
    description: str
    suggestion: str
