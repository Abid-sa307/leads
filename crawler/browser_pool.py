"""
Playwright browser pool for the School Contact Discovery System.

Manages a fixed-size pool of browser contexts shared across async workers.
Each worker checks out a context, uses it, and returns it to the pool.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    async_playwright,
)

from config import get_settings

logger = logging.getLogger("crawl")


class BrowserPool:
    """
    A fixed-size pool of Playwright BrowserContext objects.

    Each context is isolated (separate cookies/storage) but shares the
    underlying browser process to conserve RAM.

    Usage:
        async with BrowserPool(size=5) as pool:
            async with pool.acquire() as context:
                page = await context.new_page()
                ...
    """

    def __init__(self, size: Optional[int] = None) -> None:
        settings = get_settings()
        self._size = size or settings.concurrency.browser_pool_size
        self._settings = settings
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._pool: asyncio.Queue[BrowserContext] = asyncio.Queue()
        self._all_contexts: list[BrowserContext] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch the browser and pre-create all contexts."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._settings.crawler.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
                "--metrics-recording-only",
                "--mute-audio",
                "--no-first-run",
            ],
        )

        for _ in range(self._size):
            ctx = await self._make_context()
            self._all_contexts.append(ctx)
            await self._pool.put(ctx)

        logger.info("BrowserPool started with %d contexts", self._size)

    async def stop(self) -> None:
        """Close all contexts and the browser."""
        for ctx in self._all_contexts:
            try:
                await ctx.close()
            except Exception:
                pass

        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

        logger.info("BrowserPool stopped")

    async def __aenter__(self) -> "BrowserPool":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Context acquisition
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[BrowserContext, None]:
        """
        Check out a BrowserContext from the pool.

        Blocks until one is available. Automatically returns the context
        to the pool (or replaces it if broken) on exit.

        Yields:
            A Playwright BrowserContext.
        """
        context = await self._pool.get()
        try:
            yield context
        except Exception:
            # Replace the context if something went wrong
            try:
                await context.close()
            except Exception:
                pass
            try:
                context = await self._make_context()
                self._all_contexts.append(context)
            except Exception as exc:
                logger.error("Failed to replace broken browser context: %s", exc)
                raise
        finally:
            await self._pool.put(context)

    # ------------------------------------------------------------------
    # Context factory
    # ------------------------------------------------------------------

    async def _make_context(self) -> BrowserContext:
        """Create a new browser context with shared settings."""
        assert self._browser
        ctx = await self._browser.new_context(
            user_agent=self._settings.crawler.user_agent,
            locale=self._settings.crawler.accept_language.split(",")[0],
            ignore_https_errors=self._settings.crawler.ssl_permissive,
            java_script_enabled=True,
            bypass_csp=False,
            extra_http_headers={
                "Accept-Language": self._settings.crawler.accept_language,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            viewport={"width": 1280, "height": 800},
        )
        # Block unnecessary resources for speed
        await ctx.route(
            "**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,mp4,mp3,webp,avif}",
            lambda route: route.abort(),
        )
        return ctx

    @property
    def size(self) -> int:
        """Number of contexts in the pool."""
        return self._size
