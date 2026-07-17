import asyncio
import logging
import csv
import io
from pathlib import Path
from datetime import datetime, UTC
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import aiosqlite
from config import get_settings
from storage.database import Database
from storage.models import Statistics, Industry, CrawlStatus
from app.pipeline import Pipeline
from app.logger import setup_logging
from app.mailer import run_campaign_task, campaign_stats, send_single_email

logger = logging.getLogger("crawl")

app = FastAPI(title="Industry Leads Discoverer Dashboard")

@app.on_event("startup")
async def startup_event():
    settings = get_settings()
    setup_logging(
        log_dir=settings.logging.log_dir,
        level=settings.logging.level,
        console_level=settings.logging.console_level,
        max_bytes=settings.logging.max_bytes,
        backup_count=settings.logging.backup_count,
    )

# Global state to track background crawler
crawler_task: Optional[asyncio.Task] = None
active_urls: list[str] = []
current_stats = Statistics()
crawler_running = False
crawler_start_time: Optional[float] = None

# Serve static files
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Background Task
# ---------------------------------------------------------------------------

async def run_pipeline_task():
    global crawler_running, active_urls, current_stats, crawler_task, crawler_start_time
    crawler_running = True
    crawler_start_time = asyncio.get_event_loop().time()
    
    settings = get_settings()
    
    try:
        async with Database(settings.storage.db_path, backup_on_start=False) as db:
            # Get current statistics to initialize
            db_stats = await db.get_statistics()
            total = sum(db_stats.values())
            
            current_stats.total_industries = total
            current_stats.processed = db_stats.get("done", 0) + db_stats.get("failed", 0) + db_stats.get("no_website", 0)
            current_stats.successful = db_stats.get("done", 0)
            current_stats.failed = db_stats.get("failed", 0) + db_stats.get("no_website", 0)
            current_stats.skipped = db_stats.get("skipped", 0)
            current_stats.pending = db_stats.get("pending", 0)
            
            pipeline = Pipeline(db=db, stats=current_stats, active_urls=active_urls)
            await pipeline.run()
            
    except asyncio.CancelledError:
        logger.info("Crawler background task cancelled.")
    except Exception as exc:
        logger.error("Crawler background task encountered an error: %s", exc, exc_info=True)
    finally:
        crawler_running = False
        active_urls.clear()
        crawler_task = None

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def get_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return {"message": "Web Dashboard Frontend is initializing. Please refresh in a moment."}
    return FileResponse(index_path)

@app.get("/api/stats")
async def get_stats():
    settings = get_settings()
    async with Database(settings.storage.db_path, backup_on_start=False) as db:
        db_stats = await db.get_statistics()
        
    total = sum(db_stats.values())
    done = db_stats.get("done", 0)
    failed = db_stats.get("failed", 0) + db_stats.get("no_website", 0)
    skipped = db_stats.get("skipped", 0)
    crawling = db_stats.get("crawling", 0) + db_stats.get("resolving", 0)
    pending = db_stats.get("pending", 0)
    
    # Calculate elapsed and ETA if running
    elapsed = 0.0
    eta = None
    if crawler_running and crawler_start_time is not None:
        elapsed = asyncio.get_event_loop().time() - crawler_start_time
        processed_in_session = current_stats.processed - (done + failed - current_stats.processed)
        if processed_in_session > 0 and pending > 0:
            rate = processed_in_session / elapsed
            eta = pending / rate

    # Find total emails/phones found
    emails_count = 0
    phones_count = 0
    async with aiosqlite.connect(settings.storage.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT COUNT(*) as count FROM industries WHERE email IS NOT NULL OR exec_email IS NOT NULL OR hr_email IS NOT NULL"
        ) as cur:
            row = await cur.fetchone()
            emails_count = row["count"] if row else 0
        async with conn.execute(
            "SELECT COUNT(*) as count FROM industries WHERE phone IS NOT NULL"
        ) as cur:
            row = await cur.fetchone()
            phones_count = row["count"] if row else 0

    return {
        "isRunning": crawler_running,
        "activeUrls": active_urls,
        "stats": {
            "total": total,
            "done": done,
            "failed": failed,
            "skipped": skipped,
            "crawling": crawling,
            "pending": pending,
            "emailsFound": emails_count,
            "phonesFound": phones_count,
            "successRate": round((done / total * 100), 1) if total > 0 else 0.0,
            "elapsedSeconds": round(elapsed, 1),
            "etaSeconds": round(eta, 1) if eta is not None else None
        }
    }

