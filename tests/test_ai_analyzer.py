"""Tests for AI analyzer — all methods including new features."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.journal_entry import DailyRecord, Goal
from src.services.ai_analyzer import AIAnalyzer


@pytest.fixture
def analyzer() -> AIAnalyzer:
    with patch("src.services.ai_analyzer.get_settings") as m:
        m.return_value = MagicMock(openai=MagicMock(api_key="sk-test", model="gpt-4o-mini"))
        a = AIAnalyzer()
    a._ask_gpt = AsyncMock(return_value="Test AI insights.")
    return a


class TestBurnout:
    @pytest.mark.asyncio
    async def test_high_risk(self, analyzer, burnout_records):
        r = await analyzer.predict_burnout(burnout_records)
        assert r.risk_level in ("high", "critical")
        assert r.risk_score >= 45

    @pytest.mark.asyncio
    async def test_empty(self, analyzer):
        r = await analyzer.predict_burnout([])
        assert r.risk_level == "unknown"


class TestMonth:
    @pytest.mark.asyncio
    async def test_analyze(self, analyzer, sample_records):
        r = await analyzer.analyze_month(sample_records, "2026-02")
        assert r.total_days == len(sample_records)
        assert r.best_day is not None

    @pytest.mark.asyncio
    async def test_empty(self, analyzer):
        r = await analyzer.analyze_month([], "2026-12")
        assert r.total_days == 0


class TestBestDays:
    @pytest.mark.asyncio
    async def test_top3(self, analyzer, sample_records):
        best = await analyzer.best_days(sample_records, 3)
        assert len(best) == 3
        assert best[0].productivity_score >= best[2].productivity_score


class TestStreaks:
    def test_compute_streaks(self, analyzer, sample_records):
        streaks = analyzer.compute_streaks(sample_records)
        assert len(streaks) >= 4
        names = [s.name for s in streaks]
        assert "TESTIK PLUS" in names
        assert "GYM" in names

    def test_streaks_empty(self, analyzer):
        assert analyzer.compute_streaks([]) == []


class TestCompare:
    @pytest.mark.asyncio
    async def test_compare(self, analyzer, sample_records):
        mid = len(sample_records) // 2
        a, b = sample_records[:mid], sample_records[mid:]
        comp = await analyzer.compare_months(a, b, "2026-01", "2026-02")
        assert len(comp.deltas) >= 4
        assert comp.month_a == "2026-01"


class TestCorrelations:
    @pytest.mark.asyncio
    async def test_correlations(self, analyzer, sample_records):
        corr = await analyzer.compute_correlations(sample_records)
        assert corr.baseline_rating > 0
        assert len(corr.correlations) > 0


class TestDayTypes:
    @pytest.mark.asyncio
    async def test_classify(self, analyzer, sample_records):
        result = await analyzer.classify_day_types(sample_records)
        assert isinstance(result, str)
        assert len(result) > 0


class TestAlerts:
    def test_burnout_alerts(self, analyzer, burnout_records):
        alerts = analyzer.check_alerts(burnout_records)
        assert len(alerts) > 0

    def test_no_alerts(self, analyzer, sample_records):
        alerts = analyzer.check_alerts(sample_records)
        assert isinstance(alerts, list)


class TestGoalProgress:
    def test_progress(self, analyzer, sample_records, sample_goals):
        progress = analyzer.compute_goal_progress(sample_goals, sample_records)
        assert len(progress) == 3
        for p in progress:
            assert 0 <= p.percentage <= 100


class TestEmptyHandlers:
    @pytest.mark.asyncio
    async def test_all(self, analyzer):
        assert "Нет данных" in await analyzer.optimal_hours([])
        assert "Нет данных" in await analyzer.kate_impact([])
        assert "Нет данных" in await analyzer.testik_patterns([])
        assert "Нет данных" in await analyzer.weak_spots([])
