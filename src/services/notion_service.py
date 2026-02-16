"""Notion API integration — CRUD operations for the Daily Journal database."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import get_settings
from src.models.journal_entry import JournalEntry, Mood, Testik
from src.utils.cache import CacheService

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionService:
    """Async Notion client with retry logic, connection pooling, and local caching."""

    def __init__(self, cache: Optional[CacheService] = None) -> None:
        settings = get_settings()
        self._token = settings.notion.token
        self._database_id = settings.notion.database_id
        self._cache = cache or CacheService(ttl_seconds=settings.app.cache_ttl_seconds)
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create a reusable httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self._headers,
                timeout=30,
            )
        return self._client

    async def close(self) -> None:
        """Close the httpx client (call on shutdown)."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── Public API ──────────────────────────────────────────────────────────

    async def get_entries(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        force_refresh: bool = False,
    ) -> list[JournalEntry]:
        """
        Fetch journal entries from Notion (or cache if fresh).

        Args:
            start_date: Earliest date to fetch. Defaults to 90 days ago.
            end_date: Latest date to fetch. Defaults to today.
            force_refresh: Skip cache and query Notion.
        """
        if not force_refresh and self._cache.is_cache_fresh():
            logger.debug("Serving from cache")
            return self._cache.get_entries(start_date, end_date)

        if start_date is None:
            start_date = date.today() - timedelta(days=90)
        if end_date is None:
            end_date = date.today()

        raw_pages = await self._query_database(start_date, end_date)
        entries = [self._parse_page(page) for page in raw_pages]
        entries = [e for e in entries if e is not None]

        if entries:
            self._cache.upsert_entries(entries)
            self._cache.mark_synced()

        return entries

    async def get_entries_for_month(
        self, year: int, month: int, force_refresh: bool = False
    ) -> list[JournalEntry]:
        """Get all entries for a specific month."""
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        return await self.get_entries(start, end, force_refresh)

    async def get_recent(
        self, days: int = 30, force_refresh: bool = False
    ) -> list[JournalEntry]:
        """Get entries for the last N days."""
        return await self.get_entries(
            start_date=date.today() - timedelta(days=days),
            end_date=date.today(),
            force_refresh=force_refresh,
        )

    async def sync_all(self) -> int:
        """Full sync: fetch all entries and update cache. Returns count."""
        entries = await self.get_entries(
            start_date=date.today() - timedelta(days=365),
            force_refresh=True,
        )
        self._cache.cleanup_old(keep_days=365)
        return len(entries)

    # ── Notion API calls ────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def _query_database(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Query Notion database with date filter and pagination."""
        all_pages: list[dict[str, Any]] = []
        has_more = True
        next_cursor: Optional[str] = None

        filter_body: dict[str, Any] = {
            "filter": {
                "and": [
                    {
                        "property": "Date",
                        "date": {"on_or_after": start_date.isoformat()},
                    },
                    {
                        "property": "Date",
                        "date": {"on_or_before": end_date.isoformat()},
                    },
                ]
            },
            "sorts": [{"property": "Date", "direction": "descending"}],
            "page_size": 100,
        }

        client = await self._get_client()
        while has_more:
            if next_cursor:
                filter_body["start_cursor"] = next_cursor

            resp = await client.post(
                f"{NOTION_API}/databases/{self._database_id}/query",
                json=filter_body,
            )
            resp.raise_for_status()
            data = resp.json()

            all_pages.extend(data.get("results", []))
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")

        logger.info("Fetched %d pages from Notion", len(all_pages))
        return all_pages

    # ── Parsing ─────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_page(page: dict[str, Any]) -> Optional[JournalEntry]:
        """Parse a Notion page into a JournalEntry."""
        try:
            props = page["properties"]
            page_id = page["id"]

            entry_date_raw = _get_date(props, "Date")
            if not entry_date_raw:
                logger.warning("Skipping page %s: no Date", page_id)
                return None

            return JournalEntry(
                id=page_id,
                entry_date=date.fromisoformat(entry_date_raw),
                mood=_get_select_enum(props, "Mood", Mood),
                hours_worked=_get_number(props, "Hours Worked"),
                tasks_completed=int(_get_number(props, "Tasks Completed")),
                testik=_get_select_enum(props, "TESTIK", Testik),
                workout=_get_checkbox(props, "Workout"),
                university=_get_checkbox(props, "University"),
                earnings_usd=_get_number(props, "Earnings USD"),
                sleep_hours=_get_number(props, "Sleep Hours"),
                notes=_get_rich_text(props, "Notes"),
            )
        except Exception as e:
            logger.error("Failed to parse page %s: %s", page.get("id"), e)
            return None


# ── Notion property helpers ─────────────────────────────────────────────────


def _get_date(props: dict, name: str) -> Optional[str]:
    prop = props.get(name, {})
    date_obj = prop.get("date")
    if date_obj and date_obj.get("start"):
        return date_obj["start"][:10]
    return None


def _get_number(props: dict, name: str) -> float:
    prop = props.get(name, {})
    val = prop.get("number")
    return float(val) if val is not None else 0.0


def _get_checkbox(props: dict, name: str) -> bool:
    prop = props.get(name, {})
    return bool(prop.get("checkbox", False))


def _get_select_enum(props: dict, name: str, enum_cls: type) -> Optional[Any]:
    prop = props.get(name, {})
    select = prop.get("select")
    if select and select.get("name"):
        raw = select["name"].upper().replace(" ", "_")
        try:
            return enum_cls(raw)
        except ValueError:
            logger.warning("Unknown %s value: %s", name, raw)
    return None


def _get_rich_text(props: dict, name: str) -> str:
    prop = props.get(name, {})
    texts = prop.get("rich_text", [])
    return "".join(t.get("plain_text", "") for t in texts)
