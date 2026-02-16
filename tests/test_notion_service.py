"""Tests for Notion service (with mocked API calls)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.journal_entry import JournalEntry, Mood, Testik
from src.services.notion_service import NotionService, _get_checkbox, _get_date, _get_number, _get_rich_text, _get_select_enum


class TestNotionPropertyHelpers:
    """Test Notion API response parsing helpers."""

    def test_get_date_valid(self) -> None:
        props = {"Date": {"date": {"start": "2025-01-15T10:00:00.000Z"}}}
        assert _get_date(props, "Date") == "2025-01-15"

    def test_get_date_missing(self) -> None:
        assert _get_date({}, "Date") is None
        assert _get_date({"Date": {"date": None}}, "Date") is None

    def test_get_number(self) -> None:
        assert _get_number({"Hours": {"number": 7.5}}, "Hours") == 7.5
        assert _get_number({"Hours": {"number": None}}, "Hours") == 0.0
        assert _get_number({}, "Hours") == 0.0

    def test_get_checkbox(self) -> None:
        assert _get_checkbox({"W": {"checkbox": True}}, "W") is True
        assert _get_checkbox({"W": {"checkbox": False}}, "W") is False
        assert _get_checkbox({}, "W") is False

    def test_get_select_enum(self) -> None:
        props = {"Mood": {"select": {"name": "GOOD"}}}
        assert _get_select_enum(props, "Mood", Mood) == Mood.GOOD

    def test_get_select_enum_unknown(self) -> None:
        props = {"Mood": {"select": {"name": "UNKNOWN_VALUE"}}}
        assert _get_select_enum(props, "Mood", Mood) is None

    def test_get_select_enum_missing(self) -> None:
        assert _get_select_enum({}, "Mood", Mood) is None

    def test_get_rich_text(self) -> None:
        props = {"Notes": {"rich_text": [
            {"plain_text": "Hello "},
            {"plain_text": "world"},
        ]}}
        assert _get_rich_text(props, "Notes") == "Hello world"

    def test_get_rich_text_empty(self) -> None:
        assert _get_rich_text({}, "Notes") == ""


class TestNotionServiceParsing:
    """Test page parsing from Notion API responses."""

    def test_parse_valid_page(self, mock_notion_response: list[dict]) -> None:
        entry = NotionService._parse_page(mock_notion_response[0])
        assert entry is not None
        assert entry.id == "page-001"
        assert entry.entry_date == date(2025, 1, 15)
        assert entry.mood == Mood.GOOD
        assert entry.hours_worked == 7.5
        assert entry.tasks_completed == 5
        assert entry.testik == Testik.PLUS
        assert entry.workout is True
        assert entry.university is False
        assert entry.earnings_usd == 100
        assert entry.sleep_hours == 7.5
        assert entry.notes == "Great day!"

    def test_parse_page_no_date(self) -> None:
        page = {"id": "no-date", "properties": {"Date": {"date": None}}}
        assert NotionService._parse_page(page) is None

    def test_parse_bad_page(self) -> None:
        """Malformed page returns None, not exception."""
        assert NotionService._parse_page({"id": "bad"}) is None


class TestNotionServiceGetEntries:
    """Test the async get_entries method with mocked HTTP calls."""

    @pytest.mark.asyncio
    async def test_get_entries_from_cache(self, cache_service, sample_entries) -> None:
        """When cache is fresh, should return from cache."""
        cache_service.upsert_entries(sample_entries)
        cache_service.mark_synced()

        with patch("src.services.notion_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                notion=MagicMock(token="test", database_id="test-db"),
                app=MagicMock(cache_ttl_seconds=300),
            )
            service = NotionService(cache=cache_service)
            entries = await service.get_entries()
            assert len(entries) > 0

    @pytest.mark.asyncio
    async def test_get_entries_force_refresh(self, cache_service, mock_notion_response) -> None:
        """force_refresh should bypass cache and query Notion."""
        with patch("src.services.notion_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                notion=MagicMock(token="test", database_id="test-db"),
                app=MagicMock(cache_ttl_seconds=300),
            )
            service = NotionService(cache=cache_service)
            service._query_database = AsyncMock(return_value=mock_notion_response)

            entries = await service.get_entries(force_refresh=True)
            assert len(entries) == 2
            assert entries[0].id == "page-001"
            service._query_database.assert_called_once()
