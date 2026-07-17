"""
Sitemap parser for the School Contact Discovery System.

Reads sitemap.xml to discover additional URLs relevant to contact pages,
helping the crawler find information without brute-force path guessing.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx

from config import get_settings

logger = logging.getLogger("crawl")

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_CONTACT_KEYWORDS = re.compile(
    r"(contact|about|admission|administration|staff|directory|principal|office)",
    re.IGNORECASE,
)


class SitemapParser:
    """
    Lightweight sitemap.xml fetcher and URL filter.

    Discovers contact-relevant page URLs from school sitemaps.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client: Optional[httpx.AsyncClient] = None
        self._timeout = settings.timeouts.request_seconds

    async def __aenter__(self) -> "SitemapParser":
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=self._timeout,
            verify=False,  # permissive for school sites
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client:
            await self._client.aclose()

    async def get_contact_urls(self, base_url: str, max_urls: int = 20) -> list[str]:
        """
        Fetch sitemap.xml and return contact-relevant URLs.

        Args:
            base_url: Root URL of the school website.
            max_urls: Maximum number of URLs to return.

        Returns:
            List of relevant page URLs discovered from the sitemap.
        """
        parsed = urlparse(base_url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        sitemap_url = urljoin(root, "/sitemap.xml")

        try:
            urls = await self._fetch_sitemap(sitemap_url, depth=0)
        except Exception as exc:
            logger.debug("Sitemap fetch failed for %s: %s", sitemap_url, exc)
            return []

        contact_urls = [u for u in urls if _CONTACT_KEYWORDS.search(u)]
        return contact_urls[:max_urls]

    async def _fetch_sitemap(self, url: str, depth: int) -> list[str]:
        """
        Recursively fetch a sitemap or sitemap index.

        Follows sitemap index files up to depth 2.
        """
        if depth > 2 or not self._client:
            return []

        try:
            resp = await self._client.get(url, timeout=self._timeout)
            if resp.status_code != 200:
                return []
            content = resp.text
        except Exception:
            return []

        return await self._parse_sitemap_xml(content, depth)

    async def _parse_sitemap_xml(self, content: str, depth: int) -> list[str]:
        """Parse sitemap XML and extract URLs or nested sitemaps."""
        urls: list[str] = []
        try:
            root = ET.fromstring(content)
            tag = root.tag.lower()

            if "sitemapindex" in tag:
                # Sitemap index — recurse into each sitemap
                nested: list[str] = []
                for sitemap_el in root.findall("sm:sitemap", _SITEMAP_NS):
                    loc = sitemap_el.findtext("sm:loc", namespaces=_SITEMAP_NS)
                    if loc:
                        nested += await self._fetch_sitemap(loc.strip(), depth + 1)
                urls = nested

            else:
                # Regular sitemap
                for url_el in root.findall("sm:url", _SITEMAP_NS):
                    loc = url_el.findtext("sm:loc", namespaces=_SITEMAP_NS)
                    if loc:
                        urls.append(loc.strip())

        except ET.ParseError:
            # Try regex fallback
            urls = re.findall(r"<loc>(https?://[^<]+)</loc>", content)

        return urls
