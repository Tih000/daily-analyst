"""Tests for validators and text parsers."""

from datetime import date

import pytest

from src.models.journal_entry import DayRating, TestikStatus
from src.utils.validators import (
    format_number, format_percentage, parse_compare_args, parse_day_rating,
    parse_goal_arg, parse_month_arg, parse_sleep_info, parse_testik,
    sanitize_command_arg, truncate_text, validate_user_id,
)


class TestSleep:
    def test_full(self):
        i = parse_sleep_info("Woke up at 12:30. Sleep time 8:54. Recovery 81 by Apple Watch")
        assert i.woke_up_at == "12:30"
        assert i.sleep_hours == pytest.approx(8.9, abs=0.01)
        assert i.recovery == 81

    def test_partial(self):
        assert parse_sleep_info("Sleep time 7:30").sleep_hours == 7.5

    def test_empty(self):
        assert parse_sleep_info("nothing").sleep_hours is None


class TestTestik:
    def test_minus_kate(self):
        assert parse_testik("MINUS TESTIK KATE") == TestikStatus.MINUS_KATE

    def test_minus(self):
        assert parse_testik("MINUS TESTIK") == TestikStatus.MINUS

    def test_plus(self):
        assert parse_testik("PLUS TESTIK") == TestikStatus.PLUS

    def test_none(self):
        assert parse_testik("normal day") is None

    def test_priority(self):
        assert parse_testik("MINUS TESTIK KATE here") == TestikStatus.MINUS_KATE


class TestRating:
    def test_all(self):
        for val in ["perfect", "very good", "good", "normal", "bad", "very bad"]:
            assert parse_day_rating(f"MARK: {val}") is not None

    def test_none(self):
        assert parse_day_rating("no rating") is None


class TestMonth:
    def test_empty(self):
        y, m = parse_month_arg("")
        assert y == date.today().year

    def test_iso(self):
        assert parse_month_arg("2025-01") == (2025, 1)

    def test_russian(self):
        assert parse_month_arg("январь")[1] == 1

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_month_arg("xxx")


class TestCompareArgs:
    def test_two_months(self):
        (y1, m1), (y2, m2) = parse_compare_args("january february")
        assert m1 == 1 and m2 == 2

    def test_too_few(self):
        with pytest.raises(ValueError):
            parse_compare_args("january")


class TestGoalArg:
    def test_with_period(self):
        act, count, period = parse_goal_arg("gym 4/week")
        assert act == "GYM"
        assert count == 4
        assert period == "week"

    def test_default_week(self):
        act, count, period = parse_goal_arg("coding 5")
        assert act == "CODING"
        assert count == 5
        assert period == "week"

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_goal_arg("")


class TestHelpers:
    def test_sanitize(self):
        assert sanitize_command_arg("/cmd arg") == "arg"

    def test_user_id(self):
        assert validate_user_id(1, []) is True
        assert validate_user_id(1, [1]) is True
        assert validate_user_id(1, [2]) is False

    def test_format(self):
        assert format_number(1000.0) == "1,000"
        assert format_percentage(0.5) == "50.0%"

    def test_truncate(self):
        assert len(truncate_text("x" * 5000, 100)) == 100
