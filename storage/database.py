"""
Async SQLite database layer for the Industry Contact Discovery System.

All operations are non-blocking via aiosqlite.
Supports incremental saves, atomic transactions, and resume-safe state management.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, UTC
from pathlib import Path
from typing import AsyncGenerator, Optional

import aiosqlite

from storage.models import (
    SCHEMA_SQL,
    SCHEMA_VERSION,
    CrawlLogEntry,
    CrawlStatus,
    Industry,
    WebsiteResolution,
)

logger = logging.getLogger("crawl")


class Database:
    """
    Async SQLite database wrapper.

    Usage:
        async with Database("data/industries.db") as db:
            await db.upsert_industry(industry)
    """

    def __init__(self, db_path: str | Path, backup_on_start: bool = True) -> None:
        self._path = Path(db_path)
        self._backup_on_start = backup_on_start
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "Database":
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the database connection and ensure schema is up to date."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        if self._backup_on_start and self._path.exists():
            self._make_backup()

        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
        await self._apply_migrations()
        logger.info("Database connected: %s", self._path)

    async def close(self) -> None:
        """Close the database connection gracefully."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Database connection closed.")

    def _make_backup(self) -> None:
        """Copy the existing database file to a timestamped backup."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup = self._path.with_suffix(f".{timestamp}.bak")
        shutil.copy2(self._path, backup)
        logger.info("Database backup created: %s", backup)

    async def _apply_migrations(self) -> None:
        """Apply schema migrations in version order."""
        assert self._conn
        async with self._conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ) as cur:
            row = await cur.fetchone()
            current_version = row[0] if row and row[0] is not None else 0

        if current_version < 2:
            try:
                await self._conn.execute("ALTER TABLE industries ADD COLUMN email_sent_status TEXT")
                await self._conn.execute("ALTER TABLE industries ADD COLUMN email_sent_at TEXT")
                await self._conn.execute("ALTER TABLE industries ADD COLUMN email_sent_error TEXT")
                await self._conn.commit()
                logger.info("Migrated database to version 2: added email_sent columns.")
            except aiosqlite.OperationalError:
                pass

        if current_version < SCHEMA_VERSION:
            await self._conn.execute(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            await self._conn.commit()

    # ------------------------------------------------------------------
    # Industry CRUD
    # ------------------------------------------------------------------

    async def upsert_industry(self, industry: Industry) -> int:
        """
        Insert or update an industry record.

        Returns:
            The row ID of the upserted industry.
        """
        assert self._conn
        async with self._lock:
            now = datetime.now(UTC).isoformat()
            await self._conn.execute(
                """
                INSERT INTO industries (
                    industry_name, city, state, country,
                    website, email, phone, exec_email, hr_email,
                    source, crawl_status, retry_count, error_message,
                    raw_website_input, last_updated, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(industry_name, city, state) DO UPDATE SET
                    website      = COALESCE(excluded.website, website),
                    email        = COALESCE(excluded.email, email),
                    phone        = COALESCE(excluded.phone, phone),
                    exec_email   = COALESCE(excluded.exec_email, exec_email),
                    hr_email     = COALESCE(excluded.hr_email, hr_email),
                    crawl_status = excluded.crawl_status,
                    retry_count  = excluded.retry_count,
                    error_message= excluded.error_message,
                    last_updated = excluded.last_updated
                """,
                (
                    industry.industry_name,
                    industry.city,
                    industry.state,
                    industry.country,
                    industry.website,
                    industry.email,
                    industry.phone,
                    industry.exec_email,
                    industry.hr_email,
                    industry.source,
                    industry.crawl_status.value,
                    industry.retry_count,
                    industry.error_message,
                    industry.raw_website_input,
                    now,
                    industry.created_at.isoformat() if industry.created_at else now,
                ),
            )
            await self._conn.commit()

            async with self._conn.execute(
                "SELECT id FROM industries WHERE industry_name=? AND city IS ? AND state IS ?",
                (industry.industry_name, industry.city, industry.state),
            ) as cur:
                row = await cur.fetchone()
                return row["id"] if row else -1

    async def update_status(
        self,
        industry_id: int,
        status: CrawlStatus,
        error_message: Optional[str] = None,
        increment_retry: bool = False,
    ) -> None:
        """Update only the crawl status (fast, no full record needed)."""
        assert self._conn
        async with self._lock:
            await self._conn.execute(
                """
                UPDATE industries
                SET crawl_status  = ?,
                    error_message = ?,
                    retry_count   = retry_count + ?,
                    last_updated  = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    error_message,
                    1 if increment_retry else 0,
                    datetime.now(UTC).isoformat(),
                    industry_id,
                ),
            )
            await self._conn.commit()

    async def update_mail_status(
        self,
        industry_id: int,
        status: str,
        sent_at: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update email campaign status for a lead."""
        assert self._conn
        async with self._lock:
            await self._conn.execute(
                """
                UPDATE industries
                SET email_sent_status = ?,
                    email_sent_at     = ?,
                    email_sent_error  = ?,
                    last_updated      = ?
                WHERE id = ?
                """,
                (
                    status,
                    sent_at,
                    error_message,
                    datetime.now(UTC).isoformat(),
                    industry_id,
                ),
            )
            await self._conn.commit()

    async def bulk_insert_industries(self, industries: list[Industry]) -> int:
        """
        Bulk insert a list of industries (ignore conflicts = deduplication).

        Returns:
            Number of new rows inserted.
        """
        assert self._conn
        async with self._lock:
            now = datetime.now(UTC).isoformat()
            rows = [
                (
                    s.industry_name, s.city, s.state, s.country,
                    s.website, s.source, s.crawl_status.value,
                    s.raw_website_input, now, now,
                )
                for s in industries
            ]
            # Snapshot total_changes() before batch to compute diff
            async with self._conn.execute("SELECT total_changes()") as cur:
                before_row = await cur.fetchone()
                before = before_row[0] if before_row else 0

            await self._conn.executemany(
                """
                INSERT OR IGNORE INTO industries
                    (industry_name, city, state, country, website, source,
                     crawl_status, raw_website_input, last_updated, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            await self._conn.commit()

            # Diff total_changes() to get count of all new rows
            async with self._conn.execute("SELECT total_changes()") as cur:
                after_row = await cur.fetchone()
                after = after_row[0] if after_row else 0
            return after - before

    async def get_industry_by_id(self, industry_id: int) -> Optional[Industry]:
        """Fetch a single industry by ID."""
        assert self._conn
        async with self._conn.execute(
            "SELECT * FROM industries WHERE id = ?", (industry_id,)
        ) as cur:
            row = await cur.fetchone()
            return _row_to_industry(row) if row else None

    async def get_pending_industries(self, max_retries: int = 3) -> list[Industry]:
        """
        Return all industries that need processing.

        Includes PENDING and FAILED industries within the retry limit.
        """
        assert self._conn
        async with self._conn.execute(
            """
            SELECT * FROM industries
            WHERE crawl_status IN ('pending', 'failed', 'resolving', 'crawling')
              AND retry_count < ?
            ORDER BY id ASC
            """,
            (max_retries,),
        ) as cur:
            rows = await cur.fetchall()
            return [_row_to_industry(r) for r in rows]

    async def get_statistics(self) -> dict[str, int]:
        """Return counts grouped by crawl_status."""
        assert self._conn
        async with self._conn.execute(
            "SELECT crawl_status, COUNT(*) as cnt FROM industries GROUP BY crawl_status"
        ) as cur:
            rows = await cur.fetchall()
            return {r["crawl_status"]: r["cnt"] for r in rows}

    async def get_all_done(self) -> AsyncGenerator[Industry, None]:
        """Stream all completed industries (generator for memory efficiency)."""
        assert self._conn
        async with self._conn.execute(
            "SELECT * FROM industries WHERE crawl_status = 'done'"
        ) as cur:
            async for row in cur:
                yield _row_to_industry(row)

    async def get_all_failed(self) -> list[Industry]:
        """Return all failed industries."""
        assert self._conn
        async with self._conn.execute(
            "SELECT * FROM industries WHERE crawl_status = 'failed'"
        ) as cur:
            return [_row_to_industry(r) for r in await cur.fetchall()]

    async def get_all_industries(self) -> list[Industry]:
        """Return every industry in the database."""
        assert self._conn
        async with self._conn.execute("SELECT * FROM industries ORDER BY id") as cur:
            return [_row_to_industry(r) for r in await cur.fetchall()]

    # ------------------------------------------------------------------
    # Website cache
    # ------------------------------------------------------------------

    async def cache_website(self, resolution: WebsiteResolution) -> None:
        """Store a resolved website URL in the cache."""
        assert self._conn
        async with self._lock:
            await self._conn.execute(
                """
                INSERT OR REPLACE INTO website_cache
                    (industry_name, city, state, resolved_url, resolution_method, verified, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolution.industry_name,
                    resolution.city,
                    resolution.state,
                    resolution.resolved_url,
                    resolution.resolution_method,
                    int(resolution.verified),
                    datetime.now(UTC).isoformat(),
                ),
            )
            await self._conn.commit()

    async def get_cached_website(
        self, industry_name: str, city: Optional[str], state: Optional[str]
    ) -> Optional[str]:
        """Return cached resolved URL or None."""
        assert self._conn
        async with self._conn.execute(
            """
            SELECT resolved_url FROM website_cache
            WHERE industry_name = ? AND city IS ? AND state IS ?
            """,
            (industry_name, city, state),
        ) as cur:
            row = await cur.fetchone()
            return row["resolved_url"] if row else None

    # ------------------------------------------------------------------
    # Crawl log
    # ------------------------------------------------------------------

    async def log_crawl(self, entry: CrawlLogEntry) -> None:
        """Append a crawl event to the crawl_log table."""
        assert self._conn
        async with self._lock:
            await self._conn.execute(
                """
                INSERT INTO crawl_log
                    (industry_id, industry_name, url, status, http_status, duration_ms, error, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.industry_id,
                    entry.industry_name,
                    entry.url,
                    entry.status,
                    entry.http_status,
                    entry.duration_ms,
                    entry.error,
                    entry.timestamp.isoformat(),
                ),
            )
            await self._conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_industry(row: aiosqlite.Row) -> Industry:
    """Convert a SQLite row to an Industry model instance."""
    data = dict(row)
    data["crawl_status"] = CrawlStatus(data["crawl_status"])
    for dt_field in ("last_updated", "created_at"):
        if data.get(dt_field):
            try:
                data[dt_field] = datetime.fromisoformat(data[dt_field])
            except (ValueError, TypeError):
                data[dt_field] = None
    return Industry(**data)
