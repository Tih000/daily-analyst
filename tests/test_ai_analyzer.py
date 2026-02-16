"""Tests for AI analyzer (with mocked GPT calls)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.journal_entry import DailyRecord
from src.services.ai_analyzer import AIAnalyzer


@pytest.fixture
def analyzer() -> AIAnalyzer:
    with patch("src.services.ai_analyzer.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            openai=MagicMock(api_key="sk-test", model="gpt-4o-mini"),
        )
        a = AIAnalyzer()
    a._ask_gpt = AsyncMock(return_value="Test AI response with insights.")
    return a


class TestBurnout:
    @pytest.mark.asyncio
    async def test_high_risk(self, analyzer: AIAnalyzer, burnout_records: list[DailyRecord]) -> None:
        risk = await analyzer.predict_burnout(burnout_records)
        assert risk.risk_level in ("high", "critical")
        assert risk.risk_score >= 45
        assert len(risk.factors) > 0

    @pytest.mark.asyncio
    async def test_lower_risk(self, analyzer: AIAnalyzer, sample_records: list[DailyRecord]) -> None:
        risk = await analyzer.predict_burnout(sample_records)
        assert risk.risk_score < 80

    @pytest.mark.asyncio
    async def test_insufficient_data(self, analyzer: AIAnalyzer) -> None:
        risk = await analyzer.predict_burnout([])
        assert risk.risk_level == "unknown"


class TestMonthAnalysis:
    @pytest.mark.asyncio
    async def test_analyze(self, analyzer: AIAnalyzer, sample_records: list[DailyRecord]) -> None:
        result = await analyzer.analyze_month(sample_records, "2026-02")
        assert result.total_days == len(sample_records)
        assert result.avg_rating_score > 0
        assert result.avg_hours > 0
        assert result.best_day is not None
        assert result.worst_day is not None
        assert "Test AI response" in result.ai_insights

    @pytest.mark.asyncio
    async def test_empty(self, analyzer: AIAnalyzer) -> None:
        result = await analyzer.analyze_month([], "2026-12")
        assert result.total_days == 0


class TestBestDays:
    @pytest.mark.asyncio
    async def test_top3(self, analyzer: AIAnalyzer, sample_records: list[DailyRecord]) -> None:
        best = await analyzer.best_days(sample_records, 3)
        assert len(best) == 3
        assert best[0].productivity_score >= best[1].productivity_score >= best[2].productivity_score

    @pytest.mark.asyncio
    async def test_empty(self, analyzer: AIAnalyzer) -> None:
        assert await analyzer.best_days([], 3) == []


class TestOtherCommands:
    @pytest.mark.asyncio
    async def test_optimal_hours(self, analyzer: AIAnalyzer, sample_records: list[DailyRecord]) -> None:
        assert isinstance(await analyzer.optimal_hours(sample_records), str)

    @pytest.mark.asyncio
    async def test_kate_impact(self, analyzer: AIAnalyzer, sample_records: list[DailyRecord]) -> None:
        assert isinstance(await analyzer.kate_impact(sample_records), str)

    @pytest.mark.asyncio
    async def test_testik_patterns(self, analyzer: AIAnalyzer, sample_records: list[DailyRecord]) -> None:
        assert isinstance(await analyzer.testik_patterns(sample_records), str)

    @pytest.mark.asyncio
    async def test_sleep_optimizer(self, analyzer: AIAnalyzer, sample_records: list[DailyRecord]) -> None:
        assert isinstance(await analyzer.sleep_optimizer(sample_records), str)

    @pytest.mark.asyncio
    async def test_money_forecast(self, analyzer: AIAnalyzer, sample_records: list[DailyRecord]) -> None:
        assert isinstance(await analyzer.money_forecast(sample_records), str)

    @pytest.mark.asyncio
    async def test_weak_spots(self, analyzer: AIAnalyzer, sample_records: list[DailyRecord]) -> None:
        assert isinstance(await analyzer.weak_spots(sample_records), str)

    @pytest.mark.asyncio
    async def test_tomorrow_mood(self, analyzer: AIAnalyzer, sample_records: list[DailyRecord]) -> None:
        assert isinstance(await analyzer.tomorrow_mood(sample_records), str)

    @pytest.mark.asyncio
    async def test_empty_handlers(self, analyzer: AIAnalyzer) -> None:
        assert "Нет данных" in await analyzer.optimal_hours([])
        assert "Нет данных" in await analyzer.kate_impact([])
        assert "Нет данных" in await analyzer.testik_patterns([])
        assert "Нет данных" in await analyzer.sleep_optimizer([])
        assert "Нет данных" in await analyzer.money_forecast([])
        assert "Нет данных" in await analyzer.weak_spots([])
        assert "Нужно минимум" in await analyzer.tomorrow_mood([])
