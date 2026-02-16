"""Tests for Notion service parsing (with mocked API)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.journal_entry import DayRating, TestikStatus
from src.services.notion_service import (
    NotionService,
    _get_checkbox,
    _get_date,
    _get_multi_select,
    _get_number,
    _get_rich_text,
    _get_title,
)


class TestPropertyHelpers:
    def test_get_title(self) -> None:
        props = {"Name": {"type": "title", "title": [{"plain_text": "MARK"}]}}
        assert _get_title(props) == "MARK"

    def test_get_title_empty(self) -> None:
        assert _get_title({}) == ""

    def test_get_date_valid(self) -> None:
        props = {"Date": {"date": {"start": "2026-02-15T10:00:00Z"}}}
        assert _get_date(props, "Date") == "2026-02-15"

    def test_get_date_missing(self) -> None:
        assert _get_date({}, "Date") is None

    def test_get_number(self) -> None:
        assert _get_number({"H": {"number": 3.5}}, "H") == 3.5
        assert _get_number({"H": {"number": None}}, "H") == 0.0
        assert _get_number({}, "H") == 0.0

    def test_get_checkbox(self) -> None:
        assert _get_checkbox({"C": {"checkbox": True}}, "C") is True
        assert _get_checkbox({}, "C") is False

    def test_get_multi_select(self) -> None:
        props = {"Tags": {"multi_select": [{"name": "GYM"}, {"name": "CODING"}]}}
        assert _get_multi_select(props, "Tags") == ["GYM", "CODING"]

    def test_get_multi_select_empty(self) -> None:
        assert _get_multi_select({}, "Tags") == []


class TestNotionServiceParsing:
    def test_parse_page(self) -> None:
        page = {
            "id": "p1",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "MARK"}]},
                "Date": {"date": {"start": "2026-02-15"}},
                "Tags": {"multi_select": [{"name": "MARK"}]},
                "Checkbox": {"checkbox": True},
                "It took (hours)": {"number": None},
            },
        }
        task = NotionService._parse_page(page)
        assert task is not None
        assert task.id == "p1"
        assert task.title == "MARK"
        assert task.entry_date == date(2026, 2, 15)
        assert task.checkbox is True

    def test_parse_page_with_hours(self) -> None:
        page = {
            "id": "p2",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "GYM"}]},
                "Date": {"date": {"start": "2026-02-15"}},
                "Tags": {"multi_select": [{"name": "GYM"}]},
                "Checkbox": {"checkbox": True},
                "It took (hours)": {"number": 1.5},
            },
        }
        task = NotionService._parse_page(page)
        assert task is not None
        assert task.title == "GYM"
        assert task.hours == 1.5

    def test_parse_no_date(self) -> None:
        page = {"id": "no-date", "properties": {"Date": {"date": None}}}
        assert NotionService._parse_page(page) is None

    def test_parse_bad_page(self) -> None:
        assert NotionService._parse_page({"id": "bad"}) is None


class TestAggregation:
    def test_aggregate_daily(self, sample_tasks) -> None:
        sample_tasks[0].body_text = (
            "Woke up at 12:30. Sleep time 8:54. Recovery 81\n"
            "MINUS TESTIK KATE\n"
            "MARK: good"
        )

        records = NotionService._aggregate_daily(sample_tasks)
        assert len(records) == 1

        r = records[0]
        assert r.entry_date == date(2026, 2, 15)
        assert r.rating == DayRating.GOOD
        assert r.testik == TestikStatus.MINUS_KATE
        assert r.sleep.sleep_hours == pytest.approx(8.9, abs=0.01)
        assert r.sleep.recovery == 81
        assert r.total_hours == 4.5
        assert r.tasks_count == 3
        assert r.had_workout is True
        assert r.had_coding is True

    def test_aggregate_no_mark(self) -> None:
        from src.models.journal_entry import TaskEntry
        tasks = [
            TaskEntry(id="t1", title="CODING", entry_date=date(2026, 2, 20), tags=["CODING"], hours=4),
            TaskEntry(id="t2", title="GYM", entry_date=date(2026, 2, 20), tags=["GYM"], hours=1),
        ]
        records = NotionService._aggregate_daily(tasks)
        assert len(records) == 1
        r = records[0]
        assert r.rating is None
        assert r.testik is None
        assert r.total_hours == 5.0
        assert r.had_workout is True
        assert r.had_coding is True
