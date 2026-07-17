"""Unit tests for the ContactValidator."""

from __future__ import annotations

from pathlib import Path

import pytest

import sys
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import reset_settings
from storage.models import EmailType, ExtractedContact
from validators.contact_validator import ContactValidator


@pytest.fixture(autouse=True)
def reset_config():
    reset_settings()


def _email_contact(value: str, etype: EmailType = EmailType.GENERAL) -> ExtractedContact:
    return ExtractedContact(
        value=value,
        contact_type="email",
        email_type=etype,
        source_url="https://company.com/contact",
        confidence=0.9,
        raw=value,
    )


def _phone_contact(value: str) -> ExtractedContact:
    return ExtractedContact(
        value=value,
        contact_type="phone",
        source_url="https://company.com/contact",
        confidence=0.9,
        raw=value,
    )


class TestEmailValidation:
    """Tests for email validation."""

    def setup_method(self):
        self.validator = ContactValidator()

    def test_valid_email(self):
        ok, reason = self.validator.validate_email("info@mycompany.org")
        assert ok is True
        assert reason == ""

    def test_valid_email_subdomain(self):
        ok, _ = self.validator.validate_email("contact@hr.mycompany.org")
        assert ok is True

    def test_invalid_format_no_at(self):
        ok, reason = self.validator.validate_email("notanemail")
        assert ok is False
        assert reason == "invalid_format"

    def test_invalid_format_no_tld(self):
        ok, reason = self.validator.validate_email("test@nodot")
        assert ok is False

    def test_noise_domain(self):
        ok, reason = self.validator.validate_email("test@example.com")
        assert ok is False
        assert reason == "noise_domain"

    def test_noise_local(self):
        ok, reason = self.validator.validate_email("noreply@mycompany.org")
        assert ok is False
        assert reason == "noise_local"

    def test_empty_email(self):
        ok, reason = self.validator.validate_email("")
        assert ok is False
        assert reason == "empty"

    def test_batch_deduplication(self):
        emails = ["info@mycompany.org", "info@mycompany.org", "admin@mycompany.org"]
        valid, invalid = self.validator.validate_emails_batch(emails)
        assert len(valid) == 2
        assert len(invalid) == 1
        assert invalid[0]["reason"] == "duplicate"


class TestPhoneValidation:
    """Tests for phone validation."""

    def setup_method(self):
        self.validator = ContactValidator()

    def test_valid_us_phone(self):
        ok, formatted = self.validator.validate_phone("+12025550100")
        assert ok is True
        assert formatted.startswith("+1")

    def test_valid_e164_phone(self):
        ok, formatted = self.validator.validate_phone("+12025550100")
        assert ok is True
        assert formatted == "+12025550100"

    def test_invalid_phone_too_short(self):
        ok, _ = self.validator.validate_phone("123")
        assert ok is False

    def test_invalid_phone_empty(self):
        ok, _ = self.validator.validate_phone("")
        assert ok is False

    def test_phone_with_extension(self):
        ok, formatted = self.validator.validate_phone("555-123-4567 ext 123")
        assert isinstance(ok, bool)


class TestUrlValidation:
    """Tests for URL format validation."""

    def setup_method(self):
        self.validator = ContactValidator()

    def test_valid_https_url(self):
        ok, normalised = self.validator.validate_url_format("https://www.company.com")
        assert ok is True
        assert normalised == "https://www.company.com"

    def test_url_without_scheme_gets_https(self):
        ok, normalised = self.validator.validate_url_format("www.company.com")
        assert ok is True
        assert normalised.startswith("https://")

    def test_empty_url(self):
        ok, _ = self.validator.validate_url_format("")
        assert ok is False

    def test_url_no_tld(self):
        ok, _ = self.validator.validate_url_format("https://localhost")
        assert ok is False

    def test_url_with_path(self):
        ok, normalised = self.validator.validate_url_format("https://company.com/contact")
        assert ok is True


class TestContactBatchValidation:
    """Tests for batch contact validation."""

    def setup_method(self):
        self.validator = ContactValidator()

    def test_batch_valid_and_invalid(self):
        contacts = [
            _email_contact("info@mycompany.org"),
            _email_contact("noreply@mycompany.org"),
            _phone_contact("+12025550100"),
        ]
        valid, invalid = self.validator.validate_contacts(contacts)
        assert len(valid) == 2
        assert len(invalid) == 1

    def test_batch_dedup_contacts(self):
        contacts = [
            _email_contact("info@mycompany.org"),
            _email_contact("info@mycompany.org"),
        ]
        valid, invalid = self.validator.validate_contacts(contacts)
        assert len(valid) == 1
        assert len(invalid) == 1
        assert invalid[0]["reason"] == "duplicate"


class TestSelectBestContacts:
    """Tests for best-contact selection logic."""

    def setup_method(self):
        self.validator = ContactValidator()

    def test_select_by_type(self):
        contacts = [
            _email_contact("info@mycompany.org", EmailType.GENERAL),
            _email_contact("ceo@mycompany.org", EmailType.EXEC),
            _email_contact("hr@mycompany.org", EmailType.HR),
            _phone_contact("+12025550100"),
        ]
        best = self.validator.select_best_contacts(contacts)
        assert best["email"] == "info@mycompany.org"
        assert best["exec_email"] == "ceo@mycompany.org"
        assert best["hr_email"] == "hr@mycompany.org"
        assert best["phone"] == "+12025550100"

    def test_no_contacts_returns_none(self):
        best = self.validator.select_best_contacts([])
        assert all(v is None for v in best.values())
