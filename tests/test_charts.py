"""Tests for chart generation service."""

from __future__ import annotations

import pytest

from src.models.journal_entry import DailyRecord
from src.services.charts_service import ChartsService


@pytest.fixture
def charts() -> ChartsService:
    return ChartsService()


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


class TestChartsService:
    def test_monthly_overview(self, charts: ChartsService, sample_records: list[DailyRecord]) -> None:
        result = charts.monthly_overview(sample_records, "2026-02")
        assert isinstance(result, bytes)
        assert result[:8] == PNG_HEADER
        assert len(result) > 1000

    def test_monthly_empty(self, charts: ChartsService) -> None:
        result = charts.monthly_overview([], "2026-02")
        assert result[:8] == PNG_HEADER

    def test_burnout_chart(self, charts: ChartsService, sample_records: list[DailyRecord]) -> None:
        result = charts.burnout_chart(sample_records)
        assert result[:8] == PNG_HEADER

    def test_burnout_too_few(self, charts: ChartsService) -> None:
        assert isinstance(charts.burnout_chart([]), bytes)

    def test_testik_chart(self, charts: ChartsService, sample_records: list[DailyRecord]) -> None:
        result = charts.testik_chart(sample_records)
        assert result[:8] == PNG_HEADER

    def test_sleep_chart(self, charts: ChartsService, sample_records: list[DailyRecord]) -> None:
        result = charts.sleep_chart(sample_records)
        assert result[:8] == PNG_HEADER

    def test_activity_chart(self, charts: ChartsService, sample_records: list[DailyRecord]) -> None:
        result = charts.activity_chart(sample_records)
        assert result[:8] == PNG_HEADER

    def test_activity_empty(self, charts: ChartsService) -> None:
        result = charts.activity_chart([])
        assert isinstance(result, bytes)
