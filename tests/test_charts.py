"""Tests for chart generation service."""

from __future__ import annotations

import pytest

from src.models.journal_entry import JournalEntry
from src.services.charts_service import ChartsService


@pytest.fixture
def charts() -> ChartsService:
    return ChartsService()


class TestChartsService:
    def test_monthly_overview_returns_png(
        self, charts: ChartsService, sample_entries: list[JournalEntry]
    ) -> None:
        """Monthly chart returns valid PNG bytes."""
        result = charts.monthly_overview(sample_entries, "2025-01")
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic header
        assert len(result) > 1000  # Non-trivial image

    def test_monthly_overview_empty(self, charts: ChartsService) -> None:
        """Empty entries still produce a valid image."""
        result = charts.monthly_overview([], "2025-01")
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_burnout_chart(
        self, charts: ChartsService, sample_entries: list[JournalEntry]
    ) -> None:
        result = charts.burnout_chart(sample_entries)
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_burnout_chart_too_few(self, charts: ChartsService) -> None:
        """Less than 3 entries gives placeholder."""
        result = charts.burnout_chart([])
        assert isinstance(result, bytes)

    def test_testik_chart(
        self, charts: ChartsService, sample_entries: list[JournalEntry]
    ) -> None:
        result = charts.testik_chart(sample_entries)
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_sleep_chart(
        self, charts: ChartsService, sample_entries: list[JournalEntry]
    ) -> None:
        result = charts.sleep_chart(sample_entries)
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_earnings_chart(
        self, charts: ChartsService, sample_entries: list[JournalEntry]
    ) -> None:
        result = charts.earnings_chart(sample_entries)
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_earnings_chart_no_earnings(self, charts: ChartsService) -> None:
        """No earnings returns placeholder image."""
        result = charts.earnings_chart([])
        assert isinstance(result, bytes)
