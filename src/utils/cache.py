"""SQLite local cache for task entries, daily records, and goals."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Generator, Optional

from src.models.journal_entry import (
    DailyRecord,
    DayRating,
    Goal,
    SleepInfo,
    TaskEntry,
    TestikStatus,
)

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
    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl_seconds = ttl_seconds
        self._init_db()

    def _init_db(self) -> None:
        with _get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_entries (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    entry_date TEXT NOT NULL,
                    tags TEXT DEFAULT '[]',
                    checkbox INTEGER DEFAULT 0,
                    hours REAL,
                    body_text TEXT DEFAULT '',
                    cached_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_date ON task_entries(entry_date)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_records (
                    entry_date TEXT PRIMARY KEY,
                    rating TEXT,
                    testik TEXT,
                    sleep_json TEXT DEFAULT '{}',
                    activities TEXT DEFAULT '[]',
                    total_hours REAL DEFAULT 0,
                    tasks_count INTEGER DEFAULT 0,
                    tasks_completed INTEGER DEFAULT 0,
                    had_workout INTEGER DEFAULT 0,
                    had_university INTEGER DEFAULT 0,
                    had_coding INTEGER DEFAULT 0,
                    had_kate INTEGER DEFAULT 0,
                    journal_text TEXT DEFAULT '',
                    is_weekly_summary INTEGER DEFAULT 0,
                    cached_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS goals (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    target_activity TEXT NOT NULL,
                    target_count INTEGER NOT NULL,
                    period TEXT DEFAULT 'week',
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    # ── Cache freshness ─────────────────────────────────────────────────────

    def is_cache_fresh(self) -> bool:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT updated_at FROM cache_metadata WHERE key = 'last_sync'"
            ).fetchone()
            if not row:
                return False
            updated_at = datetime.fromisoformat(row["updated_at"])
            return (datetime.utcnow() - updated_at).total_seconds() < self.ttl_seconds

    def mark_synced(self) -> None:
        now = datetime.utcnow().isoformat()
        with _get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache_metadata (key, value, updated_at) VALUES ('last_sync', ?, ?)",
                (now, now),
            )
            conn.commit()

    # ── Task entries ────────────────────────────────────────────────────────

    def upsert_tasks(self, tasks: list[TaskEntry]) -> int:
        with _get_connection() as conn:
            for t in tasks:
                conn.execute(
                    """INSERT OR REPLACE INTO task_entries
                       (id, title, entry_date, tags, checkbox, hours, body_text, cached_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (t.id, t.title, t.entry_date.isoformat(), json.dumps(t.tags),
                     int(t.checkbox), t.hours, t.body_text, datetime.utcnow().isoformat()),
                )
            conn.commit()
        return len(tasks)

    def get_tasks(self, start_date: Optional[date] = None, end_date: Optional[date] = None) -> list[TaskEntry]:
        if start_date is None:
            start_date = date.today() - timedelta(days=90)
        if end_date is None:
            end_date = date.today()
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_entries WHERE entry_date BETWEEN ? AND ? ORDER BY entry_date DESC",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    # ── Daily records ───────────────────────────────────────────────────────

    def upsert_daily_records(self, records: list[DailyRecord]) -> int:
        with _get_connection() as conn:
            for r in records:
                conn.execute(
                    """INSERT OR REPLACE INTO daily_records
                       (entry_date, rating, testik, sleep_json, activities,
                        total_hours, tasks_count, tasks_completed,
                        had_workout, had_university, had_coding, had_kate,
                        journal_text, is_weekly_summary, cached_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (r.entry_date.isoformat(),
                     r.rating.value if r.rating else None,
                     r.testik.value if r.testik else None,
                     r.sleep.model_dump_json(),
                     json.dumps(r.activities),
                     r.total_hours, r.tasks_count, r.tasks_completed,
                     int(r.had_workout), int(r.had_university),
                     int(r.had_coding), int(r.had_kate),
                     r.journal_text, int(r.is_weekly_summary),
                     datetime.utcnow().isoformat()),
                )
            conn.commit()
        return len(records)

    def get_daily_records(
        self, start_date: Optional[date] = None, end_date: Optional[date] = None,
        exclude_weekly: bool = True,
    ) -> list[DailyRecord]:
        if start_date is None:
            start_date = date.today() - timedelta(days=90)
        if end_date is None:
            end_date = date.today()
        query = "SELECT * FROM daily_records WHERE entry_date BETWEEN ? AND ?"
        params: list = [start_date.isoformat(), end_date.isoformat()]
        if exclude_weekly:
            query += " AND is_weekly_summary = 0"
        query += " ORDER BY entry_date DESC"
        with _get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_daily(r) for r in rows]

    def get_daily_for_month(self, year: int, month: int) -> list[DailyRecord]:
        start = date(year, month, 1)
        end = date(year + (1 if month == 12 else 0), (month % 12) + 1, 1) - timedelta(days=1)
        return self.get_daily_records(start, end)

    def get_recent_daily(self, days: int = 30) -> list[DailyRecord]:
        return self.get_daily_records(date.today() - timedelta(days=days), date.today())

    # ── Goals ───────────────────────────────────────────────────────────────

    def upsert_goal(self, goal: Goal) -> None:
        with _get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO goals (id, user_id, name, target_activity, target_count, period, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (goal.id, goal.user_id, goal.name, goal.target_activity,
                 goal.target_count, goal.period, goal.created_at.isoformat()),
            )
            conn.commit()

    def get_goals(self, user_id: int) -> list[Goal]:
        with _get_connection() as conn:
            rows = conn.execute("SELECT * FROM goals WHERE user_id = ?", (user_id,)).fetchall()
        return [
            Goal(
                id=r["id"], user_id=r["user_id"], name=r["name"],
                target_activity=r["target_activity"], target_count=r["target_count"],
                period=r["period"], created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def delete_goal(self, goal_id: str) -> bool:
        with _get_connection() as conn:
            cursor = conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def cleanup_old(self, keep_days: int = 180) -> int:
        cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
        with _get_connection() as conn:
            c1 = conn.execute("DELETE FROM task_entries WHERE entry_date < ?", (cutoff,)).rowcount
            c2 = conn.execute("DELETE FROM daily_records WHERE entry_date < ?", (cutoff,)).rowcount
            conn.commit()
        return c1 + c2

    # ── Row converters ──────────────────────────────────────────────────────

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskEntry:
        return TaskEntry(
            id=row["id"], title=row["title"],
            entry_date=date.fromisoformat(row["entry_date"]),
            tags=json.loads(row["tags"]), checkbox=bool(row["checkbox"]),
            hours=row["hours"], body_text=row["body_text"] or "",
        )

    @staticmethod
    def _row_to_daily(row: sqlite3.Row) -> DailyRecord:
        sleep_data = json.loads(row["sleep_json"]) if row["sleep_json"] else {}
        return DailyRecord(
            entry_date=date.fromisoformat(row["entry_date"]),
            rating=DayRating(row["rating"]) if row["rating"] else None,
            testik=TestikStatus(row["testik"]) if row["testik"] else None,
            sleep=SleepInfo(**sleep_data),
            activities=json.loads(row["activities"]),
            total_hours=row["total_hours"], tasks_count=row["tasks_count"],
            tasks_completed=row["tasks_completed"],
            had_workout=bool(row["had_workout"]), had_university=bool(row["had_university"]),
            had_coding=bool(row["had_coding"]), had_kate=bool(row["had_kate"]),
            journal_text=row["journal_text"] or "",
            is_weekly_summary=bool(row["is_weekly_summary"]),
        )
