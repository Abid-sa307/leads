"""Unit tests for the Database layer."""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path

import pytest
import pytest_asyncio

import sys
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.database import Database
from storage.models import CrawlStatus, Industry, WebsiteResolution


@pytest.fixture
def industry():
    return Industry(
        industry_name="Test Corp",
        city="Springfield",
        state="IL",
        country="US",
        website="https://test.com",
        source="test",
        crawl_status=CrawlStatus.PENDING,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
class TestDatabase:
    """Async tests for the SQLite database layer."""

    @pytest_asyncio.fixture
    async def db(self, tmp_path):
        """Provide a fresh in-memory-like DB for each test."""
        db_path = tmp_path / "test.db"
        async with Database(db_path, backup_on_start=False) as database:
            yield database

    async def test_upsert_industry_inserts(self, db, industry):
        """Upserting a new industry should return a valid row ID."""
        industry_id = await db.upsert_industry(industry)
        assert isinstance(industry_id, int)
        assert industry_id > 0

    async def test_upsert_industry_updates(self, db, industry):
        """Upserting the same industry twice should update, not duplicate."""
        id1 = await db.upsert_industry(industry)
        industry.website = "https://updated.com"
        id2 = await db.upsert_industry(industry)
        assert id1 == id2

        fetched = await db.get_industry_by_id(id1)
        assert fetched is not None
        assert fetched.website == "https://updated.com"

    async def test_get_industry_by_id(self, db, industry):
        """Should retrieve the correct industry by ID."""
        industry_id = await db.upsert_industry(industry)
        fetched = await db.get_industry_by_id(industry_id)
        assert fetched is not None
        assert fetched.industry_name == "Test Corp"
        assert fetched.city == "Springfield"

    async def test_get_industry_by_id_not_found(self, db):
        """Non-existent ID should return None."""
        result = await db.get_industry_by_id(99999)
        assert result is None

    async def test_update_status(self, db, industry):
        """update_status should change crawl_status."""
        industry_id = await db.upsert_industry(industry)
        await db.update_status(industry_id, CrawlStatus.DONE)
        fetched = await db.get_industry_by_id(industry_id)
        assert fetched.crawl_status == CrawlStatus.DONE

    async def test_update_status_increment_retry(self, db, industry):
        """increment_retry=True should increase retry_count."""
        industry_id = await db.upsert_industry(industry)
        await db.update_status(industry_id, CrawlStatus.FAILED, increment_retry=True)
        await db.update_status(industry_id, CrawlStatus.FAILED, increment_retry=True)
        fetched = await db.get_industry_by_id(industry_id)
        assert fetched.retry_count == 2

    async def test_bulk_insert_industries(self, db):
        """Bulk insert should add all unique industries."""
        industries = [
            Industry(industry_name=f"Industry {i}", city="City", state="ST",
                     country="US", created_at=datetime.now(UTC))
            for i in range(5)
        ]
        inserted = await db.bulk_insert_industries(industries)
        assert inserted == 5

    async def test_bulk_insert_deduplication(self, db):
        """Duplicate bulk inserts should not create duplicate rows."""
        industry = Industry(
            industry_name="Dup Industry", city="NYC", state="NY",
            country="US", created_at=datetime.now(UTC)
        )
        await db.bulk_insert_industries([industry])
        inserted2 = await db.bulk_insert_industries([industry])
        assert inserted2 == 0  # Already exists

    async def test_get_pending_industries(self, db):
        """Should return only PENDING and FAILED industries within retry limit."""
        pending = Industry(
            industry_name="Pending Ind", city="A", state="B",
            country="US", crawl_status=CrawlStatus.PENDING,
            created_at=datetime.now(UTC)
        )
        done = Industry(
            industry_name="Done Ind", city="C", state="D",
            country="US", crawl_status=CrawlStatus.DONE,
            created_at=datetime.now(UTC)
        )
        await db.bulk_insert_industries([pending, done])
        result = await db.get_pending_industries(max_retries=3)
        names = [s.industry_name for s in result]
        assert "Pending Ind" in names
        assert "Done Ind" not in names

    async def test_get_statistics(self, db, industry):
        """Statistics should reflect current industry statuses."""
        await db.upsert_industry(industry)
        stats = await db.get_statistics()
        assert stats.get("pending", 0) >= 1

    async def test_website_cache(self, db):
        """Should store and retrieve cached website resolutions."""
        resolution = WebsiteResolution(
            industry_name="Cache Industry",
            city="Test",
            state="CA",
            resolved_url="https://cacheindustry.com",
            resolution_method="search",
            verified=True,
        )
        await db.cache_website(resolution)
        cached = await db.get_cached_website("Cache Industry", "Test", "CA")
        assert cached == "https://cacheindustry.com"

    async def test_website_cache_miss(self, db):
        """Cache miss should return None."""
        result = await db.get_cached_website("NonExistent", None, None)
        assert result is None

    async def test_get_all_done_async_generator(self, db, industry):
        """get_all_done should yield done industries."""
        industry_id = await db.upsert_industry(industry)
        await db.update_status(industry_id, CrawlStatus.DONE)
        done_industries = []
        async for s in db.get_all_done():
            done_industries.append(s)
        assert any(s.industry_name == "Test Corp" for s in done_industries)
