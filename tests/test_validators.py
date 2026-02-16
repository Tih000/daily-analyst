"""Tests for validators and text parsers."""

from datetime import date

import pytest

from src.models.journal_entry import DayRating, TestikStatus
from src.utils.validators import (
    format_number,
    format_percentage,
    parse_day_rating,
    parse_month_arg,
    parse_sleep_info,
    parse_testik,
    sanitize_command_arg,
    truncate_text,
    validate_user_id,
)


class TestParseSleepInfo:
    def test_full_parse(self) -> None:
        text = "Woke up at 12:30. Sleep time 8:54. Recovery 81 by Apple Watch"
        info = parse_sleep_info(text)
        assert info.woke_up_at == "12:30"
        assert info.sleep_duration == "8:54"
        assert info.sleep_hours == pytest.approx(8.9, abs=0.01)
        assert info.recovery == 81

    def test_partial_sleep(self) -> None:
        text = "Sleep time 7:30"
        info = parse_sleep_info(text)
        assert info.sleep_hours == 7.5
        assert info.woke_up_at is None

    def test_no_sleep_data(self) -> None:
        info = parse_sleep_info("Just a normal day")
        assert info.sleep_hours is None
        assert info.recovery is None

    def test_different_formats(self) -> None:
        info = parse_sleep_info("woke up at 8:00. sleep time 6:45. recovery 72")
        assert info.woke_up_at == "8:00"
        assert info.sleep_hours == pytest.approx(6.75, abs=0.01)
        assert info.recovery == 72


class TestParseTestik:
    def test_minus_kate(self) -> None:
        assert parse_testik("MINUS TESTIK KATE") == TestikStatus.MINUS_KATE

    def test_minus_solo(self) -> None:
        assert parse_testik("MINUS TESTIK") == TestikStatus.MINUS

    def test_plus(self) -> None:
        assert parse_testik("PLUS TESTIK") == TestikStatus.PLUS

    def test_case_insensitive(self) -> None:
        assert parse_testik("minus testik kate") == TestikStatus.MINUS_KATE

    def test_no_testik(self) -> None:
        assert parse_testik("Just a normal day") is None

    def test_minus_kate_priority(self) -> None:
        """MINUS TESTIK KATE should be detected even if MINUS TESTIK appears as substring."""
        assert parse_testik("Today: MINUS TESTIK KATE happened") == TestikStatus.MINUS_KATE

    def test_embedded_in_text(self) -> None:
        text = "Did some work\nMINUS TESTIK\nThen went to sleep"
        assert parse_testik(text) == TestikStatus.MINUS


class TestParseDayRating:
    def test_all_ratings(self) -> None:
        assert parse_day_rating("MARK: perfect") == DayRating.PERFECT
        assert parse_day_rating("MARK: very good") == DayRating.VERY_GOOD
        assert parse_day_rating("MARK: good") == DayRating.GOOD
        assert parse_day_rating("MARK: normal") == DayRating.NORMAL
        assert parse_day_rating("MARK: bad") == DayRating.BAD
        assert parse_day_rating("MARK: very bad") == DayRating.VERY_BAD

    def test_case_insensitive(self) -> None:
        assert parse_day_rating("MARK: Good") == DayRating.GOOD
        assert parse_day_rating("mark: PERFECT") == DayRating.PERFECT

    def test_no_rating(self) -> None:
        assert parse_day_rating("No rating here") is None

    def test_embedded(self) -> None:
        text = "Did stuff\nWent to gym\nMARK: good"
        assert parse_day_rating(text) == DayRating.GOOD


class TestParseMonthArg:
    def test_empty(self) -> None:
        y, m = parse_month_arg("")
        assert y == date.today().year
        assert m == date.today().month

    def test_iso(self) -> None:
        assert parse_month_arg("2025-01") == (2025, 1)
        assert parse_month_arg("2026/12") == (2026, 12)

    def test_number(self) -> None:
        assert parse_month_arg("3") == (date.today().year, 3)

    def test_english(self) -> None:
        assert parse_month_arg("january")[1] == 1
        assert parse_month_arg("dec")[1] == 12

    def test_russian(self) -> None:
        assert parse_month_arg("январь")[1] == 1
        assert parse_month_arg("декабрь")[1] == 12

    def test_invalid(self) -> None:
        with pytest.raises(ValueError):
            parse_month_arg("not-a-month")

    def test_invalid_number(self) -> None:
        with pytest.raises(ValueError):
            parse_month_arg("13")


class TestHelpers:
    def test_sanitize_command_arg(self) -> None:
        assert sanitize_command_arg("/analyze 2025-01") == "2025-01"
        assert sanitize_command_arg("/analyze") == ""

    def test_validate_user_id(self) -> None:
        assert validate_user_id(123, []) is True
        assert validate_user_id(123, [123, 456]) is True
        assert validate_user_id(789, [123, 456]) is False

    def test_format_number(self) -> None:
        assert format_number(1234.5) == "1,234.5"
        assert format_number(1000.0) == "1,000"

    def test_format_percentage(self) -> None:
        assert format_percentage(0.756) == "75.6%"

    def test_truncate_text(self) -> None:
        assert truncate_text("Hello") == "Hello"
        long = "x" * 5000
        assert len(truncate_text(long, 100)) == 100
        assert truncate_text(long, 100).endswith("...")
