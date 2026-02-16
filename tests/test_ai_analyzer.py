"""Tests for AI analyzer (with mocked GPT calls)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.journal_entry import JournalEntry, Mood, Testik
from src.services.ai_analyzer import AIAnalyzer


@pytest.fixture
def analyzer() -> AIAnalyzer:
    """AI Analyzer with mocked OpenAI client."""
    with patch("src.services.ai_analyzer.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            openai=MagicMock(api_key="sk-test", model="gpt-4o-mini"),
        )
        a = AIAnalyzer()
    a._ask_gpt = AsyncMock(return_value="Test AI response with 📊 insights.")
    return a


class TestAIAnalyzerBurnout:
    @pytest.mark.asyncio
    async def test_predict_burnout_high_risk(
        self, analyzer: AIAnalyzer, burnout_entries: list[JournalEntry]
    ) -> None:
        """Burnout entries should trigger high/critical risk."""
        risk = await analyzer.predict_burnout(burnout_entries)
        assert risk.risk_level in ("high", "critical")
        assert risk.risk_score >= 45
        assert len(risk.factors) > 0

    @pytest.mark.asyncio
    async def test_predict_burnout_low_risk(
        self, analyzer: AIAnalyzer, sample_entries: list[JournalEntry]
    ) -> None:
        """Normal entries should have lower risk."""
        risk = await analyzer.predict_burnout(sample_entries)
        assert risk.risk_score < 80  # Not critical for mixed data

    @pytest.mark.asyncio
    async def test_predict_burnout_insufficient_data(self, analyzer: AIAnalyzer) -> None:
        """Too few entries should return 'unknown' risk."""
        risk = await analyzer.predict_burnout([])
        assert risk.risk_level == "unknown"


class TestAIAnalyzerMonth:
    @pytest.mark.asyncio
    async def test_analyze_month(
        self, analyzer: AIAnalyzer, sample_entries: list[JournalEntry]
    ) -> None:
        """Monthly analysis should return complete stats."""
        result = await analyzer.analyze_month(sample_entries, "2025-01")
        assert result.total_entries == len(sample_entries)
        assert result.avg_mood_score > 0
        assert result.avg_hours_worked > 0
        assert result.total_tasks > 0
        assert result.best_day is not None
        assert result.worst_day is not None
        assert "Test AI response" in result.ai_insights

    @pytest.mark.asyncio
    async def test_analyze_empty_month(self, analyzer: AIAnalyzer) -> None:
        """Empty month should return zero stats."""
        result = await analyzer.analyze_month([], "2025-12")
        assert result.total_entries == 0
        assert result.avg_mood_score == 0


class TestAIAnalyzerBestDays:
    @pytest.mark.asyncio
    async def test_best_days_returns_top3(
        self, analyzer: AIAnalyzer, sample_entries: list[JournalEntry]
    ) -> None:
        best = await analyzer.best_days(sample_entries, top_n=3)
        assert len(best) == 3
        assert best[0].productivity_score >= best[1].productivity_score >= best[2].productivity_score

    @pytest.mark.asyncio
    async def test_best_days_empty(self, analyzer: AIAnalyzer) -> None:
        best = await analyzer.best_days([], top_n=3)
        assert best == []


class TestAIAnalyzerOtherCommands:
    @pytest.mark.asyncio
    async def test_optimal_hours(
        self, analyzer: AIAnalyzer, sample_entries: list[JournalEntry]
    ) -> None:
        result = await analyzer.optimal_hours(sample_entries)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_kate_impact(
        self, analyzer: AIAnalyzer, sample_entries: list[JournalEntry]
    ) -> None:
        result = await analyzer.kate_impact(sample_entries)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_testik_patterns(
        self, analyzer: AIAnalyzer, sample_entries: list[JournalEntry]
    ) -> None:
        result = await analyzer.testik_patterns(sample_entries)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_sleep_optimizer(
        self, analyzer: AIAnalyzer, sample_entries: list[JournalEntry]
    ) -> None:
        result = await analyzer.sleep_optimizer(sample_entries)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_money_forecast(
        self, analyzer: AIAnalyzer, sample_entries: list[JournalEntry]
    ) -> None:
        result = await analyzer.money_forecast(sample_entries)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_weak_spots(
        self, analyzer: AIAnalyzer, sample_entries: list[JournalEntry]
    ) -> None:
        result = await analyzer.weak_spots(sample_entries)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_tomorrow_mood(
        self, analyzer: AIAnalyzer, sample_entries: list[JournalEntry]
    ) -> None:
        result = await analyzer.tomorrow_mood(sample_entries)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_empty_data_handling(self, analyzer: AIAnalyzer) -> None:
        """All commands handle empty data gracefully."""
        assert "Нет данных" in await analyzer.optimal_hours([])
        assert "Нет данных" in await analyzer.kate_impact([])
        assert "Нет данных" in await analyzer.testik_patterns([])
        assert "Нет данных" in await analyzer.sleep_optimizer([])
        assert "Нет данных" in await analyzer.money_forecast([])
        assert "Нет данных" in await analyzer.weak_spots([])
        assert "Нужно минимум" in await analyzer.tomorrow_mood([])
