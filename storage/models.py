"""
Data models for the Industry Contact Discovery System.

Defines Pydantic models for validation/serialization and the SQLite schema.
"""

from __future__ import annotations

import re
from datetime import datetime, UTC
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CrawlStatus(str, Enum):
    """Lifecycle states for an industry record."""

    PENDING = "pending"          # Not yet processed
    RESOLVING = "resolving"      # Attempting to find official website
    CRAWLING = "crawling"        # Actively being crawled
    DONE = "done"                # Successfully crawled and data extracted
    FAILED = "failed"            # All retries exhausted
    SKIPPED = "skipped"          # Intentionally skipped (duplicate / invalid input)
    NO_WEBSITE = "no_website"    # Could not resolve official website


class EmailType(str, Enum):
    """Classification of discovered email addresses."""

    GENERAL = "general"
    EXEC = "exec"
    HR = "hr"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Core Pydantic models
# ---------------------------------------------------------------------------


class Industry(BaseModel):
    """
    Represents an industry record throughout the discovery pipeline.

    Used for both in-memory processing and SQLite persistence.
    """

    id: Optional[int] = Field(None, description="Auto-assigned SQLite row ID")
    industry_name: str = Field(..., min_length=1, description="Official company / industry name")
    city: Optional[str] = Field(None, description="City where industry is located")
    state: Optional[str] = Field(None, description="State / province / region")
    country: str = Field("US", description="ISO 3166-1 alpha-2 country code")
    website: Optional[str] = Field(None, description="Official industry website URL")
    email: Optional[str] = Field(None, description="Primary contact email")
    phone: Optional[str] = Field(None, description="Primary contact phone")
    exec_email: Optional[str] = Field(None, description="Executive email if public")
    hr_email: Optional[str] = Field(None, description="HR / careers email if public")
    source: Optional[str] = Field(None, description="Source file or import batch")
    crawl_status: CrawlStatus = Field(CrawlStatus.PENDING, description="Current pipeline state")
    retry_count: int = Field(0, ge=0, description="Number of crawl attempts made")
    error_message: Optional[str] = Field(None, description="Last error encountered")
    raw_website_input: Optional[str] = Field(None, description="Original website from import")
    last_updated: Optional[datetime] = Field(None, description="Timestamp of last update")
    created_at: Optional[datetime] = Field(None, description="Timestamp of record creation")

    @field_validator("industry_name")
    @classmethod
    def clean_industry_name(cls, v: str) -> str:
        """Strip and normalize industry name."""
        return v.strip()

    @field_validator("website", "raw_website_input")
    @classmethod
    def normalize_url(cls, v: Optional[str]) -> Optional[str]:
        """Ensure URL starts with a scheme."""
        if not v:
            return None
        v = v.strip()
        if v and not re.match(r"^https?://", v, re.IGNORECASE):
            v = "https://" + v
        return v

    @field_validator("email", "exec_email", "hr_email")
    @classmethod
    def clean_email(cls, v: Optional[str]) -> Optional[str]:
        """Lowercase and strip email."""
        if not v:
            return None
        return v.strip().lower()

    @field_validator("country")
    @classmethod
    def normalize_country(cls, v: str) -> str:
        """Uppercase country code."""
        return v.strip().upper() if v else "US"

    model_config = {"from_attributes": True}


class ExtractedContact(BaseModel):
    """
    A single contact item extracted from a crawled page.

    Used internally during the extraction pipeline before being
    merged into the Industry record.
    """

    value: str = Field(..., description="The raw extracted value (email or phone)")
    contact_type: str = Field(..., description="'email' or 'phone'")
    email_type: Optional[EmailType] = Field(None, description="Classification for emails")
    source_url: str = Field(..., description="Page URL where this was found")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Extraction confidence score")
    raw: str = Field(..., description="Original unprocessed value from page")


class WebsiteResolution(BaseModel):
    """
    Cached result of resolving an industry name -> official website URL.
    """

    industry_name: str
    city: Optional[str] = None
    state: Optional[str] = None
    resolved_url: str
    resolution_method: str = Field(..., description="'existing', 'cache', 'search'")
    verified: bool = False
    resolved_at: Optional[datetime] = None


class CrawlLogEntry(BaseModel):
    """
    A single crawl event written to the crawl log table.
    """

    industry_id: int
    industry_name: str
    url: str
    status: str
    http_status: Optional[int] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Statistics(BaseModel):
    """
    Aggregate run statistics snapshot.
    """

    total_industries: int = 0
    processed: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    pending: int = 0
    emails_found: int = 0
    phones_found: int = 0
    websites_resolved: int = 0
    start_time: Optional[datetime] = None
    elapsed_seconds: float = 0.0
    eta_seconds: Optional[float] = None
    current_urls: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# SQLite Schema DDL
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS industries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    industry_name       TEXT    NOT NULL,
    city                TEXT,
    state               TEXT,
    country             TEXT    NOT NULL DEFAULT 'US',
    website             TEXT,
    email               TEXT,
    phone               TEXT,
    exec_email          TEXT,
    hr_email            TEXT,
    source              TEXT,
    crawl_status        TEXT    NOT NULL DEFAULT 'pending',
    retry_count         INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    raw_website_input   TEXT,
    last_updated        TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(industry_name, city, state)
);

CREATE TABLE IF NOT EXISTS website_cache (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    industry_name       TEXT    NOT NULL,
    city                TEXT,
    state               TEXT,
    resolved_url        TEXT    NOT NULL,
    resolution_method   TEXT    NOT NULL,
    verified            INTEGER NOT NULL DEFAULT 0,
    resolved_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(industry_name, city, state)
);

CREATE TABLE IF NOT EXISTS crawl_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    industry_id   INTEGER NOT NULL,
    industry_name TEXT    NOT NULL,
    url           TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    http_status   INTEGER,
    duration_ms   INTEGER,
    error         TEXT,
    timestamp     TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (industry_id) REFERENCES industries(id)
);

CREATE INDEX IF NOT EXISTS idx_industries_status ON industries(crawl_status);
CREATE INDEX IF NOT EXISTS idx_industries_name    ON industries(industry_name);
CREATE INDEX IF NOT EXISTS idx_crawl_log_industry ON crawl_log(industry_id);
"""

SCHEMA_VERSION = 1
