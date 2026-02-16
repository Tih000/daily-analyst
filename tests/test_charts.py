"""Tests for chart generation — all chart types."""

from __future__ import annotations

import pytest

from src.models.journal_entry import (
    ActivityCorrelation,
    CorrelationMatrix,
    DailyRecord,
    MetricDelta,
    MonthComparison,
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


class TestNewCharts:
    def test_habit_heatmap(self, charts, sample_records):
        result = charts.habit_heatmap(sample_records, "gym")
        assert result[:8] == PNG

    def test_habit_sleep7(self, charts, sample_records):
        result = charts.habit_heatmap(sample_records, "sleep7")
        assert result[:8] == PNG

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
        result = charts.report_card(sample_records, "2026-02")
        assert result[:8] == PNG
        assert len(result) > 1000

    def test_compare_chart(self, charts):
        comp = MonthComparison(
            month_a="2026-01", month_b="2026-02",
            deltas=[
                MetricDelta(name="Rating", emoji="⭐", value_a=3.5, value_b=4.2),
                MetricDelta(name="Sleep", emoji="😴", value_a=7.1, value_b=6.4),
            ],
        )
        assert charts.compare_chart(comp)[:8] == PNG


class TestEmpty:
    def test_monthly_empty(self, charts):
        assert isinstance(charts.monthly_overview([], "X"), bytes)

    def test_habit_empty(self, charts):
        assert isinstance(charts.habit_heatmap([], "gym"), bytes)
