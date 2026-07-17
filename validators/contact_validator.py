"""
Contact validator for the Industry Contact Discovery System.

Validates extracted emails, phone numbers, and website URLs.
Removes duplicates, invalid records, and broken URLs.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

import phonenumbers

from config import get_settings
from storage.models import ExtractedContact

logger = logging.getLogger("crawl")

# ---------------------------------------------------------------------------
# Email validation
# ---------------------------------------------------------------------------

# RFC 5321 simplified pattern
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]{1,64}@[a-zA-Z0-9.\-]{1,253}\.[a-zA-Z]{2,}$"
)

# Domains that are clearly noise
_NOISE_DOMAINS = frozenset(
    {
        "example.com", "example.org", "example.net",
        "test.com", "localhost", "domain.com",
        "email.com", "yourcompany.com", "company.com",
        "noreply.com",
    }
)

# Local-parts that are clearly noise
_NOISE_LOCALS = frozenset(
    {
        "noreply", "no-reply", "donotreply", "do-not-reply",
        "bounce", "postmaster", "mailer-daemon",
    }
)


class ContactValidator:
    """
    Validates emails, phone numbers, and website URLs extracted by the pipeline.

    All methods are pure (no I/O) except validate_url_reachable.
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Email
    # ------------------------------------------------------------------

    def validate_email(self, email: str) -> tuple[bool, str]:
        """
        Validate an email address.

        Args:
            email: The email string to validate.

        Returns:
            (is_valid, reason) where reason is empty string on success.
        """
        if not email:
            return False, "empty"

        email = email.strip().lower()

        if not _EMAIL_RE.match(email):
            return False, "invalid_format"

        parts = email.split("@")
        if len(parts) != 2:
            return False, "malformed"

        local, domain = parts

        # Check noise local-parts FIRST (before domain, to give correct reason)
        if local in _NOISE_LOCALS:
            return False, "noise_local"

        if domain in _NOISE_DOMAINS:
            return False, "noise_domain"

        # Domain must have at least one dot
        if "." not in domain:
            return False, "invalid_domain"

        # TLD check (basic)
        tld = domain.rsplit(".", 1)[-1]
        if len(tld) < 2 or not tld.isalpha():
            return False, "invalid_tld"

        return True, ""

    def validate_emails_batch(
        self, emails: list[str]
    ) -> tuple[list[str], list[dict]]:
        """
        Validate a list of emails.

        Returns:
            (valid_list, invalid_records)
        """
        valid: list[str] = []
        invalid: list[dict] = []
        seen: set[str] = set()

        for email in emails:
            email_lower = email.strip().lower()
            if email_lower in seen:
                invalid.append({"value": email, "reason": "duplicate"})
                continue
            seen.add(email_lower)

            ok, reason = self.validate_email(email_lower)
            if ok:
                valid.append(email_lower)
            else:
                invalid.append({"value": email, "reason": reason})

        return valid, invalid

    # ------------------------------------------------------------------
    # Phone
    # ------------------------------------------------------------------

    def validate_phone(
        self,
        phone: str,
        region: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Validate and format a phone number.

        Args:
            phone: Raw phone string.
            region: ISO region code (e.g., 'US'). Defaults to settings value.

        Returns:
            (is_valid, formatted_e164_or_empty)
        """
        if not phone:
            return False, ""

        region = region or self._settings.extraction.phone_default_region
        try:
            parsed = phonenumbers.parse(phone, region)
            if phonenumbers.is_valid_number(parsed):
                formatted = phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
                return True, formatted
            return False, ""
        except phonenumbers.NumberParseException:
            return False, ""

    # ------------------------------------------------------------------
    # URL / website
    # ------------------------------------------------------------------

    def validate_url_format(self, url: str) -> tuple[bool, str]:
        """
        Validate a URL syntactically (no network call).

        Returns:
            (is_valid, normalised_url_or_empty)
        """
        if not url:
            return False, ""

        url = url.strip()
        if not re.match(r"^https?://", url, re.IGNORECASE):
            url = "https://" + url

        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False, ""
            # Netloc must contain at least one dot
            if "." not in parsed.netloc:
                return False, ""
            return True, url
        except Exception:
            return False, ""

    # ------------------------------------------------------------------
    # Batch contact validation
    # ------------------------------------------------------------------

    def validate_contacts(
        self, contacts: list[ExtractedContact]
    ) -> tuple[list[ExtractedContact], list[dict]]:
        """
        Validate a list of ExtractedContact objects.

        Returns:
            (valid_contacts, invalid_records)
        """
        valid: list[ExtractedContact] = []
        invalid: list[dict] = []
        seen: set[str] = set()

        for contact in contacts:
            key = (contact.contact_type, contact.value)
            if key in seen:
                invalid.append({"contact": contact.value, "reason": "duplicate"})
                continue
            seen.add(key)

            if contact.contact_type == "email":
                ok, reason = self.validate_email(contact.value)
                if ok:
                    valid.append(contact)
                else:
                    invalid.append({"contact": contact.value, "reason": reason})

            elif contact.contact_type == "phone":
                ok, formatted = self.validate_phone(contact.value)
                if ok:
                    contact.value = formatted  # Normalise to E.164
                    valid.append(contact)
                else:
                    invalid.append({"contact": contact.value, "reason": "invalid_phone"})

            else:
                valid.append(contact)  # Unknown types pass through

        return valid, invalid

    def select_best_contacts(
        self,
        contacts: list[ExtractedContact],
        industry_domain: Optional[str] = None,
    ) -> dict[str, Optional[str]]:
        """
        Select the best contact values for each role from a validated list.

        Args:
            contacts: Validated contacts.
            industry_domain: The industry's website domain for preference boosting.

        Returns:
            Dict with keys: 'email', 'phone', 'exec_email', 'hr_email'.
        """
        emails = [c for c in contacts if c.contact_type == "email"]
        phones = [c for c in contacts if c.contact_type == "phone"]

        # Sort by confidence descending
        emails.sort(key=lambda c: c.confidence, reverse=True)
        phones.sort(key=lambda c: c.confidence, reverse=True)

        result: dict[str, Optional[str]] = {
            "email": None,
            "phone": None,
            "exec_email": None,
            "hr_email": None,
        }

        from storage.models import EmailType

        for email_contact in emails:
            etype = email_contact.email_type
            if etype == EmailType.EXEC and result["exec_email"] is None:
                result["exec_email"] = email_contact.value
            elif etype == EmailType.HR and result["hr_email"] is None:
                result["hr_email"] = email_contact.value
            elif result["email"] is None:
                result["email"] = email_contact.value

        if phones:
            result["phone"] = phones[0].value

        return result
