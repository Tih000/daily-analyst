"""Input validation and text parsing helpers."""

from __future__ import annotations

import re
from datetime import date
from typing import Optional, Tuple

from src.models.journal_entry import DayRating, SleepInfo, TestikStatus


# ── Parsing MARK entry body text ────────────────────────────────────────────


def parse_sleep_info(text: str) -> SleepInfo:
    """
    Extract sleep data from MARK entry body.

    Looks for patterns like:
        "Woke up at 12:30"
        "Sleep time 8:54"
        "Recovery 81 by Apple Watch"
    """
    woke_up_at: Optional[str] = None
    sleep_duration: Optional[str] = None
    sleep_hours: Optional[float] = None
    recovery: Optional[int] = None

    # "Woke up at 12:30" or "woke up at 8:00"
    woke_match = re.search(r"[Ww]oke\s+up\s+at\s+(\d{1,2}[:.]\d{2})", text)
    if woke_match:
        woke_up_at = woke_match.group(1).replace(".", ":")

    # "Sleep time 8:54" or "sleep time 7:30"
    sleep_match = re.search(r"[Ss]leep\s+time\s+(\d{1,2})[:.:](\d{2})", text)
    if sleep_match:
        hours_part = int(sleep_match.group(1))
        mins_part = int(sleep_match.group(2))
        sleep_duration = f"{hours_part}:{mins_part:02d}"
        sleep_hours = round(hours_part + mins_part / 60, 2)

    # "Recovery 81" or "recovery 75 by Apple Watch"
    recovery_match = re.search(r"[Rr]ecovery\s+(\d{1,3})", text)
    if recovery_match:
        recovery = int(recovery_match.group(1))

    return SleepInfo(
        woke_up_at=woke_up_at,
        sleep_duration=sleep_duration,
        sleep_hours=sleep_hours,
        recovery=recovery,
    )


def parse_testik(text: str) -> Optional[TestikStatus]:
    """
    Extract TESTIK status from MARK entry body.

    Patterns (case-insensitive):
        "MINUS TESTIK KATE"  → MINUS_KATE
        "MINUS TESTIK"       → MINUS (solo)
        "PLUS TESTIK"        → PLUS
    """
    text_upper = text.upper()

    if "MINUS TESTIK KATE" in text_upper or "MINUS TEST KATE" in text_upper:
        return TestikStatus.MINUS_KATE
    if "MINUS TESTIK" in text_upper or "MINUS TEST" in text_upper:
        return TestikStatus.MINUS
    if "PLUS TESTIK" in text_upper or "PLUS TEST" in text_upper:
        return TestikStatus.PLUS

    return None


def parse_day_rating(text: str) -> Optional[DayRating]:
    """
    Extract daily rating from MARK entry body.

    Looks for "MARK: good" / "MARK: very bad" etc. at the end of the text.
    """
    # Match "MARK: <rating>" (case-insensitive)
    match = re.search(r"MARK\s*:\s*(very\s+good|very\s+bad|perfect|good|normal|bad)", text, re.IGNORECASE)
    if match:
        raw = match.group(1).strip().lower()
        # Normalize whitespace
        raw = re.sub(r"\s+", " ", raw)
        try:
            return DayRating(raw)
        except ValueError:
            pass
    return None


# ── Month argument parsing ──────────────────────────────────────────────────


def parse_month_arg(text: str) -> Tuple[int, int]:
    """
    Parse month from user input.

    Accepts: "2025-01", "january", "январь", "01", "1", empty (current month).
    Returns (year, month). Raises ValueError if unparseable.
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

    # English month names
    en_months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "jun": 6, "jul": 7, "aug": 8, "sep": 9,
        "oct": 10, "nov": 11, "dec": 12,
    }
    if text in en_months:
        return date.today().year, en_months[text]

    # Russian month names
    ru_months = {
        "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
        "май": 5, "июнь": 6, "июль": 7, "август": 8,
        "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
    }
    if text in ru_months:
        return date.today().year, ru_months[text]

    raise ValueError(f"Не могу распознать месяц: '{text}'")


def _validate_month(month: int) -> None:
    if not 1 <= month <= 12:
        raise ValueError(f"Месяц должен быть 1-12, получено {month}")


# ── Compare command parsing ──────────────────────────────────────────────────


def parse_compare_args(text: str) -> tuple[tuple[int, int], tuple[int, int]]:
    """Parse '/compare jan feb' or '/compare 2025-01 2025-02'. Returns two (year, month)."""
    parts = text.strip().split()
    if len(parts) < 2:
        raise ValueError("Нужно два месяца: /compare январь февраль")
    return parse_month_arg(parts[0]), parse_month_arg(parts[1])


# ── Goal command parsing ────────────────────────────────────────────────────


def parse_goal_arg(text: str) -> tuple[str, int, str]:
    """
    Parse '/set_goal gym 4/week'.

    Returns (activity, target_count, period).
    """
    parts = text.strip().split()
    if len(parts) < 2:
        raise ValueError("Формат: /set_goal <activity> <count>/<period>\nПример: /set_goal gym 4/week")

    activity = parts[0].upper()
    target_str = parts[1]

    if "/" in target_str:
        count_str, period = target_str.split("/", 1)
        try:
            count = int(count_str)
        except ValueError:
            raise ValueError(f"Не могу распознать число: '{count_str}'")
        if period not in ("week", "month"):
            raise ValueError("Период должен быть 'week' или 'month'")
    else:
        try:
            count = int(target_str)
        except ValueError:
            raise ValueError(f"Не могу распознать число: '{target_str}'")
        period = "week"

    return activity, count, period


# ── Utility helpers ─────────────────────────────────────────────────────────


def sanitize_command_arg(text: str) -> str:
    """Remove the /command part and return the argument."""
    parts = text.strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def validate_user_id(user_id: int, allowed_ids: frozenset[int] | set[int] | list[int]) -> bool:
    """Check if user is authorized. Empty collection = allow all."""
    if not allowed_ids:
        return True
    return user_id in allowed_ids


def format_number(value: float, decimals: int = 1) -> str:
    """Format number: 1234.5 → '1,234.5'."""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.{decimals}f}"


def format_percentage(value: float) -> str:
    """Format as percentage: 0.756 → '75.6%'."""
    return f"{value * 100:.1f}%"


def truncate_text(text: str, max_length: int = 4000) -> str:
    """Truncate for Telegram message limit."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
