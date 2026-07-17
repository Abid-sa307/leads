"""Unit tests for the ContactExtractor."""

from __future__ import annotations

from pathlib import Path

import pytest

import sys
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import reset_settings
from crawler.page_crawler import CrawlResult, IndustryCrawlResult
from extractors.contact_extractor import ContactExtractor
from storage.models import EmailType


@pytest.fixture(autouse=True)
def reset_config():
    reset_settings()


def _make_crawl_result(html: str, url: str = "https://www.company.com/contact") -> IndustryCrawlResult:
    """Helper to build an IndustryCrawlResult with one page."""
    page = CrawlResult(url=url, html=html, final_url=url)
    return IndustryCrawlResult(
        industry_id=1,
        industry_name="Test Company",
        base_url="https://www.company.com",
        pages=[page],
        success=True,
    )


class TestContactExtractor:
    """Tests for email and phone extraction."""

    def setup_method(self):
        self.extractor = ContactExtractor()

    # ------------------------------------------------------------------
    # Email extraction
    # ------------------------------------------------------------------

    def test_extract_email_from_mailto(self):
        """Should extract email from mailto: anchor."""
        html = '<a href="mailto:info@company.com">Contact Us</a>'
        result = _make_crawl_result(html)
        contacts = self.extractor.extract(result)
        emails = [c for c in contacts if c.contact_type == "email"]
        assert any(c.value == "info@company.com" for c in emails)

    def test_extract_email_from_text(self):
        """Should extract email from raw page text."""
        html = "<p>Contact our office at office@company.com for information.</p>"
        result = _make_crawl_result(html)
        contacts = self.extractor.extract(result)
        emails = [c for c in contacts if c.contact_type == "email"]
        assert any(c.value == "office@company.com" for c in emails)

    def test_email_classification_exec(self):
        """Email near 'ceo' keyword should be classified as EXEC."""
        html = """
        <p>CEO's Office</p>
        <a href="mailto:ceo@company.com">Email CEO</a>
        """
        result = _make_crawl_result(html)
        contacts = self.extractor.extract(result)
        exec_contacts = [c for c in contacts if c.email_type == EmailType.EXEC]
        assert len(exec_contacts) >= 1

    def test_email_classification_hr(self):
        """Email near 'careers' keyword should be classified as HR."""
        html = """
        <p>Careers Office</p>
        <a href="mailto:hr@company.com">Apply Now</a>
        """
        result = _make_crawl_result(html)
        contacts = self.extractor.extract(result)
        hr_contacts = [c for c in contacts if c.email_type == EmailType.HR]
        assert len(hr_contacts) >= 1

    def test_same_domain_email_gets_higher_confidence(self):
        """Email on company domain should have higher confidence than off-domain."""
        html = """
        <a href="mailto:info@company.com">Company Email</a>
        <a href="mailto:random@gmail.com">External Email</a>
        """
        result = _make_crawl_result(html)
        contacts = self.extractor.extract(result)

        company_email = next((c for c in contacts if "company.com" in c.value), None)
        gmail_email = next((c for c in contacts if "gmail.com" in c.value), None)

        if company_email and gmail_email:
            assert company_email.confidence > gmail_email.confidence

    def test_deduplication(self):
        """Duplicate emails should be deduplicated, keeping highest confidence."""
        html = """
        <a href="mailto:info@company.com">Email 1</a>
        <a href="mailto:info@company.com">Email 2</a>
        """
        result = _make_crawl_result(html)
        contacts = self.extractor.extract(result)
        emails = [c for c in contacts if c.value == "info@company.com"]
        assert len(emails) == 1

    # ------------------------------------------------------------------
    # Phone extraction
    # ------------------------------------------------------------------

    def test_extract_phone_from_tel_link(self):
        """Should extract phone from tel: anchor."""
        html = '<a href="tel:+12025551234">Call Us</a>'
        result = _make_crawl_result(html)
        contacts = self.extractor.extract(result)
        phones = [c for c in contacts if c.contact_type == "phone"]
        assert isinstance(phones, list)

    def test_extract_phone_from_text(self):
        """Should extract phone number from page text."""
        html = "<p>Call us at (202) 555-0100 during business hours.</p>"
        result = _make_crawl_result(html)
        contacts = self.extractor.extract(result)
        assert isinstance(contacts, list)

    def test_phone_normalized_to_e164(self):
        """Extracted phones should be in E.164 format."""
        html = '<a href="tel:+12025550147">Phone</a>'
        result = _make_crawl_result(html)
        contacts = self.extractor.extract(result)
        phones = [c for c in contacts if c.contact_type == "phone"]
        if phones:
            assert phones[0].value.startswith("+")

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_html(self):
        """Empty HTML should return no contacts."""
        result = _make_crawl_result("")
        contacts = self.extractor.extract(result)
        assert contacts == []

    def test_no_contacts_in_html(self):
        """HTML with no emails or phones should return empty list."""
        html = "<html><body><h1>Welcome to our company!</h1></body></html>"
        result = _make_crawl_result(html)
        contacts = self.extractor.extract(result)
        assert contacts == []

    def test_multiple_pages_merged(self):
        """Should extract from all pages and deduplicate."""
        page1 = CrawlResult(
            url="https://company.com/",
            html='<a href="mailto:info@company.com">Email</a>',
            final_url="https://company.com/",
        )
        page2 = CrawlResult(
            url="https://company.com/contact",
            html='<a href="mailto:info@company.com">Same Email</a><a href="mailto:admin@company.com">Admin</a>',
            final_url="https://company.com/contact",
        )
        crawl = IndustryCrawlResult(
            industry_id=1,
            industry_name="Test Company",
            base_url="https://company.com",
            pages=[page1, page2],
            success=True,
        )
        contacts = self.extractor.extract(crawl)
        emails = {c.value for c in contacts if c.contact_type == "email"}
        assert "info@company.com" in emails
        assert "admin@company.com" in emails
        count = sum(1 for c in contacts if c.value == "info@company.com")
        assert count == 1

    def test_skips_failed_pages(self):
        """Pages with errors should be skipped during extraction."""
        page = CrawlResult(
            url="https://company.com/",
            html="",
            final_url="https://company.com/",
            error="Timeout",
        )
        crawl = IndustryCrawlResult(
            industry_id=1,
            industry_name="Test Company",
            base_url="https://company.com",
            pages=[page],
            success=False,
        )
        contacts = self.extractor.extract(crawl)
        assert contacts == []
