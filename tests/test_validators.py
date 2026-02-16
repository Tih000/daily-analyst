"""Tests for input validators and formatters."""

from datetime import date

import pytest

from src.utils.validators import (
    format_number,
    format_percentage,
    parse_month_arg,
    sanitize_command_arg,
    truncate_text,
    validate_user_id,
)


class TestParseMonthArg:
    def test_empty_returns_current(self) -> None:
        year, month = parse_month_arg("")
        today = date.today()
        assert year == today.year
        assert month == today.month

    def test_iso_format(self) -> None:
        assert parse_month_arg("2025-01") == (2025, 1)
        assert parse_month_arg("2025/12") == (2025, 12)

    def test_bare_number(self) -> None:
        assert parse_month_arg("3") == (date.today().year, 3)
        assert parse_month_arg("12") == (date.today().year, 12)

    def test_english_name(self) -> None:
        assert parse_month_arg("january")[1] == 1
        assert parse_month_arg("dec")[1] == 12

    def test_russian_name(self) -> None:
        assert parse_month_arg("январь")[1] == 1
        assert parse_month_arg("декабрь")[1] == 12

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_month_arg("not-a-month")

    def test_invalid_month_number(self) -> None:
        with pytest.raises(ValueError):
            parse_month_arg("13")


class TestSanitizeCommandArg:
    def test_with_arg(self) -> None:
        assert sanitize_command_arg("/analyze 2025-01") == "2025-01"

    def test_no_arg(self) -> None:
        assert sanitize_command_arg("/analyze") == ""

    def test_multiple_args(self) -> None:
        assert sanitize_command_arg("/cmd arg1 arg2") == "arg1 arg2"


class TestValidateUserId:
    def test_empty_allows_all(self) -> None:
        assert validate_user_id(123, []) is True

    def test_in_list(self) -> None:
        assert validate_user_id(123, [123, 456]) is True

    def test_not_in_list(self) -> None:
        assert validate_user_id(789, [123, 456]) is False


class TestFormatters:
    def test_format_number(self) -> None:
        assert format_number(1234.5) == "1,234.5"
        assert format_number(1000.0) == "1,000"

    def test_format_percentage(self) -> None:
        assert format_percentage(0.756) == "75.6%"
        assert format_percentage(1.0) == "100.0%"

    def test_truncate_text(self) -> None:
        short = "Hello"
        assert truncate_text(short) == short

        long = "x" * 5000
        result = truncate_text(long, max_length=100)
        assert len(result) == 100
        assert result.endswith("...")
