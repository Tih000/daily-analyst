"""Pydantic models matching the real Notion 'Tasks' database structure."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ───────────────────────────────────────────────────────────────────


class DayRating(str, Enum):
    PERFECT = "perfect"
    VERY_GOOD = "very good"
    GOOD = "good"
    NORMAL = "normal"
    BAD = "bad"
    VERY_BAD = "very bad"

    @property
    def score(self) -> int:
        return {
            DayRating.PERFECT: 6, DayRating.VERY_GOOD: 5,
            DayRating.GOOD: 4, DayRating.NORMAL: 3,
            DayRating.BAD: 2, DayRating.VERY_BAD: 1,
        }[self]

    @property
    def emoji(self) -> str:
        return {
            DayRating.PERFECT: "🤩", DayRating.VERY_GOOD: "😁",
            DayRating.GOOD: "😊", DayRating.NORMAL: "😐",
            DayRating.BAD: "😔", DayRating.VERY_BAD: "😫",
        }[self]

    @property
    def is_good(self) -> bool:
        return self.score >= 4


class TestikStatus(str, Enum):
    PLUS = "PLUS"
    MINUS = "MINUS"
    MINUS_KATE = "MINUS_KATE"

    @property
    def score(self) -> int:
        return {TestikStatus.PLUS: 1, TestikStatus.MINUS: -2, TestikStatus.MINUS_KATE: -1}[self]

    @property
    def label(self) -> str:
        return {
            TestikStatus.PLUS: "PLUS ✅",
            TestikStatus.MINUS: "MINUS (solo) 🔴",
            TestikStatus.MINUS_KATE: "MINUS (Kate) 🟡",
        }[self]


# ── Task Entry ──────────────────────────────────────────────────────────────


class TaskEntry(BaseModel):
    id: str
    title: str
    entry_date: date
    tags: list[str] = Field(default_factory=list)
    checkbox: bool = False
    hours: Optional[float] = Field(default=None, ge=0)
    body_text: str = ""

    @field_validator("hours", mode="before")
    @classmethod
    def coerce_hours(cls, v: object) -> Optional[float]:
        if v is None:
            return None
        return float(v)


# ── Sleep Info ──────────────────────────────────────────────────────────────


class SleepInfo(BaseModel):
    woke_up_at: Optional[str] = None
    sleep_duration: Optional[str] = None
    sleep_hours: Optional[float] = None
    recovery: Optional[int] = None


# ── Daily Record ────────────────────────────────────────────────────────────


class DailyRecord(BaseModel):
    entry_date: date
    rating: Optional[DayRating] = None
    testik: Optional[TestikStatus] = None
    sleep: SleepInfo = Field(default_factory=SleepInfo)

    activities: list[str] = Field(default_factory=list)
    total_hours: float = 0
    tasks_count: int = 0
    tasks_completed: int = 0

    had_workout: bool = False
    had_university: bool = False
    had_coding: bool = False
    had_kate: bool = False

    journal_text: str = ""
    is_weekly_summary: bool = False

    @property
    def productivity_score(self) -> float:
        rating_score = (self.rating.score / 6 * 25) if self.rating else 12.5
        hours_score = min(self.total_hours / 10 * 25, 25)
        sleep_score = 0.0
        if self.sleep.sleep_hours is not None:
            if self.sleep.sleep_hours >= 4:
                sleep_score = min(self.sleep.sleep_hours / 8 * 20, 20)
        else:
            sleep_score = 10.0
        activity_score = min(self.tasks_count / 6 * 15, 15)
        bonus = (
            (5 if self.had_workout else 0)
            + (5 if self.had_university else 0)
            + (5 if self.had_coding else 0)
        )
        return round(rating_score + hours_score + sleep_score + activity_score + bonus, 1)


# ── Analytics Models ────────────────────────────────────────────────────────


class DaySummary(BaseModel):
    entry_date: date
    productivity_score: float
    rating: Optional[DayRating]
    total_hours: float
    activities: list[str]


class BurnoutRisk(BaseModel):
    risk_level: str
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


# ── Streak Models ───────────────────────────────────────────────────────────


class StreakInfo(BaseModel):
    name: str
    emoji: str
    current: int = 0
    record: int = 0
    last_date: Optional[date] = None


# ── Goal Models ─────────────────────────────────────────────────────────────


class Goal(BaseModel):
    id: str
    user_id: int
    name: str
    target_activity: str
    target_count: int
    period: str = "week"  # "week" or "month"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def label(self) -> str:
        return f"{self.name} {self.target_count}/{self.period}"


class GoalProgress(BaseModel):
    goal: Goal
    current: int
    target: int
    percentage: float

    @property
    def bar(self) -> str:
        filled = round(self.percentage / 100 * 8)
        return "█" * filled + "░" * (8 - filled)

    @property
    def is_complete(self) -> bool:
        return self.current >= self.target


# ── Comparison Models ───────────────────────────────────────────────────────


class MetricDelta(BaseModel):
    name: str
    emoji: str
    value_a: float
    value_b: float

    @property
    def delta(self) -> float:
        return round(self.value_b - self.value_a, 2)

    @property
    def arrow(self) -> str:
        if self.delta > 0:
            return "↑"
        elif self.delta < 0:
            return "↓"
        return "→"

    @property
    def trend_emoji(self) -> str:
        if self.delta > 0:
            return "🟢"
        elif self.delta < 0:
            return "🔴"
        return "⚪"


class MonthComparison(BaseModel):
    month_a: str
    month_b: str
    deltas: list[MetricDelta]
    ai_insights: str = ""


# ── Correlation Models ──────────────────────────────────────────────────────


class ActivityCorrelation(BaseModel):
    activity: str
    avg_rating: float
    count: int
    vs_baseline: float  # delta from overall average


class CorrelationMatrix(BaseModel):
    baseline_rating: float
    correlations: list[ActivityCorrelation]
    combo_insights: list[str] = Field(default_factory=list)
    ai_insights: str = ""


# ── Life Score ──────────────────────────────────────────────────────────────


class LifeDimension(BaseModel):
    name: str
    emoji: str
    score: float  # 0-100
    trend: str = "→"  # ↑ / ↓ / →

    @property
    def bar(self) -> str:
        filled = round(self.score / 100 * 10)
        return "█" * filled + "░" * (10 - filled)


class LifeScore(BaseModel):
    total: float  # 0-100
    trend_delta: float = 0  # vs previous period
    dimensions: list[LifeDimension] = Field(default_factory=list)
    trend_weeks: int = 0  # weeks of improvement


# ── Anomaly ─────────────────────────────────────────────────────────────────


class Anomaly(BaseModel):
    entry_date: date
    score: float
    avg_score: float
    direction: str  # "high" or "low"
    activities: list[str]
    explanation: str = ""


# ── Chat Memory ─────────────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    id: str
    user_id: int
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Milestone ───────────────────────────────────────────────────────────────


class MilestoneType(str, Enum):
    RECORD = "record"
    BURNOUT = "burnout"
    STREAK = "streak"
    PERFECT_WEEK = "perfect_week"
    BEST_MONTH = "best_month"
    LEVEL_UP = "level_up"
    CUSTOM = "custom"


class Milestone(BaseModel):
    id: str
    entry_date: date
    milestone_type: MilestoneType
    emoji: str
    title: str
    description: str = ""
    score: Optional[float] = None
