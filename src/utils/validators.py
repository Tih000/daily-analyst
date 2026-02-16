"""Input validation helpers for Telegram commands."""

from __future__ import annotations

import re
from datetime import date
from typing import Tuple


def parse_month_arg(text: str) -> Tuple[int, int]:
    """
    Parse month argument from user input.

    Accepts: "2025-01", "january", "01", "1", empty (current month).
    Returns (year, month).

    Raises ValueError if unparseable.
    """
    text = text.strip().lower()

    if not text:
        today = date.today()
        return today.year, today.month

    # "2025-01" or "2025/01"
    iso_match = re.match(r"^(\d{4})[-/](\d{1,2})$", text)
    if iso_match:
        year, month = int(iso_match.group(1)), int(iso_match.group(2))
        _validate_month(month)
        return year, month

    # Bare number "1" .. "12"
    if text.isdigit():
        month = int(text)
        _validate_month(month)
        return date.today().year, month

    # English month name
    month_names = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "jun": 6, "jul": 7, "aug": 8, "sep": 9,
        "oct": 10, "nov": 11, "dec": 12,
    }
    if text in month_names:
        return date.today().year, month_names[text]

    # Russian month names
    ru_months = {
        "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
        "май": 5, "июнь": 6, "июль": 7, "август": 8,
        "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
    }
    if text in ru_months:
        return date.today().year, ru_months[text]

    raise ValueError(f"Cannot parse month from: '{text}'")


def _validate_month(month: int) -> None:
    if not 1 <= month <= 12:
        raise ValueError(f"Month must be 1-12, got {month}")


def sanitize_command_arg(text: str) -> str:
    """Remove the /command part and return the argument."""
    parts = text.strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def validate_user_id(user_id: int, allowed_ids: frozenset[int] | list[int]) -> bool:
    """Check if user is authorized. Empty collection = allow all."""
    if not allowed_ids:
        return True
    return user_id in allowed_ids


def format_number(value: float, decimals: int = 1) -> str:
    """Format number nicely: 1234.5 → '1,234.5'."""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.{decimals}f}"


def format_percentage(value: float) -> str:
    """Format as percentage: 0.756 → '75.6%'."""
    return f"{value * 100:.1f}%"


def truncate_text(text: str, max_length: int = 4000) -> str:
    """Truncate text for Telegram message limit."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
