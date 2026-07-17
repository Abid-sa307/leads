"""
Website resolver for the Industry Contact Discovery System.

Resolves an official industry website URL using:
1. Existing URL in the record (verify reachable)
2. SQLite cache lookup
3. DuckDuckGo Instant Answer search
4. Heuristic domain construction fallback
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from typing import Optional

import httpx

from config import get_settings
from storage.models import WebsiteResolution

logger = logging.getLogger("crawl")

# Common industry TLDs in priority order
_INDUSTRY_TLDS = [".com", ".co", ".io", ".org", ".net", ".biz", ".us"]

# DuckDuckGo Instant Answer API
_DDG_API = "https://api.duckduckgo.com/"


class WebsiteResolver:
    """
    Resolves an official website from an industry name + location.

    Maintains a domain-level rate limiter to avoid hammering search engines.
    """

    def __init__(self, db: Optional[object] = None) -> None:
        """
        Args:
            db: Optional Database instance for cache lookups/writes.
        """
        self._db = db
        self._settings = get_settings()
        self._client: Optional[httpx.AsyncClient] = None
        self._domain_last_hit: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "WebsiteResolver":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                self._settings.timeouts.request_seconds,
                connect=self._settings.timeouts.dns_seconds,
            ),
            follow_redirects=True,
            headers={
                "User-Agent": self._settings.crawler.user_agent,
                "Accept-Language": self._settings.crawler.accept_language,
            },
            verify=not self._settings.crawler.ssl_permissive,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def resolve(
        self,
        industry_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
        existing_url: Optional[str] = None,
    ) -> Optional[WebsiteResolution]:
        """
        Resolve the official website for an industry.

        Resolution order:
        1. Verify existing URL if provided
        2. Cache lookup
        3. DuckDuckGo search
        4. Heuristic construction

        Args:
            industry_name: Industry name.
            city: Optional city.
            state: Optional state.
            existing_url: URL already known from the input data.

        Returns:
            WebsiteResolution if found, None otherwise.
        """
        # Step 1: verify existing URL
        if existing_url:
            url = self._normalise_url(existing_url)
            if url and await self._verify_url(url):
                resolution = WebsiteResolution(
                    industry_name=industry_name,
                    city=city,
                    state=state,
                    resolved_url=url,
                    resolution_method="existing",
                    verified=True,
                )
                await self._save_cache(resolution)
                return resolution
            logger.debug("Existing URL unreachable: %s", existing_url)

        # Step 2: cache lookup
        if self._db and self._settings.resolver.use_cache:
            cached = await self._db.get_cached_website(industry_name, city, state)
            if cached:
                logger.debug("Cache hit for '%s': %s", industry_name, cached)
                return WebsiteResolution(
                    industry_name=industry_name,
                    city=city,
                    state=state,
                    resolved_url=cached,
                    resolution_method="cache",
                    verified=True,
                )

        # Step 3: DuckDuckGo search
        url = await self._search_duckduckgo(industry_name, city, state)
        if url:
            resolution = WebsiteResolution(
                industry_name=industry_name,
                city=city,
                state=state,
                resolved_url=url,
                resolution_method="search",
                verified=True,
            )
            await self._save_cache(resolution)
            return resolution

        # Step 4: heuristic fallback
        url = await self._heuristic_resolve(industry_name, city, state)
        if url:
            resolution = WebsiteResolution(
                industry_name=industry_name,
                city=city,
                state=state,
                resolved_url=url,
                resolution_method="heuristic",
                verified=True,
            )
            await self._save_cache(resolution)
            return resolution

        logger.warning("Could not resolve website for '%s'", industry_name)
        return None

    # ------------------------------------------------------------------
    # DuckDuckGo search
    # ------------------------------------------------------------------

    async def _search_duckduckgo(
        self,
        industry_name: str,
        city: Optional[str],
        state: Optional[str],
    ) -> Optional[str]:
        """Use DuckDuckGo Instant Answer API to find official industry site."""
        if not self._client:
            return None

        query_parts = [industry_name, "official website"]
        if city:
            query_parts.append(city)
        if state:
            query_parts.append(state)
        query = " ".join(query_parts)

        params = {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }

        await self._rate_limit("duckduckgo.com")

        try:
            resp = await self._client.get(_DDG_API, params=params)
            if resp.status_code != 200:
                return None

            data = resp.json()

            # AbstractURL is the most reliable field
            abstract_url = data.get("AbstractURL", "")
            if abstract_url and await self._verify_url(abstract_url):
                return self._normalise_url(abstract_url)

            # RelatedTopics first result
            topics = data.get("RelatedTopics", [])
            for topic in topics[:3]:
                first_url = topic.get("FirstURL", "")
                if first_url and await self._verify_url(first_url):
                    return self._normalise_url(first_url)

        except Exception as exc:
            logger.debug("DuckDuckGo search failed for '%s': %s", industry_name, exc)

        # Fallback: web search via DuckDuckGo HTML (scrape top result)
        return await self._scrape_ddg_web(query)

    async def _scrape_ddg_web(self, query: str) -> Optional[str]:
        """Scrape the first organic result from DuckDuckGo web search."""
        if not self._client:
            return None
        await self._rate_limit("duckduckgo.com")
        try:
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            resp = await self._client.get(url)
            if resp.status_code != 200:
                return None

            # Extract first result link
            pattern = r'href="(https?://[^"]+)"'
            matches = re.findall(pattern, resp.text)
            for match in matches[:5]:
                parsed = urllib.parse.urlparse(match)
                # Skip DDG internal links
                if "duckduckgo" in parsed.netloc:
                    continue
                if await self._verify_url(match):
                    return self._normalise_url(match)
        except Exception as exc:
            logger.debug("DDG web scrape failed: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Heuristic resolution
    # ------------------------------------------------------------------

    async def _heuristic_resolve(
        self,
        industry_name: str,
        city: Optional[str],
        state: Optional[str],
    ) -> Optional[str]:
        """
        Try common URL patterns for the industry name.

        e.g., 'Lincoln Industries' -> lincoln.com, etc.
        """
        slug = self._slugify(industry_name)
        short = self._short_slug(industry_name)

        candidates: list[str] = []
        for tld in _INDUSTRY_TLDS:
            candidates += [
                f"https://www.{slug}{tld}",
                f"https://{slug}{tld}",
                f"https://www.{short}{tld}",
            ]
            if state:
                state_slug = state.lower().replace(" ", "")
                candidates.append(f"https://www.{short}.{state_slug}{tld}")

        for candidate in candidates:
            if await self._verify_url(candidate):
                logger.debug("Heuristic resolved '%s' -> %s", industry_name, candidate)
                return candidate

        return None

    # ------------------------------------------------------------------
    # URL utilities
    # ------------------------------------------------------------------

    async def _verify_url(self, url: str) -> bool:
        """Check that a URL returns a 2xx/3xx response."""
        if not self._client or not url:
            return False
        try:
            normalised = self._normalise_url(url)
            if not normalised:
                return False
            await self._rate_limit(urllib.parse.urlparse(normalised).netloc)
            resp = await self._client.head(
                normalised,
                timeout=self._settings.timeouts.request_seconds,
            )
            return resp.status_code < 400
        except Exception:
            return False

    def _normalise_url(self, url: str) -> Optional[str]:
        """Add scheme if missing and normalise."""
        url = url.strip()
        if not url:
            return None
        if not re.match(r"^https?://", url, re.IGNORECASE):
            url = "https://" + url
        return url

    def _slugify(self, name: str) -> str:
        """Convert industry name to URL-safe slug."""
        slug = name.lower()
        slug = re.sub(r"\b(corp|corporation|inc|incorporated|llc|ltd|limited|co|company|industries|industry|group|solutions|services)\b", "", slug)
        slug = re.sub(r"[^a-z0-9\s]", "", slug)
        slug = re.sub(r"\s+", "", slug.strip())
        return slug[:30]

    def _short_slug(self, name: str) -> str:
        """Build an abbreviated slug from initials or first word."""
        words = re.sub(r"[^a-zA-Z\s]", "", name).split()
        stop_words = {"of", "the", "and", "at", "inc", "co", "llc", "ltd", "corp", "company", "group", "industries", "solutions", "services"}
        meaningful = [w for w in words if w.lower() not in stop_words]
        if len(meaningful) >= 2:
            return "".join(w[0].lower() for w in meaningful[:4])
        return meaningful[0].lower()[:10] if meaningful else words[0].lower()[:10]

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _rate_limit(self, domain: str) -> None:
        """Enforce per-domain rate limiting."""
        import time
        async with self._lock:
            last = self._domain_last_hit.get(domain, 0)
            min_gap = 1.0 / self._settings.concurrency.requests_per_second_per_domain
            wait = min_gap - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._domain_last_hit[domain] = time.monotonic()

    # ------------------------------------------------------------------
    # Cache helper
    # ------------------------------------------------------------------

    async def _save_cache(self, resolution: WebsiteResolution) -> None:
        """Write resolution to DB cache if DB is available."""
        if self._db and self._settings.resolver.use_cache:
            try:
                await self._db.cache_website(resolution)
            except Exception as exc:
                logger.debug("Failed to write website cache: %s", exc)