@app.get("/api/industries")
async def get_industries(
    status: str = "all",
    source: str = "all",
    search: str = "",
    contact_filter: str = "all",
    sort_by: str = "id",
    sort_order: str = "asc",
    limit: int = 50,
    offset: int = 0
):
    settings = get_settings()
    
    # Sanitize sort fields
    allowed_sort_fields = {"id", "industry_name", "city", "state", "email", "phone", "crawl_status", "last_updated"}
    if sort_by not in allowed_sort_fields:
        sort_by = "id"
    sort_order = "DESC" if sort_order.upper() == "DESC" else "ASC"
    
    # Query building
    where_clauses = []
    query_params = []
    
    if status != "all":
        where_clauses.append("crawl_status = ?")
        query_params.append(status)
        
    if source != "all":
        where_clauses.append("source = ?")
        query_params.append(source)
        
    if search:
        search_pat = f"%{search}%"
        where_clauses.append(
            "(industry_name LIKE ? OR city LIKE ? OR state LIKE ? OR email LIKE ? OR phone LIKE ?)"
        )
        query_params.extend([search_pat] * 5)
        
    if contact_filter == "any_email":
        where_clauses.append("( (email IS NOT NULL AND email != '') OR (exec_email IS NOT NULL AND exec_email != '') OR (hr_email IS NOT NULL AND hr_email != '') )")
    elif contact_filter == "general_email":
        where_clauses.append("(email IS NOT NULL AND email != '')")
    elif contact_filter == "hr_email":
        where_clauses.append("(hr_email IS NOT NULL AND hr_email != '')")
    elif contact_filter == "exec_email":
        where_clauses.append("(exec_email IS NOT NULL AND exec_email != '')")
    elif contact_filter == "phone":
        where_clauses.append("(phone IS NOT NULL AND phone != '')")
    elif contact_filter == "no_contact":
        where_clauses.append("(email IS NULL OR email = '') AND (exec_email IS NULL OR exec_email = '') AND (hr_email IS NULL OR hr_email = '') AND (phone IS NULL OR phone = '')")
        
    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    
    async with aiosqlite.connect(settings.storage.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        
        # Get total matching count
        count_sql = f"SELECT COUNT(*) as count FROM industries{where_sql}"
        async with conn.execute(count_sql, query_params) as cur:
            row = await cur.fetchone()
            total_count = row["count"] if row else 0
            
        # Get data
        data_sql = f"SELECT * FROM industries{where_sql} ORDER BY {sort_by} {sort_order} LIMIT ? OFFSET ?"
        data_params = query_params + [limit, offset]
        
        async with conn.execute(data_sql, data_params) as cur:
            rows = await cur.fetchall()
            items = [dict(row) for row in rows]
            
        # Get list of unique sources for filter dropdown
        async with conn.execute("SELECT DISTINCT source FROM industries WHERE source IS NOT NULL ORDER BY source") as cur:
            sources = [r["source"] for r in await cur.fetchall()]
            
    return {
        "items": items,
        "total": total_count,
        "sources": sources,
        "limit": limit,
        "offset": offset
    }

@app.post("/api/run")
async def start_crawler():
    global crawler_task, crawler_running
    if crawler_running:
        return {"status": "error", "message": "Crawler is already running."}
        
    crawler_task = asyncio.create_task(run_pipeline_task())
    return {"status": "success", "message": "Crawler started in background."}

@app.post("/api/stop")
async def stop_crawler():
    global crawler_task, crawler_running
    if not crawler_running or not crawler_task:
        return {"status": "error", "message": "Crawler is not running."}
        
    crawler_task.cancel()
    crawler_running = False
    return {"status": "success", "message": "Crawler shutdown requested."}

@app.post("/api/reset")
async def reset_statuses():
    global crawler_running
    if crawler_running:
        raise HTTPException(status_code=400, detail="Cannot reset database while crawler is running.")
        
    settings = get_settings()
    async with aiosqlite.connect(settings.storage.db_path) as conn:
        await conn.execute(
            "UPDATE industries SET crawl_status='pending', retry_count=0, error_message=NULL, email=NULL, phone=NULL, exec_email=NULL, hr_email=NULL"
        )
        await conn.commit()
        
    return {"status": "success", "message": "All industry records reset to pending."}

@app.post("/api/seed")
async def seed_sectors():
    global crawler_running
    if crawler_running:
        raise HTTPException(status_code=400, detail="Cannot seed database while crawler is running.")
        
    from app.sample_data import SECTOR_DATA
    settings = get_settings()
    
    industries_to_insert = []
    for sector, companies in SECTOR_DATA.items():
        for c in companies:
            industries_to_insert.append(
                Industry(
                    industry_name=c["industry_name"],
                    city=c["city"],
                    state=c["state"],
                    country=c["country"],
                    website=c["website"],
                    raw_website_input=c["website"],
                    source=sector,
                    crawl_status=CrawlStatus.PENDING,
                    created_at=datetime.now(UTC)
                )
            )
            
    async with Database(settings.storage.db_path, backup_on_start=False) as db:
        inserted = await db.bulk_insert_industries(industries_to_insert)
        
    return {
        "status": "success",
        "message": f"Successfully seeded {inserted} new companies from the 6 target categories."
    }

@app.post("/api/concurrency")
async def update_concurrency(worker_count: int = Query(..., ge=1, le=100)):
    settings = get_settings()
    settings.concurrency.worker_count = worker_count
    return {"status": "success", "message": f"Updated active worker count to {worker_count}."}

@app.get("/api/export")
async def export_data(
    status: str = "all",
    source: str = "all",
    search: str = "",
    contact_filter: str = "all"
):
    settings = get_settings()
    where_clauses = []
    query_params = []
    
    if status != "all":
        where_clauses.append("crawl_status = ?")
        query_params.append(status)
        
    if source != "all":
        where_clauses.append("source = ?")
        query_params.append(source)
        
    if search:
        search_pat = f"%{search}%"
        where_clauses.append(
            "(industry_name LIKE ? OR city LIKE ? OR state LIKE ? OR email LIKE ? OR phone LIKE ?)"
        )
        query_params.extend([search_pat] * 5)
        
    if contact_filter == "any_email":
        where_clauses.append("( (email IS NOT NULL AND email != '') OR (exec_email IS NOT NULL AND exec_email != '') OR (hr_email IS NOT NULL AND hr_email != '') )")
    elif contact_filter == "general_email":
        where_clauses.append("(email IS NOT NULL AND email != '')")
    elif contact_filter == "hr_email":
        where_clauses.append("(hr_email IS NOT NULL AND hr_email != '')")
    elif contact_filter == "exec_email":
        where_clauses.append("(exec_email IS NOT NULL AND exec_email != '')")
    elif contact_filter == "phone":
        where_clauses.append("(phone IS NOT NULL AND phone != '')")
    elif contact_filter == "no_contact":
        where_clauses.append("(email IS NULL OR email = '') AND (exec_email IS NULL OR exec_email = '') AND (hr_email IS NULL OR hr_email = '') AND (phone IS NULL OR phone = '')")
        
    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    
    # Stream CSV
    async def csv_generator():
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            "ID", "Industry Name", "City", "State", "Country", "Website", 
            "Email", "Phone", "Exec Email", "HR Email", "Source", "Crawl Status", 
            "Retry Count", "Error Message", "Last Updated",
            "Email Sent Status", "Email Sent At", "Email Sent Error"
        ])
        yield output.getvalue()
        output.truncate(0)
        output.seek(0)
        
        async with aiosqlite.connect(settings.storage.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                f"SELECT * FROM industries{where_sql} ORDER BY id ASC", query_params
            ) as cur:
                async for row in cur:
                    writer.writerow([
                        row["id"], row["industry_name"], row["city"], row["state"], row["country"],
                        row["website"], row["email"], row["phone"], row["exec_email"], row["hr_email"],
                        row["source"], row["crawl_status"], row["retry_count"], row["error_message"],
                        row["last_updated"],
                        row["email_sent_status"], row["email_sent_at"], row["email_sent_error"]
                    ])
                    yield output.getvalue()
                    output.truncate(0)
                    output.seek(0)
                    
    headers = {
        "Content-Disposition": 'attachment; filename="leads_export.csv"',
        "Content-Type": "text/csv"
    }
    return StreamingResponse(csv_generator(), headers=headers)

