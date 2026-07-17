"""
Page crawler for the Industry Contact Discovery System.

Visits a prioritised list of pages on an industry's website using Playwright,
collects raw HTML from each page, and handles JS rendering, redirects,
SSL errors, and retries.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import BrowserContext, Error as PlaywrightError, TimeoutError

from config import get_settings
from crawler.browser_pool import BrowserPool

logger = logging.getLogger("crawl")


@dataclass
class CrawlResult:
    """Result of crawling a single page."""

    url: str
    html: str
    final_url: str
    status: int = 200
    error: Optional[str] = None
    duration_ms: int = 0


@dataclass
class IndustryCrawlResult:
    """Aggregated results from crawling all pages of one industry."""

    industry_id: int
    industry_name: str
    base_url: str
    pages: list[CrawlResult] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None


class PageCrawler:
    """
    Crawls a set of prioritised pages for a single industry website.

    Shares a BrowserPool with other workers and checks out a context
    for each industry crawl.
    """

    # Pages to visit in priority order
    TARGET_PATHS = [
        "/",
        "/contact",
        "/contact-us",
        "/contact_us",
        "/contactus",
        "/about",
        "/about-us",
        "/careers",
        "/jobs",
        "/team",
        "/staff",
        "/directory",
    ]

    def __init__(self, browser_pool: BrowserPool) -> None:
        self._pool = browser_pool
        self._settings = get_settings()
        from extractors.contact_extractor import ContactExtractor
        from validators.contact_validator import ContactValidator
        self._extractor = ContactExtractor()
        self._validator = ContactValidator()

    async def crawl_industry(
        self,
        industry_id: int,
        industry_name: str,
        base_url: str,
    ) -> IndustryCrawlResult:
        """
        Crawl all target pages of an industry website.

        Args:
            industry_id: DB row ID for the industry.
            industry_name: Human-readable industry name (for logging).
            base_url: The verified base URL of the industry website.

        Returns:
            IndustryCrawlResult with HTML content from each reachable page.
        """
        result = IndustryCrawlResult(
            industry_id=industry_id,
            industry_name=industry_name,
            base_url=base_url,
        )

        # Try to get sitemap URLs first for additional page hints
        sitemap_extras: list[str] = []
        try:
            from extractors.sitemap_parser import SitemapParser
            async with SitemapParser() as parser:
                sitemap_extras = await parser.get_contact_urls(base_url)
        except Exception:
            pass

        pages_to_visit = self._build_page_list(base_url, sitemap_extras)
        visited: set[str] = set()
        crawled_count = 0
        max_pages = self._settings.crawler.max_pages_per_industry

        async with self._pool.acquire() as context:
            for url in pages_to_visit:
                if crawled_count >= max_pages:
                    break
                if url in visited:
                    continue
                visited.add(url)

                page_result = await self._visit_page(context, url)
                if page_result:
                    result.pages.append(page_result)
                    crawled_count += 1
                    if page_result.error:
                        logger.debug(
                            "[%s] Page error %s: %s", industry_name, url, page_result.error
                        )
                    else:
                        # Early Stop Check: if we already found email and phone, stop crawling additional pages
                        try:
                            raw_contacts = self._extractor.extract(result)
                            valid_contacts, _ = self._validator.validate_contacts(raw_contacts)
                            has_email = any(c.contact_type == "email" for c in valid_contacts)
                            has_phone = any(c.contact_type == "phone" for c in valid_contacts)
                            if has_email and has_phone:
                                logger.info("[%s] Early stop triggered: found both email and phone", industry_name)
                                break
                        except Exception as exc:
                            logger.debug("[%s] Early stop check failed: %s", industry_name, exc)

        result.success = len(result.pages) > 0 and any(
            not p.error for p in result.pages
        )
        if not result.success:
            result.error = "No pages successfully crawled"

        logger.info(
            "[%s] Crawled %d pages from %s (success=%s)",
            industry_name,
            len(result.pages),
            base_url,
            result.success,
        )
        return result

    # ------------------------------------------------------------------
    # Page visitor
    # ------------------------------------------------------------------

    async def _visit_page(
        self, context: BrowserContext, url: str
    ) -> Optional[CrawlResult]:
        """
        Visit a single page and return its HTML content.

        Retries up to max_attempts times with exponential backoff.
        """
        settings = self._settings
        max_attempts = settings.retries.max_attempts
        backoff = settings.retries.backoff_factor
        timeout_ms = settings.timeouts.page_load_seconds * 1000

        for attempt in range(1, max_attempts + 1):
            page = None
            start = time.monotonic()
            try:
                page = await context.new_page()

                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )

                html = await page.content()
                
                # Conditional Wait Optimization: check if page already has contact info.
                # If it doesn't, wait up to 1.0 second for JS hydration.
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "lxml")
                base_domain = urlparse(url).netloc.lstrip("www.")
                temp_res = CrawlResult(url=url, html=html, final_url=page.url)
                contacts = self._extractor._extract_from_page(soup, temp_res, base_domain)
                valid_contacts, _ = self._validator.validate_contacts(contacts)
                
                if not valid_contacts:
                    await page.wait_for_timeout(1000)
                    html = await page.content()

                final_url = page.url
                status = response.status if response else 200
                duration_ms = int((time.monotonic() - start) * 1000)

                await page.close()
                return CrawlResult(
                    url=url,
                    html=html,
                    final_url=final_url,
                    status=status,
                    duration_ms=duration_ms,
                )

            except TimeoutError:
                logger.debug("Timeout (attempt %d/%d): %s", attempt, max_attempts, url)
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if attempt < max_attempts:
                    await asyncio.sleep(backoff ** attempt)

            except PlaywrightError as exc:
                err_str = str(exc)
                # Non-retryable errors
                if any(
                    msg in err_str
                    for msg in ("net::ERR_NAME_NOT_RESOLVED", "net::ERR_CONNECTION_REFUSED")
                ):
                    logger.debug("Non-retryable error for %s: %s", url, err_str[:100])
                    if page:
                        try:
                            await page.close()
                        except Exception:
                            pass
                    return CrawlResult(
                        url=url,
                        html="",
                        final_url=url,
                        status=0,
                        error=err_str[:200],
                        duration_ms=int((time.monotonic() - start) * 1000),
                    )

                logger.debug(
                    "Playwright error (attempt %d/%d) %s: %s",
                    attempt, max_attempts, url, err_str[:100],
                )
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if attempt < max_attempts:
                    await asyncio.sleep(backoff ** attempt)

            except Exception as exc:
                logger.debug("Unexpected error visiting %s: %s", url, exc)
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
                break

        duration_ms = int((time.monotonic() - start) * 1000)
        return CrawlResult(
            url=url,
            html="",
            final_url=url,
            status=0,
            error="All retry attempts exhausted",
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    def _build_page_list(self, base_url: str, sitemap_extras: list[str]) -> list[str]:
        """
        Build the ordered list of URLs to visit.

        Combines default paths with sitemap-discovered contact-relevant URLs.
        """
        parsed = urlparse(base_url)
        scheme_host = f"{parsed.scheme}://{parsed.netloc}"

        urls: list[str] = []
        for path in self._settings.crawler.pages_to_visit:
            urls.append(urljoin(scheme_host, path))

        # Add sitemap extras that look contact-related
        contact_keywords = {"contact", "about", "admin", "staff", "directory", "career", "job", "team"}
        for extra in sitemap_extras:
            lower = extra.lower()
            if any(kw in lower for kw in contact_keywords):
                full = extra if extra.startswith("http") else urljoin(scheme_host, extra)
                if full not in urls:
                    urls.append(full)

        return urls
