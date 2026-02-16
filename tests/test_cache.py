"""Tests for SQLite cache service."""

from datetime import date, timedelta

import pytest

from src.models.journal_entry import JournalEntry, Mood, Testik
from src.utils.cache import CacheService


class TestCacheService:
    def test_init_creates_tables(self, cache_service: CacheService) -> None:
        """DB tables should be created on init."""
        entries = cache_service.get_entries()
        assert entries == []

    def test_upsert_and_retrieve(self, cache_service: CacheService, sample_entries: list[JournalEntry]) -> None:
        """Entries can be inserted and retrieved."""
        count = cache_service.upsert_entries(sample_entries)
        assert count == len(sample_entries)

        retrieved = cache_service.get_entries()
        assert len(retrieved) == len(sample_entries)
        assert retrieved[0].id == sample_entries[-1].id  # DESC order, latest first

    def test_upsert_idempotent(self, cache_service: CacheService, sample_entries: list[JournalEntry]) -> None:
        """Upserting same entries twice doesn't duplicate."""
        cache_service.upsert_entries(sample_entries)
        cache_service.upsert_entries(sample_entries)
        assert len(cache_service.get_entries()) == len(sample_entries)

    def test_date_filtering(self, cache_service: CacheService, sample_entries: list[JournalEntry]) -> None:
        """Date range filtering works correctly."""
        cache_service.upsert_entries(sample_entries)

        recent = cache_service.get_entries(
            start_date=date.today() - timedelta(days=5),
            end_date=date.today(),
        )
        assert len(recent) <= 6  # At most 6 days

    def test_get_recent(self, cache_service: CacheService, sample_entries: list[JournalEntry]) -> None:
        """get_recent helper returns correct window."""
        cache_service.upsert_entries(sample_entries)
        recent = cache_service.get_recent(days=7)
        for entry in recent:
            assert entry.entry_date >= date.today() - timedelta(days=7)

    def test_cache_freshness(self, cache_service: CacheService) -> None:
        """Cache should not be fresh initially, then fresh after marking."""
        assert not cache_service.is_cache_fresh()
        cache_service.mark_synced()
        assert cache_service.is_cache_fresh()

    def test_cleanup_old(self, cache_service: CacheService, sample_entries: list[JournalEntry]) -> None:
        """Old entries are cleaned up correctly."""
        # Create some very old entries
        old_entries = [
            JournalEntry(
                id=f"old-{i}",
                entry_date=date.today() - timedelta(days=200 + i),
                mood=Mood.NORMAL,
            )
            for i in range(5)
        ]
        cache_service.upsert_entries(old_entries + sample_entries)
        total_before = len(cache_service.get_entries(
            start_date=date.today() - timedelta(days=365)
        ))

        removed = cache_service.cleanup_old(keep_days=90)
        assert removed == 5

    def test_entry_fields_preserved(self, cache_service: CacheService) -> None:
        """All fields survive round-trip through cache."""
        entry = JournalEntry(
            id="full-test",
            entry_date=date(2025, 6, 15),
            mood=Mood.PERFECT,
            hours_worked=9.5,
            tasks_completed=7,
            testik=Testik.PLUS,
            workout=True,
            university=True,
            earnings_usd=250.0,
            sleep_hours=8.0,
            notes="Full field test entry",
        )
        cache_service.upsert_entries([entry])
        results = cache_service.get_entries(
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 30),
        )
        assert len(results) == 1
        r = results[0]
        assert r.id == "full-test"
        assert r.mood == Mood.PERFECT
        assert r.hours_worked == 9.5
        assert r.tasks_completed == 7
        assert r.testik == Testik.PLUS
        assert r.workout is True
        assert r.university is True
        assert r.earnings_usd == 250.0
        assert r.sleep_hours == 8.0
        assert r.notes == "Full field test entry"
