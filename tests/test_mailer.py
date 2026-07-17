"""Unit tests for the Email Mailer module."""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
import pytest
import pytest_asyncio
import sys
import sqlite3
import aiosqlite

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.database import Database
from storage.models import CrawlStatus, Industry
from app.mailer import format_template, CampaignStats

@pytest.fixture
def industry_dict():
    return {
        "id": 1,
        "industry_name": "Apollo Clinic",
        "city": "Chennai",
        "state": "Tamil Nadu",
        "website": "https://apolloclinic.com"
    }

def test_format_template(industry_dict):
    """Verifies that variables in the subject/body template are replaced correctly."""
    subj_template = "Inquiry for {company_name} in {city}"
    body_template = "Hello, we visited {website} for email {email} in {state}."
    
    formatted_subj = format_template(subj_template, industry_dict, "info@apolloclinic.com")
    formatted_body = format_template(body_template, industry_dict, "info@apolloclinic.com")
    
    assert formatted_subj == "Inquiry for Apollo Clinic in Chennai"
    assert formatted_body == "Hello, we visited https://apolloclinic.com for email info@apolloclinic.com in Tamil Nadu."

def test_format_template_missing_keys(industry_dict):
    """Verifies that template formatting is safe and does not raise exceptions for missing placeholders."""
    template = "Welcome to {company_name} at {unknown_placeholder}"
    formatted = format_template(template, industry_dict, "test@test.com")
    assert formatted == "Welcome to Apollo Clinic at {unknown_placeholder}"

@pytest.mark.asyncio
class TestMailerDatabase:
    """Tests the database integration of mailer statuses."""

    @pytest_asyncio.fixture
    async def db(self, tmp_path):
        """Provide a fresh DB upgraded to version 2."""
        db_path = tmp_path / "test_mail.db"
        async with Database(db_path, backup_on_start=False) as database:
            yield database

    async def test_update_mail_status(self, db):
        """Verifies that update_mail_status updates the campaign fields in the database."""
        # Insert a mock lead
        now = datetime.now(UTC).isoformat()
        await db._conn.execute(
            """
            INSERT INTO industries (industry_name, city, state, country, website, source, crawl_status, created_at, last_updated)
            VALUES ('Apollo Clinic', 'Chennai', 'Tamil Nadu', 'IN', 'https://apolloclinic.com', 'test', 'done', ?, ?)
            """,
            (now, now)
        )
        await db._conn.commit()
        
        async with db._conn.execute("SELECT id FROM industries LIMIT 1") as cur:
            row = await cur.fetchone()
            lead_id = row["id"]
            
        # Update mail status to sent
        sent_time = datetime.now(UTC).isoformat()
        await db.update_mail_status(lead_id, "sent", sent_time)
        
        async with db._conn.execute("SELECT email_sent_status, email_sent_at, email_sent_error FROM industries WHERE id = ?", (lead_id,)) as cur:
            row = await cur.fetchone()
            assert row["email_sent_status"] == "sent"
            assert row["email_sent_at"] == sent_time
            assert row["email_sent_error"] is None

        # Update mail status to failed with error
        await db.update_mail_status(lead_id, "failed", sent_time, "SMTP Authentication Error")
        
        async with db._conn.execute("SELECT email_sent_status, email_sent_at, email_sent_error FROM industries WHERE id = ?", (lead_id,)) as cur:
            row = await cur.fetchone()
            assert row["email_sent_status"] == "failed"
            assert row["email_sent_error"] == "SMTP Authentication Error"
