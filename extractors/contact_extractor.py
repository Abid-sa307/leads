"""
Contact extractor for the Industry Contact Discovery System.

Extracts publicly listed corporate email addresses and phone numbers
from crawled HTML pages using BeautifulSoup + regex.

Classifier logic:
  - exec email: context contains 'ceo', 'president', 'founder', 'owner', 'director', 'partner', 'principal'
  - hr email: context contains 'hr', 'careers', 'jobs', 'hiring', 'recruitment', 'apply'
  - general: all other corporate emails
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

import phonenumbers
from bs4 import BeautifulSoup

from config import get_settings
from crawler.page_crawler import CrawlResult, IndustryCrawlResult
from storage.models import EmailType, ExtractedContact

logger = logging.getLogger("crawl")

# ---------------------------------------------------------------------------
# Email patterns
# ---------------------------------------------------------------------------

_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# Noise / personal email domains to deprioritise
_PERSONAL_DOMAINS = frozenset(
    {
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
        "aol.com", "icloud.com", "live.com", "msn.com",
        "protonmail.com", "mail.com", "yandex.com",
    }
)

# Email type keyword hints
_EXEC_KEYWORDS = re.compile(
    r"ceo|president|founder|owner|director|partner|principal|executive|management|chief",
    re.IGNORECASE,
)
_HR_KEYWORDS = re.compile(
    r"hr|careers?|jobs?|hiring|recruiting|recruitment|apply|employment",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Phone patterns
# ---------------------------------------------------------------------------

# Broad pattern to find candidate phone strings before phonenumbers validation
_PHONE_CANDIDATE = re.compile(
    r"(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?:\s*(?:ext|x|ext\.)\s*\d{1,5})?)",
    re.IGNORECASE,
)


class ContactExtractor:
    """
    Extracts emails and phone numbers from crawled industry pages.

    Classifies emails as general / exec / hr based on
    surrounding text context.
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    def extract(self, crawl_result: IndustryCrawlResult) -> list[ExtractedContact]:
        """
        Extract all contacts from an industry's crawl result.

        Args:
            crawl_result: Aggregated crawl results for one industry.

        Returns:
            Deduplicated list of ExtractedContact objects.
        """
        all_contacts: list[ExtractedContact] = []
        base_domain = self._get_domain(crawl_result.base_url)

        for page in crawl_result.pages:
            if not page.html or page.error:
                continue
            soup = BeautifulSoup(page.html, "lxml")
            contacts = self._extract_from_page(soup, page, base_domain)
            all_contacts.extend(contacts)

        return self._deduplicate(all_contacts)

    # ------------------------------------------------------------------
    # Per-page extraction
    # ------------------------------------------------------------------

    def _extract_from_page(
        self,
        soup: BeautifulSoup,
        page: CrawlResult,
        base_domain: str,
    ) -> list[ExtractedContact]:
        """Extract emails and phones from a single parsed page."""
        contacts: list[ExtractedContact] = []

        contacts.extend(self._extract_emails(soup, page, base_domain))
        contacts.extend(self._extract_phones(soup, page))

        return contacts

    # ------------------------------------------------------------------
    # Email extraction
    # ------------------------------------------------------------------

    def _extract_emails(
        self,
        soup: BeautifulSoup,
        page: CrawlResult,
        base_domain: str,
    ) -> list[ExtractedContact]:
        """Extract emails via mailto: links and raw text."""
        emails: dict[str, ExtractedContact] = {}

        # 1. Extract from mailto: anchors (highest confidence)
        for anchor in soup.find_all("a", href=True):
            href: str = anchor["href"]
            if not href.lower().startswith("mailto:"):
                continue
            raw_email = href[7:].split("?")[0].strip()
            email = self._normalise_email(raw_email)
            if not email:
                continue

            context = self._get_context(anchor)
            email_type = self._classify_email(context)
            confidence = self._email_confidence(email, base_domain, context)

            if email not in emails or confidence > emails[email].confidence:
                emails[email] = ExtractedContact(
                    value=email,
                    contact_type="email",
                    email_type=email_type,
                    source_url=page.url,
                    confidence=confidence,
                    raw=raw_email,
                )

        # 2. Extract from raw page text (lower confidence, avoids personal emails)
        full_text = soup.get_text(separator=" ")
        for match in _EMAIL_PATTERN.finditer(full_text):
            raw_email = match.group(0)
            email = self._normalise_email(raw_email)
            if not email or email in emails:
                continue

            context = self._get_surrounding_text(full_text, match.start(), window=150)
            email_type = self._classify_email(context)
            confidence = self._email_confidence(email, base_domain, context)

            if confidence < self._settings.extraction.min_email_confidence:
                continue

            emails[email] = ExtractedContact(
                value=email,
                contact_type="email",
                email_type=email_type,
                source_url=page.url,
                confidence=confidence,
                raw=raw_email,
            )

        return list(emails.values())

    # ------------------------------------------------------------------
    # Phone extraction
    # ------------------------------------------------------------------

    def _extract_phones(
        self,
        soup: BeautifulSoup,
        page: CrawlResult,
    ) -> list[ExtractedContact]:
        """Extract phone numbers using phonenumbers library for validation."""
        phones: dict[str, ExtractedContact] = {}
        region = self._settings.extraction.phone_default_region

        # 1. tel: links (highest confidence)
        for anchor in soup.find_all("a", href=True):
            href: str = anchor["href"]
            if not href.lower().startswith("tel:"):
                continue
            raw_phone = href[4:].strip()
            try:
                parsed = phonenumbers.parse(raw_phone, region)
                if phonenumbers.is_valid_number(parsed):
                    formatted = phonenumbers.format_number(
                        parsed, phonenumbers.PhoneNumberFormat.E164
                    )
                    if formatted not in phones:
                        phones[formatted] = ExtractedContact(
                            value=formatted,
                            contact_type="phone",
                            source_url=page.url,
                            confidence=1.0,
                            raw=raw_phone,
                        )
            except phonenumbers.NumberParseException:
                continue

        # 2. Raw text pattern matching
        full_text = soup.get_text(separator=" ")
        for match in _PHONE_CANDIDATE.finditer(full_text):
            raw_phone = match.group(0).strip()
            try:
                parsed = phonenumbers.parse(raw_phone, region)
                if not phonenumbers.is_valid_number(parsed):
                    continue
                formatted = phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
                if formatted not in phones:
                    phones[formatted] = ExtractedContact(
                        value=formatted,
                        contact_type="phone",
                        source_url=page.url,
                        confidence=0.85,
                        raw=raw_phone,
                    )
            except phonenumbers.NumberParseException:
                continue

        return list(phones.values())

    # ------------------------------------------------------------------
    # Classification & scoring
    # ------------------------------------------------------------------

    def _classify_email(self, context: str) -> EmailType:
        """Classify email based on surrounding text keywords."""
        if not self._settings.extraction.extract_exec_email:
            pass
        elif _EXEC_KEYWORDS.search(context):
            return EmailType.EXEC

        if not self._settings.extraction.extract_hr_email:
            pass
        elif _HR_KEYWORDS.search(context):
            return EmailType.HR

        return EmailType.GENERAL

    def _email_confidence(
        self, email: str, base_domain: str, context: str
    ) -> float:
        """Score an email's relevance (0.0–1.0)."""
        score = 0.5
        domain = email.split("@")[-1].lower()

        # Strong boost: same domain as industry website
        if base_domain and domain == base_domain:
            score += 0.4
        elif base_domain and domain.endswith("." + base_domain):
            score += 0.3

        # Penalty: personal email domain
        if domain in _PERSONAL_DOMAINS:
            score -= 0.4

        # Boost: institutional keywords in address or context
        corporate = re.compile(r"info|contact|office|admin|exec|ceo|hr|careers?|jobs?", re.I)
        if corporate.search(email.split("@")[0]):
            score += 0.1
        if corporate.search(context):
            score += 0.05

        return max(0.0, min(1.0, score))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalise_email(self, raw: str) -> Optional[str]:
        """Lowercase, strip, and validate basic email format."""
        email = raw.strip().lower()
        if not _EMAIL_PATTERN.fullmatch(email):
            return None
        return email

    def _get_domain(self, url: str) -> str:
        """Extract the root domain from a URL."""
        try:
            parsed = urlparse(url)
            # Remove www. prefix
            return parsed.netloc.lstrip("www.")
        except Exception:
            return ""

    def _get_context(self, element: BeautifulSoup) -> str:
        """Get text around a BeautifulSoup element."""
        try:
            parent = element.find_parent()
            return parent.get_text(separator=" ")[:400] if parent else ""
        except Exception:
            return ""

    def _get_surrounding_text(self, text: str, pos: int, window: int = 150) -> str:
        """Get text window around a position."""
        start = max(0, pos - window)
        end = min(len(text), pos + window)
        return text[start:end]

    def _deduplicate(self, contacts: list[ExtractedContact]) -> list[ExtractedContact]:
        """Keep the highest-confidence instance of each value."""
        best: dict[str, ExtractedContact] = {}
        for contact in contacts:
            key = (contact.contact_type, contact.value)
            if key not in best or contact.confidence > best[key].confidence:
                best[key] = contact
        return list(best.values())