# Request schemas for mailing campaigns
class MailSendRequest(BaseModel):
    sector: str
    email_type: str
    smtp_server: str
    smtp_port: int
    use_ssl: bool
    sender_email: str
    sender_password: str
    subject: str
    body: str
    delay_seconds: float = 2.0

class MailTestRequest(BaseModel):
    smtp_server: str
    smtp_port: int
    use_ssl: bool
    sender_email: str
    sender_password: str
    recipient_email: str

@app.post("/api/mail/test")
async def test_mail_settings(req: MailTestRequest):
    try:
        await asyncio.to_thread(
            send_single_email,
            req.smtp_server,
            req.smtp_port,
            req.use_ssl,
            req.sender_email,
            req.sender_password,
            req.recipient_email,
            "Test Email - Industry Leads Discoverer",
            "This is a test email confirming that your SMTP connection settings in the Industry Leads Discoverer app are valid!"
        )
        return {"status": "success", "message": "Test email sent successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/mail/send")
async def send_mail_campaign(req: MailSendRequest, background_tasks: BackgroundTasks):
    if campaign_stats.active:
        return {"status": "error", "message": "A mailing campaign is already running."}
    
    background_tasks.add_task(
        run_campaign_task,
        req.sector,
        req.email_type,
        req.smtp_server,
        req.smtp_port,
        req.use_ssl,
        req.sender_email,
        req.sender_password,
        req.subject,
        req.body,
        req.delay_seconds
    )
    return {"status": "success", "message": "Email campaign started in the background."}

@app.post("/api/mail/stop")
async def stop_mail_campaign():
    if not campaign_stats.active:
        return {"status": "error", "message": "No active mailing campaign is running."}
    campaign_stats.stop_requested = True
    return {"status": "success", "message": "Email campaign shutdown requested."}

@app.get("/api/mail/status")
async def get_mail_campaign_status():
    return {
        "active": campaign_stats.active,
        "total": campaign_stats.total,
        "sent": campaign_stats.sent,
        "failed": campaign_stats.failed,
        "current_company": campaign_stats.current_company,
        "errors": campaign_stats.errors,
        "stop_requested": campaign_stats.stop_requested
    }

# Mount the static files directory at /static
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
