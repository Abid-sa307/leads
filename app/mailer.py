import asyncio
import smtplib
import logging
import csv
import io
from datetime import datetime, UTC
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Dict, Any, List

import aiosqlite
from config.settings import get_settings

logger = logging.getLogger("crawl")

# Global Campaign State
class CampaignStats:
    def __init__(self):
        self.active: bool = False
        self.total: int = 0
        self.sent: int = 0
        self.failed: int = 0
        self.current_company: str = ""
        self.errors: List[Dict[str, Any]] = []
        self.stop_requested: bool = False

campaign_stats = CampaignStats()

def format_template(template: str, industry: Dict[str, Any], email_val: str) -> str:
    """Safely replaces placeholders in the template text."""
    mapping = {
        "company_name": industry.get("industry_name", ""),
        "city": industry.get("city") or "",
        "state": industry.get("state") or "",
        "website": industry.get("website") or "",
        "email": email_val
    }
    result = template
    for key, val in mapping.items():
        result = result.replace("{" + key + "}", str(val))
    return result

def send_single_email(
    smtp_server: str,
    smtp_port: int,
    use_ssl: bool,
    sender_email: str,
    sender_password: str,
    recipient_email: str,
    subject: str,
    body: str
) -> None:
    """Synchronous function to send an email using SMTP. Executed in an async executor."""
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if use_ssl:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15)
    else:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
        # Check if we should upgrade to STARTTLS (common on port 587)
        if smtp_port == 587 or smtp_server in ["smtp.gmail.com", "smtp.office365.com"]:
            server.starttls()
    
    try:
        if sender_password:
            server.login(sender_email, sender_password)
        server.sendmail(sender_email, [recipient_email], msg.as_string())
    finally:
        try:
            server.quit()
        except Exception:
            pass

async def run_campaign_task(
    sector: str,
    email_type: str,
    smtp_server: str,
    smtp_port: int,
    use_ssl: bool,
    sender_email: str,
    sender_password: str,
    subject_template: str,
    body_template: str,
    delay_seconds: float = 2.0
):
    global campaign_stats
    settings = get_settings()

    campaign_stats.active = True
    campaign_stats.total = 0
    campaign_stats.sent = 0
    campaign_stats.failed = 0
    campaign_stats.current_company = ""
    campaign_stats.errors = []
    campaign_stats.stop_requested = False

    logger.info("Email Campaign starting for sector: %s, email_type: %s", sector, email_type)

    try:
        # Step 1: Retrieve matching leads that are completed (done) and have the required email type
        async with aiosqlite.connect(settings.storage.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            
            where_clauses = ["crawl_status = 'done'"]
            query_params = []
            
            if sector != "all":
                where_clauses.append("source = ?")
                query_params.append(sector)

            # Determine email type filters
            if email_type == "hr":
                where_clauses.append("hr_email IS NOT NULL AND hr_email != ''")
            elif email_type == "exec":
                where_clauses.append("exec_email IS NOT NULL AND exec_email != ''")
            elif email_type == "general":
                where_clauses.append("email IS NOT NULL AND email != ''")
            else: # any
                where_clauses.append("( (email IS NOT NULL AND email != '') OR (exec_email IS NOT NULL AND exec_email != '') OR (hr_email IS NOT NULL AND hr_email != '') )")

            where_sql = " WHERE " + " AND ".join(where_clauses)
            
            sql = f"SELECT * FROM industries{where_sql} ORDER BY id ASC"
            
            async with conn.execute(sql, query_params) as cur:
                leads = [dict(row) for row in await cur.fetchall()]

        campaign_stats.total = len(leads)
        logger.info("Found %d matching leads for the campaign.", campaign_stats.total)

        if campaign_stats.total == 0:
            campaign_stats.active = False
            return

        # Step 2: Iterate and send
        for lead in leads:
            if campaign_stats.stop_requested:
                logger.info("Email Campaign stopped by user request.")
                break

            # Find the best target email based on preference
            target_email = ""
            if email_type == "hr":
                target_email = lead["hr_email"]
            elif email_type == "exec":
                target_email = lead["exec_email"]
            elif email_type == "general":
                target_email = lead["email"]
            else:  # any: HR -> Exec -> General
                target_email = lead["hr_email"] or lead["exec_email"] or lead["email"]

            if not target_email:
                continue

            campaign_stats.current_company = lead["industry_name"]
            logger.info("Mailing %s (%s)", lead["industry_name"], target_email)

            # Format templates
            subj = format_template(subject_template, lead, target_email)
            body = format_template(body_template, lead, target_email)

            sent_ok = False
            err_msg = None

            try:
                # Run synchronous smtplib code inside a thread pool to avoid blocking the asyncio loop
                await asyncio.to_thread(
                    send_single_email,
                    smtp_server,
                    smtp_port,
                    use_ssl,
                    sender_email,
                    sender_password,
                    target_email,
                    subj,
                    body
                )
                sent_ok = True
                campaign_stats.sent += 1
            except Exception as e:
                err_msg = str(e)
                logger.error("Failed to send email to %s: %s", target_email, err_msg)
                campaign_stats.failed += 1
                campaign_stats.errors.append({
                    "company": lead["industry_name"],
                    "email": target_email,
                    "error": err_msg,
                    "timestamp": datetime.now(UTC).isoformat()
                })

            # Update database status
            async with aiosqlite.connect(settings.storage.db_path) as conn:
                now_str = datetime.now(UTC).isoformat()
                if sent_ok:
                    await conn.execute(
                        "UPDATE industries SET email_sent_status = 'sent', email_sent_at = ?, email_sent_error = NULL, last_updated = ? WHERE id = ?",
                        (now_str, now_str, lead["id"])
                    )
                else:
                    await conn.execute(
                        "UPDATE industries SET email_sent_status = 'failed', email_sent_at = ?, email_sent_error = ?, last_updated = ? WHERE id = ?",
                        (now_str, err_msg, now_str, lead["id"])
                    )
                await conn.commit()

            # Wait to avoid spam trigger / rate limit
            await asyncio.sleep(delay_seconds)

    except Exception as exc:
        logger.error("Exception in campaign run task: %s", str(exc))
    finally:
        campaign_stats.active = False
        campaign_stats.current_company = ""
        logger.info("Email Campaign completed. Sent: %d, Failed: %d", campaign_stats.sent, campaign_stats.failed)
