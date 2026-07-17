"""Crawler package."""
from .browser_pool import BrowserPool
from .page_crawler import CrawlResult, PageCrawler, IndustryCrawlResult
from .website_resolver import WebsiteResolver

__all__ = [
    "BrowserPool",
    "PageCrawler",
    "WebsiteResolver",
    "CrawlResult",
    "IndustryCrawlResult",
]
