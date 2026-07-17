"""
Main pipeline orchestrator for the Industry Contact Discovery System.

Responsibilities:
  - Load pending industries from DB
  - Manage asyncio worker queue
  - Coordinate resolver -> crawler -> extractor -> validator -> storage
  - Update Statistics for the dashboard
  - Emit structured log entries
  - Resume automatically on restart
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, UTC
from urllib.parse import urlparse
from typing import Optional

from app.logger import log_statistics
from config import get_settings
from crawler.browser_pool import BrowserPool
from crawler.page_crawler import PageCrawler
from crawler.website_resolver import WebsiteResolver
from extractors.contact_extractor import ContactExtractor
from storage.database import Database
from storage.models import CrawlLogEntry, CrawlStatus, Industry, Statistics
from validators.contact_validator import ContactValidator

logger = logging.getLogger("crawl")
error_logger = logging.getLogger("error")
retry_logger = logging.getLogger("retry")


class Pipeline:
    """
    Async pipeline that processes a queue of industries end-to-end.

    Architecture:
        - One asyncio.Queue fed by the main task
        - N worker coroutines consuming from the queue
        - Shared BrowserPool across all workers
        - Thread-safe Statistics updated after each industry
    """

    def __init__(
        self,
        db: Database,
        stats: Statistics,
        active_urls: Optional[list[str]] = None,
    ) -> None:
        self._db = db
        self._stats = stats
        self._active_urls: list[str] = active_urls if active_urls is not None else []
        self._settings = get_settings()
        self._queue: asyncio.Queue[Industry] = asyncio.Queue()
        self._extractor = ContactExtractor()
        self._validator = ContactValidator()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> Statistics:
        """
        Load pending industries and process them all.

        Returns:
            Final Statistics snapshot.
        """
        self._stats.start_time = datetime.now(UTC)
        industries = await self._load_pending()

        if not industries:
            logger.info("No pending industries to process.")
            return self._stats

        self._stats.total_industries = await self._count_total()
        self._stats.pending = len(industries)
        logger.info("Pipeline starting: %d industries in queue", len(industries))

        # Seed queue
        for industry in industries:
            await self._queue.put(industry)

        worker_count = self._settings.concurrency.worker_count
        async with BrowserPool(size=self._settings.concurrency.browser_pool_size) as pool:
            workers = [
                asyncio.create_task(self._worker(i, pool))
                for i in range(worker_count)
            ]
            # Wait for queue to be exhausted
            await self._queue.join()
            # Signal workers to stop
            for _ in range(worker_count):
                await self._queue.put(_SENTINEL)  # type: ignore[arg-type]
            await asyncio.gather(*workers, return_exceptions=True)

        self._stats.elapsed_seconds = time.monotonic() - (
            self._stats.start_time.timestamp() if self._stats.start_time else 0
        )
        log_statistics(self._stats.model_dump(mode="json"))
        logger.info(
            "Pipeline complete. Success=%d, Failed=%d, Skipped=%d",
            self._stats.successful,
            self._stats.failed,
            self._stats.skipped,
        )
        return self._stats

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    async def _worker(self, worker_id: int, pool: BrowserPool) -> None:
        """Consume industries from the queue until sentinel received."""
        crawler = PageCrawler(pool)

        async with WebsiteResolver(db=self._db) as resolver:
            while True:
                industry = await self._queue.get()
                if industry is _SENTINEL:
                    self._queue.task_done()
                    break
                try:
                    await self._process_industry(industry, crawler, resolver)
                except Exception as exc:
                    error_logger.error(
                        "Unhandled error processing '%s': %s",
                        industry.industry_name,
                        exc,
                        exc_info=True,
                    )
                finally:
                    self._queue.task_done()

    # ------------------------------------------------------------------
    # Per-industry processing
    # ------------------------------------------------------------------

    async def _process_industry(
        self,
        industry: Industry,
        crawler: PageCrawler,
        resolver: WebsiteResolver,
    ) -> None:
        """Full pipeline for one industry: resolve -> crawl -> extract -> validate -> save."""
        industry_id = industry.id
        name = industry.industry_name
        start_ts = time.monotonic()

        logger.info("[%s] Processing started", name)
        await self._db.update_status(industry_id, CrawlStatus.RESOLVING)

        # ── Step 1: Resolve website ──────────────────────────────────
        resolution = await resolver.resolve(
            industry_name=name,
            city=industry.city,
            state=industry.state,
            existing_url=industry.raw_website_input or industry.website,
        )

        if not resolution:
            logger.warning("[%s] Could not resolve website", name)
            await self._db.update_status(
                industry_id,
                CrawlStatus.NO_WEBSITE,
                error_message="Website could not be resolved",
                increment_retry=True,
            )
            async with self._lock:
                self._stats.failed += 1
                self._stats.processed += 1
            return

        base_url = resolution.resolved_url
        industry.website = base_url

        async with self._lock:
            self._stats.websites_resolved += 1
            self._active_urls.append(base_url)

        await self._db.update_status(industry_id, CrawlStatus.CRAWLING)

        # ── Step 2: Crawl pages ──────────────────────────────────────
        try:
            crawl_result = await crawler.crawl_industry(industry_id, name, base_url)
        except Exception as exc:
            await self._handle_crawl_failure(industry, exc, start_ts)
            return
        finally:
            async with self._lock:
                if base_url in self._active_urls:
                    self._active_urls.remove(base_url)

        if not crawl_result.success:
            await self._handle_crawl_failure(
                industry,
                Exception(crawl_result.error or "Unknown crawl failure"),
                start_ts,
            )
            return

        # ── Step 3: Extract contacts ─────────────────────────────────
        raw_contacts = self._extractor.extract(crawl_result)

        # ── Step 4: Validate contacts ────────────────────────────────
        valid_contacts, _ = self._validator.validate_contacts(raw_contacts)

        # ── Step 5: Select best contacts ────────────────────────────
        domain = urlparse(base_url).netloc.lstrip("www.")
        best = self._validator.select_best_contacts(valid_contacts, domain)

        # ── Step 6: Save to DB ──────────────────────────────────────
        industry.email = best.get("email")
        industry.phone = best.get("phone")
        industry.exec_email = best.get("exec_email")
        industry.hr_email = best.get("hr_email")
        industry.crawl_status = CrawlStatus.DONE
        industry.error_message = None

        await self._db.upsert_industry(industry)
        await self._db.update_status(industry_id, CrawlStatus.DONE)

        # ── Step 7: Log crawl event ──────────────────────────────────
        duration_ms = int((time.monotonic() - start_ts) * 1000)
        await self._db.log_crawl(
            CrawlLogEntry(
                industry_id=industry_id,
                industry_name=name,
                url=base_url,
                status="done",
                duration_ms=duration_ms,
            )
        )

        # ── Step 8: Update stats ─────────────────────────────────────
        async with self._lock:
            self._stats.successful += 1
            self._stats.processed += 1
            if industry.email or industry.exec_email or industry.hr_email:
                self._stats.emails_found += 1
            if industry.phone:
                self._stats.phones_found += 1
            pending = self._queue.qsize()
            self._stats.pending = pending
            elapsed = time.monotonic() - (
                self._stats.start_time.timestamp()
                if self._stats.start_time else time.monotonic()
            )
            self._stats.elapsed_seconds = elapsed
            if self._stats.processed > 0 and pending > 0:
                rate = self._stats.processed / max(elapsed, 1)
                self._stats.eta_seconds = pending / rate

        logger.info(
            "[%s] Done in %.1fs — email=%s phone=%s",
            name,
            duration_ms / 1000,
            industry.email or "—",
            industry.phone or "—",
        )

    # ------------------------------------------------------------------
    # Failure handler
    # ------------------------------------------------------------------

    async def _handle_crawl_failure(
        self, industry: Industry, exc: Exception, start_ts: float
    ) -> None:
        """Handle a crawl failure: update DB, log, update stats."""
        duration_ms = int((time.monotonic() - start_ts) * 1000)
        err_msg = str(exc)[:500]
        max_retries = self._settings.retries.max_attempts

        new_retry_count = (industry.retry_count or 0) + 1
        new_status = (
            CrawlStatus.FAILED if new_retry_count >= max_retries else CrawlStatus.PENDING
        )

        await self._db.update_status(
            industry.id,
            new_status,
            error_message=err_msg,
            increment_retry=True,
        )
        await self._db.log_crawl(
            CrawlLogEntry(
                industry_id=industry.id,
                industry_name=industry.industry_name,
                url=industry.website or "unknown",
                status="failed",
                error=err_msg,
                duration_ms=duration_ms,
            )
        )

        if new_retry_count < max_retries:
            retry_logger.warning(
                "Retry %d/%d for '%s': %s",
                new_retry_count,
                max_retries,
                industry.industry_name,
                err_msg[:100],
            )
            industry.retry_count = new_retry_count
            await self._queue.put(industry)
        else:
            error_logger.error(
                "Max retries reached for '%s': %s",
                industry.industry_name,
                err_msg[:100],
            )
            async with self._lock:
                self._stats.failed += 1
                self._stats.processed += 1

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _load_pending(self) -> list[Industry]:
        """Return industries that still need processing."""
        return await self._db.get_pending_industries(
            max_retries=self._settings.retries.max_attempts
        )

    async def _count_total(self) -> int:
        """Return total industry count from stats."""
        stats = await self._db.get_statistics()
        return sum(stats.values())


# Sentinel object for signalling workers to stop
_SENTINEL = object()
