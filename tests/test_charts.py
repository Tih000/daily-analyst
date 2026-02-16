"""Tests for chart generation — all chart types including Jarvis."""

from __future__ import annotations

import pytest

from src.models.journal_entry import (
    ActivityCorrelation, Anomaly, CorrelationMatrix, DailyRecord,
    LifeDimension, LifeScore, MetricDelta, MonthComparison,
)
from src.services.charts_service import ChartsService

PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def charts() -> ChartsService:
    return ChartsService()


class TestExistingCharts:
    def test_monthly(self, charts, sample_records):
        assert charts.monthly_overview(sample_records, "2026-02")[:8] == PNG

    def test_burnout(self, charts, sample_records):
        assert charts.burnout_chart(sample_records)[:8] == PNG

    def test_testik(self, charts, sample_records):
        assert charts.testik_chart(sample_records)[:8] == PNG

    def test_sleep(self, charts, sample_records):
        assert charts.sleep_chart(sample_records)[:8] == PNG

    def test_activity(self, charts, sample_records):
        assert charts.activity_chart(sample_records)[:8] == PNG


class TestPhase2Charts:
    def test_habit_heatmap(self, charts, sample_records):
        assert charts.habit_heatmap(sample_records, "gym")[:8] == PNG

    def test_correlation_chart(self, charts):
        corr = CorrelationMatrix(
            baseline_rating=3.5,
            correlations=[
                ActivityCorrelation(activity="GYM", avg_rating=4.5, count=10, vs_baseline=1.0),
                ActivityCorrelation(activity="CODING", avg_rating=3.0, count=8, vs_baseline=-0.5),
            ],
        )
        assert charts.correlation_chart(corr)[:8] == PNG

    def test_report_card(self, charts, sample_records):
        assert charts.report_card(sample_records, "2026-02")[:8] == PNG

    def test_compare_chart(self, charts):
        comp = MonthComparison(
            month_a="2026-01", month_b="2026-02",
            deltas=[
                MetricDelta(name="Rating", emoji="⭐", value_a=3.5, value_b=4.2),
                MetricDelta(name="Sleep", emoji="😴", value_a=7.1, value_b=6.4),
            ],
        )
        assert charts.compare_chart(comp)[:8] == PNG


class TestJarvisCharts:
    def test_dashboard(self, charts):
        life = LifeScore(
            total=72, trend_delta=5.0,
            dimensions=[
                LifeDimension(name="Продуктивность", emoji="🧠", score=82, trend="↑"),
                LifeDimension(name="Сон", emoji="😴", score=65, trend="↓"),
                LifeDimension(name="Физ. форма", emoji="🏋️", score=90, trend="↑"),
                LifeDimension(name="Отношения", emoji="💕", score=72, trend="→"),
                LifeDimension(name="TESTIK", emoji="🧪", score=100, trend="↑"),
                LifeDimension(name="Настроение", emoji="😊", score=74, trend="→"),
            ],
        )
        result = charts.dashboard_chart(life)
        assert result[:8] == PNG
        assert len(result) > 1000

    def test_dashboard_empty(self, charts):
        life = LifeScore(total=0, dimensions=[])
        result = charts.dashboard_chart(life)
        assert isinstance(result, bytes)

    def test_anomaly_chart(self, charts, sample_records):
        from datetime import date, timedelta
        anomalies = [
            Anomaly(entry_date=sample_records[0].entry_date, score=90, avg_score=60,
                    direction="high", activities=["GYM", "CODING"]),
            Anomaly(entry_date=sample_records[-1].entry_date, score=20, avg_score=60,
                    direction="low", activities=[]),
        ]
        result = charts.anomaly_chart(sample_records, anomalies)
        assert result[:8] == PNG

    def test_anomaly_empty(self, charts):
        result = charts.anomaly_chart([], [])
        assert isinstance(result, bytes)


class TestEmpty:
    def test_monthly_empty(self, charts):
        assert isinstance(charts.monthly_overview([], "X"), bytes)

    def test_habit_empty(self, charts):
        assert isinstance(charts.habit_heatmap([], "gym"), bytes)
