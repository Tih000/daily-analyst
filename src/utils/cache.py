"""SQLite local cache for Notion journal entries."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Generator, Optional

from src.models.journal_entry import JournalEntry, Mood, Testik

logger = logging.getLogger(__name__)

DB_PATH = Path("data/cache.db")


@contextmanager
def _get_connection() -> Generator[sqlite3.Connection, None, None]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


class CacheService:
    """SQLite-backed cache for journal entries."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl_seconds = ttl_seconds
        self._init_db()

    def _init_db(self) -> None:
        with _get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal_entries (
                    id TEXT PRIMARY KEY,
                    entry_date TEXT NOT NULL,
                    mood TEXT,
                    hours_worked REAL DEFAULT 0,
                    tasks_completed INTEGER DEFAULT 0,
                    testik TEXT,
                    workout INTEGER DEFAULT 0,
                    university INTEGER DEFAULT 0,
                    earnings_usd REAL DEFAULT 0,
                    sleep_hours REAL DEFAULT 0,
                    notes TEXT DEFAULT '',
                    cached_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_entry_date ON journal_entries(entry_date)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def is_cache_fresh(self) -> bool:
        """Check if cache was updated within TTL."""
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT value, updated_at FROM cache_metadata WHERE key = 'last_sync'"
            ).fetchone()
            if not row:
                return False
            updated_at = datetime.fromisoformat(row["updated_at"])
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - updated_at).total_seconds() < self.ttl_seconds

    def mark_synced(self) -> None:
        """Mark cache as freshly synced."""
        now = datetime.now(timezone.utc).isoformat()
        with _get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO cache_metadata (key, value, updated_at)
                   VALUES ('last_sync', ?, ?)""",
                (now, now),
            )
            conn.commit()

    def upsert_entries(self, entries: list[JournalEntry]) -> int:
        """Insert or update multiple journal entries using batch insert. Returns count."""
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                entry.id,
                entry.entry_date.isoformat(),
                entry.mood.value if entry.mood else None,
                entry.hours_worked,
                entry.tasks_completed,
                entry.testik.value if entry.testik else None,
                int(entry.workout),
                int(entry.university),
                entry.earnings_usd,
                entry.sleep_hours,
                entry.notes,
                now,
            )
            for entry in entries
        ]
        with _get_connection() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO journal_entries
                   (id, entry_date, mood, hours_worked, tasks_completed,
                    testik, workout, university, earnings_usd, sleep_hours,
                    notes, cached_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()
        logger.info("Cached %d entries", len(entries))
        return len(entries)

    def get_entries(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[JournalEntry]:
        """Retrieve cached entries within a date range."""
        if start_date is None:
            start_date = date.today() - timedelta(days=90)
        if end_date is None:
            end_date = date.today()

        with _get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM journal_entries
                   WHERE entry_date BETWEEN ? AND ?
                   ORDER BY entry_date DESC""",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()

        return [self._row_to_entry(row) for row in rows]

    def get_entries_for_month(self, year: int, month: int) -> list[JournalEntry]:
        """Get all entries for a specific month."""
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        return self.get_entries(start, end)

    def get_recent(self, days: int = 30) -> list[JournalEntry]:
        """Get entries for last N days."""
        return self.get_entries(
            start_date=date.today() - timedelta(days=days),
            end_date=date.today(),
        )

    def cleanup_old(self, keep_days: int = 90) -> int:
        """Remove entries older than keep_days. Returns count removed."""
        cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
        with _get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM journal_entries WHERE entry_date < ?", (cutoff,)
            )
            conn.commit()
            removed = cursor.rowcount
        logger.info("Cleaned up %d old entries", removed)
        return removed

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> JournalEntry:
        return JournalEntry(
            id=row["id"],
            entry_date=date.fromisoformat(row["entry_date"]),
            mood=Mood(row["mood"]) if row["mood"] else None,
            hours_worked=row["hours_worked"],
            tasks_completed=row["tasks_completed"],
            testik=Testik(row["testik"]) if row["testik"] else None,
            workout=bool(row["workout"]),
            university=bool(row["university"]),
            earnings_usd=row["earnings_usd"],
            sleep_hours=row["sleep_hours"],
            notes=row["notes"] or "",
        )
