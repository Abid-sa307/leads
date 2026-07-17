"""
Integration test for the full discovery pipeline.

Uses the sample dataset and verifies end-to-end flow with mocked
Playwright and HTTP calls to avoid network dependencies.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

import sys
if str(Path(__file__).resolve().parent.parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.pipeline import Pipeline
from config.settings import reset_settings
from importers.importer import IndustryImporter
from storage.database import Database
from storage.models import CrawlStatus, Industry, Statistics


SAMPLE_HTML = """
<html>
<body>
    <h1>Welcome to Test Company</h1>
    <p>For inquiries, email us at <a href="mailto:info@testcompany.com">info@testcompany.com</a></p>
    <p>Careers: <a href="mailto:hr@testcompany.com">hr@testcompany.com</a></p>
    <p>Call us: <a href="tel:+15551234567">(555) 123-4567</a></p>
</body>
</html>
"""


@pytest.mark.asyncio
class TestPipelineIntegration:
    """End-to-end integration tests with mocked external services."""

    @pytest_asyncio.fixture
    async def db(self, tmp_path):
        db_path = tmp_path / "integration_test.db"
        async with Database(db_path, backup_on_start=False) as database:
            yield database

    @pytest_asyncio.fixture
    async def seeded_db(self, db):
        """DB seeded with 2 industries."""
        industries = [
            Industry(
                industry_name="Test Company",
                city="Springfield",
                state="IL",
                country="US",
                website="https://www.testcompany.com",
                raw_website_input="https://www.testcompany.com",
                source="integration_test",
                crawl_status=CrawlStatus.PENDING,
                created_at=datetime.now(UTC),
            ),
            Industry(
                industry_name="Sample Corp",
                city="Boston",
                state="MA",
                country="US",
                website="https://www.samplecorp.com",
                raw_website_input="https://www.samplecorp.com",
                source="integration_test",
                crawl_status=CrawlStatus.PENDING,
                created_at=datetime.now(UTC),
            ),
        ]
        await db.bulk_insert_industries(industries)
        return db

    async def test_importer_to_database(self, tmp_path, db):
        """Importer -> Database: imported industries should land in DB as PENDING."""
        csv_path = tmp_path / "industries.csv"
        csv_path.write_text(
            "Industry Name,City,State,Website\n"
            "Alpha Corp,Dallas,TX,https://alpha.com\n"
            "Beta Inc,Miami,FL,\n",
            encoding="utf-8",
        )
        importer = IndustryImporter()
        industries, skipped = importer.load(csv_path, source="test_batch")
        inserted = await db.bulk_insert_industries(industries)
        assert inserted == 2
        assert len(skipped) == 0

        pending = await db.get_pending_industries()
        assert len(pending) == 2
        assert all(s.crawl_status == CrawlStatus.PENDING for s in pending)

    async def test_pipeline_processes_industries(self, seeded_db, tmp_path):
        """Pipeline should mark industries as done after mocked crawl."""
        reset_settings()
        stats = Statistics()
        active_urls: list[str] = []

        # Mock the entire crawl chain
        mock_crawl_result = MagicMock()
        mock_crawl_result.success = True
        mock_crawl_result.error = None
        mock_crawl_result.base_url = "https://www.testcompany.com"
        mock_page = MagicMock()
        mock_page.html = SAMPLE_HTML
        mock_page.error = None
        mock_page.url = "https://www.testcompany.com/contact"
        mock_crawl_result.pages = [mock_page]

        with (
            patch("app.pipeline.BrowserPool") as mock_pool_cls,
            patch("app.pipeline.PageCrawler") as mock_crawler_cls,
            patch("app.pipeline.WebsiteResolver") as mock_resolver_cls,
        ):
            # BrowserPool context manager
            mock_pool = AsyncMock()
            mock_pool.__aenter__ = AsyncMock(return_value=mock_pool)
            mock_pool.__aexit__ = AsyncMock(return_value=False)
            mock_pool_cls.return_value = mock_pool

            # WebsiteResolver
            mock_resolver = AsyncMock()
            mock_resolver.__aenter__ = AsyncMock(return_value=mock_resolver)
            mock_resolver.__aexit__ = AsyncMock(return_value=False)
            from storage.models import WebsiteResolution
            mock_resolver.resolve = AsyncMock(
                return_value=WebsiteResolution(
                    industry_name="Test Company",
                    resolved_url="https://www.testcompany.com",
                    resolution_method="existing",
                    verified=True,
                )
            )
            mock_resolver_cls.return_value = mock_resolver

            # PageCrawler
            mock_crawler = MagicMock()
            mock_crawler.crawl_industry = AsyncMock(return_value=mock_crawl_result)
            mock_crawler_cls.return_value = mock_crawler

            pipeline = Pipeline(db=seeded_db, stats=stats, active_urls=active_urls)
            final_stats = await pipeline.run()

        assert final_stats.processed >= 1

    async def test_resume_skips_done_industries(self, db, tmp_path):
        """Industries with DONE status should not be re-queued."""
        done_industry = Industry(
            industry_name="Already Done",
            city="Portland",
            state="OR",
            country="US",
            crawl_status=CrawlStatus.DONE,
            created_at=datetime.now(UTC),
        )
        await db.bulk_insert_industries([done_industry])

        pending = await db.get_pending_industries(max_retries=3)
        names = [s.industry_name for s in pending]
        assert "Already Done" not in names

    async def test_database_statistics_accuracy(self, seeded_db):
        """Statistics should correctly count industries by status."""
        stats = await seeded_db.get_statistics()
        total = sum(stats.values())
        assert total == 2
        assert stats.get("pending", 0) == 2

    async def test_report_generation(self, seeded_db, tmp_path):
        """Report exporter should create files from database."""
        from exporters.exporter import Exporter
        exporter = Exporter(str(tmp_path / "output"))
        paths = await exporter.generate_all_reports(db=seeded_db)
        assert (tmp_path / "output" / "summary.csv").exists()
        assert (tmp_path / "output" / "failed.csv").exists()
        assert (tmp_path / "output" / "industries_full.xlsx").exists()
