"""Notion API integration — reads Tasks database and parses MARK entries."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import get_settings
from src.models.journal_entry import (
    DailyRecord,
    SleepInfo,
    TaskEntry,
)
from src.utils.cache import CacheService
from src.utils.validators import parse_day_rating, parse_sleep_info, parse_testik

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Tags that map to specific boolean flags on DailyRecord
_WORKOUT_TAGS = {"GYM", "WORKOUT", "FOOTBALL", "TENNIS", "PADEL", "SPORT"}
_UNI_TAGS = {"UNIVERSITY", "UNI"}
_CODING_TAGS = {"CODING", "CODE", "PROGRAMMING"}
_KATE_TAGS = {"KATE"}


class NotionService:
    """Async Notion client with page content parsing, retry logic, and caching."""

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

    # ── Public API ──────────────────────────────────────────────────────────

    async def get_daily_records(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        force_refresh: bool = False,
    ) -> list[DailyRecord]:
        """
        Fetch and aggregate daily records.

        1. Query Notion database for all task entries in range
        2. For MARK entries: fetch page content (blocks) to get body text
        3. Group tasks by date → build DailyRecord per day
        4. Cache results
        """
        if not force_refresh and self._cache.is_cache_fresh():
            logger.debug("Serving daily records from cache")
            return self._cache.get_daily_records(start_date, end_date)

        if start_date is None:
            start_date = date.today() - timedelta(days=90)
        if end_date is None:
            end_date = date.today()

        # Step 1: Query all task pages
        raw_pages = await self._query_database(start_date, end_date)
        tasks = [self._parse_page(p) for p in raw_pages]
        tasks = [t for t in tasks if t is not None]

        # Step 2: Fetch body text for MARK entries (contains sleep, testik, rating)
        for task in tasks:
            if task.title.upper() in ("MARK", "MARK'S WEAK", "MARK'S WEEK"):
                task.body_text = await self._get_page_blocks_text(task.id)

        # Step 3: Group by date → DailyRecord
        records = self._aggregate_daily(tasks)

        # Step 4: Cache
        if tasks:
            self._cache.upsert_tasks(tasks)
        if records:
            self._cache.upsert_daily_records(records)
            self._cache.mark_synced()

        return records

    async def get_daily_for_month(
        self, year: int, month: int, force_refresh: bool = False
    ) -> list[DailyRecord]:
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        return await self.get_daily_records(start, end, force_refresh)

    async def get_recent(
        self, days: int = 30, force_refresh: bool = False
    ) -> list[DailyRecord]:
        return await self.get_daily_records(
            start_date=date.today() - timedelta(days=days),
            end_date=date.today(),
            force_refresh=force_refresh,
        )

    async def sync_all(self) -> int:
        records = await self.get_daily_records(
            start_date=date.today() - timedelta(days=365),
            force_refresh=True,
        )
        self._cache.cleanup_old(keep_days=365)
        return len(records)

    # ── Notion API calls ────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def _query_database(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Query database with date filter and pagination."""
        all_pages: list[dict[str, Any]] = []
        has_more = True
        next_cursor: Optional[str] = None

        filter_body: dict[str, Any] = {
            "filter": {
                "and": [
                    {"property": "Date", "date": {"on_or_after": start_date.isoformat()}},
                    {"property": "Date", "date": {"on_or_before": end_date.isoformat()}},
                ]
            },
            "sorts": [{"property": "Date", "direction": "descending"}],
            "page_size": 100,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            while has_more:
                if next_cursor:
                    filter_body["start_cursor"] = next_cursor

                resp = await client.post(
                    f"{NOTION_API}/databases/{self._database_id}/query",
                    headers=self._headers,
                    json=filter_body,
                )
                resp.raise_for_status()
                data = resp.json()

                all_pages.extend(data.get("results", []))
                has_more = data.get("has_more", False)
                next_cursor = data.get("next_cursor")

        logger.info("Fetched %d task pages from Notion", len(all_pages))
        return all_pages

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=0.5, max=5))
    async def _get_page_blocks_text(self, page_id: str) -> str:
        """Fetch all blocks (content) of a page and return plain text."""
        blocks_text: list[str] = []
        has_more = True
        next_cursor: Optional[str] = None

        async with httpx.AsyncClient(timeout=30) as client:
            while has_more:
                url = f"{NOTION_API}/blocks/{page_id}/children?page_size=100"
                if next_cursor:
                    url += f"&start_cursor={next_cursor}"

                resp = await client.get(url, headers=self._headers)
                resp.raise_for_status()
                data = resp.json()

                for block in data.get("results", []):
                    text = self._extract_block_text(block)
                    if text:
                        blocks_text.append(text)

                has_more = data.get("has_more", False)
                next_cursor = data.get("next_cursor")

        return "\n".join(blocks_text)

    # ── Parsing ─────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_page(page: dict[str, Any]) -> Optional[TaskEntry]:
        """Parse a Notion page into a TaskEntry."""
        try:
            props = page["properties"]
            page_id = page["id"]

            entry_date_raw = _get_date(props, "Date")
            if not entry_date_raw:
                return None

            title = _get_title(props)
            tags = _get_multi_select(props, "Tags")
            checkbox = _get_checkbox(props, "Checkbox")
            hours = _get_number(props, "It took (hours)")

            return TaskEntry(
                id=page_id,
                title=title,
                entry_date=date.fromisoformat(entry_date_raw),
                tags=tags,
                checkbox=checkbox,
                hours=hours if hours > 0 else None,
                body_text="",
            )
        except Exception as e:
            logger.error("Failed to parse page %s: %s", page.get("id"), e)
            return None

    @staticmethod
    def _extract_block_text(block: dict[str, Any]) -> str:
        """Extract plain text from a single Notion block."""
        block_type = block.get("type", "")
        block_data = block.get(block_type, {})

        if "rich_text" in block_data:
            return "".join(
                t.get("plain_text", "") for t in block_data["rich_text"]
            )
        if "text" in block_data:
            return "".join(
                t.get("plain_text", "") for t in block_data["text"]
            )
        return ""

    # ── Aggregation ─────────────────────────────────────────────────────────

    @staticmethod
    def _aggregate_daily(tasks: list[TaskEntry]) -> list[DailyRecord]:
        """Group tasks by date and build DailyRecord per day."""
        by_date: dict[date, list[TaskEntry]] = defaultdict(list)
        for task in tasks:
            by_date[task.entry_date].append(task)

        records: list[DailyRecord] = []
        for day, day_tasks in sorted(by_date.items(), reverse=True):
            mark_task: Optional[TaskEntry] = None
            is_weekly = False

            all_tags: list[str] = []
            total_hours = 0.0
            completed = 0
            flags = {"workout": False, "university": False, "coding": False, "kate": False}

            for t in day_tasks:
                title_upper = t.title.upper().strip()

                # Detect MARK entry
                if title_upper == "MARK":
                    mark_task = t
                elif title_upper in ("MARK'S WEAK", "MARK'S WEEK"):
                    is_weekly = True
                    mark_task = t

                # Collect tags
                for tag in t.tags:
                    tag_upper = tag.upper().strip()
                    if tag_upper not in all_tags:
                        all_tags.append(tag)
                    if tag_upper in _WORKOUT_TAGS:
                        flags["workout"] = True
                    if tag_upper in _UNI_TAGS:
                        flags["university"] = True
                    if tag_upper in _CODING_TAGS:
                        flags["coding"] = True
                    if tag_upper in _KATE_TAGS:
                        flags["kate"] = True

                # Also check title for activity detection
                if title_upper in _WORKOUT_TAGS:
                    flags["workout"] = True
                if title_upper in _UNI_TAGS:
                    flags["university"] = True
                if title_upper in _CODING_TAGS:
                    flags["coding"] = True
                if title_upper in _KATE_TAGS:
                    flags["kate"] = True

                if t.hours:
                    total_hours += t.hours
                if t.checkbox:
                    completed += 1

            # Parse MARK body for sleep, testik, rating
            sleep = SleepInfo()
            testik = None
            rating = None
            journal_text = ""

            if mark_task and mark_task.body_text:
                body = mark_task.body_text
                journal_text = body
                sleep = parse_sleep_info(body)
                testik = parse_testik(body)
                rating = parse_day_rating(body)

            records.append(DailyRecord(
                entry_date=day,
                rating=rating,
                testik=testik,
                sleep=sleep,
                activities=all_tags,
                total_hours=round(total_hours, 1),
                tasks_count=len(day_tasks),
                tasks_completed=completed,
                had_workout=flags["workout"],
                had_university=flags["university"],
                had_coding=flags["coding"],
                had_kate=flags["kate"],
                journal_text=journal_text,
                is_weekly_summary=is_weekly,
            ))

        return records


# ── Notion property helpers ─────────────────────────────────────────────────


def _get_title(props: dict) -> str:
    """Extract the page title (from the 'title' type property)."""
    for prop in props.values():
        if prop.get("type") == "title":
            texts = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in texts)
    return ""


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


def _get_multi_select(props: dict, name: str) -> list[str]:
    prop = props.get(name, {})
    options = prop.get("multi_select", [])
    return [opt["name"] for opt in options if opt.get("name")]


def _get_rich_text(props: dict, name: str) -> str:
    prop = props.get(name, {})
    texts = prop.get("rich_text", [])
    return "".join(t.get("plain_text", "") for t in texts)
