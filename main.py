"""
Industry Contact Discovery System — CLI Entry Point

Usage:
    python main.py run --input data/sample_industries.csv
    python main.py run --input industries.xlsx --workers 20
    python main.py report
    python main.py export --format excel
    python main.py status
    python main.py reset --confirm
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: ensure project root is on sys.path
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Imports (after path fix)
# ---------------------------------------------------------------------------

from app.logger import setup_logging
from app.pipeline import Pipeline
from config import get_settings, reset_settings
from dashboard.live_dashboard import LiveDashboard
from exporters.exporter import Exporter
from importers.importer import IndustryImporter
from storage.database import Database
from storage.models import Statistics

logger = logging.getLogger("crawl")


# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------


async def cmd_run(args: argparse.Namespace) -> int:
    """Import industries (if given) and run the discovery pipeline."""
    settings = get_settings()

    setup_logging(
        log_dir=settings.logging.log_dir,
        level=settings.logging.level,
        console_level=settings.logging.console_level,
        max_bytes=settings.logging.max_bytes,
        backup_count=settings.logging.backup_count,
    )

    db_path = args.db or settings.storage.db_path

    async with Database(
        db_path,
        backup_on_start=settings.storage.backup_on_start,
    ) as db:
        # ── Import industries if --input provided ──────────────────
        all_skipped: list[dict] = []
        all_invalid: list[dict] = []

        if args.input:
            importer = IndustryImporter()
            industries, skipped = importer.load(
                args.input,
                source=args.source or Path(args.input).stem,
            )
            all_skipped.extend(skipped)

            inserted = await db.bulk_insert_industries(industries)
            print(
                f"[Import] {len(industries)} parsed, {inserted} new rows added, "
                f"{len(skipped)} skipped."
            )

        # ── Build statistics object ─────────────────────────────────
        db_stats = await db.get_statistics()
        total = sum(db_stats.values())
        if total == 0:
            print(
                "No industries in database. Use --input to import an industry list."
            )
            return 0

        stats = Statistics(total_industries=total)
        active_urls: list[str] = []

        # ── Set up graceful shutdown ────────────────────────────────
        shutdown_event = asyncio.Event()

        def _handle_signal(*_: object) -> None:
            print("\n[!] Interrupt received — saving progress...")
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handle_signal)
            except (OSError, ValueError):
                pass  # Windows may not support all signals

        # ── Run pipeline with live dashboard ────────────────────────
        pipeline = Pipeline(db=db, stats=stats, active_urls=active_urls)

        async with LiveDashboard(
            stats=stats,
            active_urls=active_urls,
            refresh_rate=settings.dashboard.refresh_rate,
            total=total,
        ):
            pipeline_task = asyncio.create_task(pipeline.run())
            done_task, _ = await asyncio.wait(
                [pipeline_task, asyncio.create_task(shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if shutdown_event.is_set():
                pipeline_task.cancel()
                try:
                    await pipeline_task
                except asyncio.CancelledError:
                    pass
                print("\nPipeline interrupted. Run again to resume from where it stopped.")
            else:
                final_stats = await pipeline_task

        # ── Generate reports ────────────────────────────────────────
        if settings.reports.auto_generate_on_complete:
            exporter = Exporter(settings.storage.output_dir)
            paths = await exporter.generate_all_reports(
                db=db,
                stats=stats,
                duplicates=all_skipped,
                invalid_contacts=all_invalid,
            )
            print(f"\nReports written to: {settings.storage.output_dir}")
            for name, path in paths.items():
                print(f"  {name:15s} -> {path}")

    return 0


async def cmd_report(args: argparse.Namespace) -> int:
    """Generate reports from the existing database without crawling."""
    settings = get_settings()
    setup_logging(**_log_kwargs(settings))
    db_path = args.db or settings.storage.db_path

    async with Database(db_path, backup_on_start=False) as db:
        stats = Statistics()
        exporter = Exporter(settings.storage.output_dir)
        paths = await exporter.generate_all_reports(db=db, stats=stats)
        print(f"Reports written to: {settings.storage.output_dir}")
        for name, path in paths.items():
            print(f"  {name:15s} -> {path}")
    return 0


async def cmd_status(args: argparse.Namespace) -> int:
    """Show current database statistics."""
    settings = get_settings()
    db_path = args.db or settings.storage.db_path

    async with Database(db_path, backup_on_start=False) as db:
        db_stats = await db.get_statistics()
        total = sum(db_stats.values())
        print(f"\n{'Industry Contact Discovery - Status':^50}")
        print("-" * 50)
        print(f"  {'Total industries':25s} {total:>8,}")
        for status, count in sorted(db_stats.items()):
            print(f"  {status:25s} {count:>8,}")
        print("-" * 50)
    return 0


async def cmd_reset(args: argparse.Namespace) -> int:
    """Reset all industry statuses to pending (for full re-run)."""
    if not args.confirm:
        print("Use --confirm to reset all crawl statuses to pending.")
        return 1

    settings = get_settings()
    db_path = args.db or settings.storage.db_path

    import aiosqlite
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "UPDATE industries SET crawl_status='pending', retry_count=0, error_message=NULL"
        )
        await conn.commit()
        async with conn.execute("SELECT changes()") as cur:
            row = await cur.fetchone()
            count = row[0] if row else 0
    print(f"Reset {count:,} industries to 'pending'.")
    return 0


async def cmd_web(args: argparse.Namespace) -> int:
    """Start the FastAPI + Uvicorn web dashboard server."""
    import uvicorn
    from config import get_settings
    settings = get_settings()

    if args.db:
        settings.storage.db_path = args.db

    print(f"\nBooting Web Dashboard...")
    print(f"Server is running at: http://{args.host}:{args.port}")
    print(f"Database path: {settings.storage.db_path}\n")

    from app.web_server import app

    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(config)
    await server.serve()
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="industry-discovery",
        description="Industry Contact Discovery System — autonomous B2B contact finder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py run --input data/sample_industries.csv
  python main.py run --input industries.xlsx --workers 20 --config config/config.json
  python main.py run                           # Resume interrupted run
  python main.py status
  python main.py report
  python main.py reset --confirm
        """,
    )
    parser.add_argument(
        "--config",
        default="config/config.json",
        help="Path to config.json (default: config/config.json)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ── run ──────────────────────────────────────────────────────────
    run_p = sub.add_parser("run", help="Run the discovery pipeline")
    run_p.add_argument("--input", "-i", help="Path to input file (CSV/Excel/JSON)")
    run_p.add_argument("--db", help="Override database path")
    run_p.add_argument("--workers", type=int, help="Override worker count")
    run_p.add_argument("--source", help="Label for this import batch")

    # ── report ───────────────────────────────────────────────────────
    report_p = sub.add_parser("report", help="Generate reports from existing database")
    report_p.add_argument("--db", help="Override database path")

    # ── status ───────────────────────────────────────────────────────
    status_p = sub.add_parser("status", help="Show database statistics")
    status_p.add_argument("--db", help="Override database path")

    # ── reset ────────────────────────────────────────────────────────
    reset_p = sub.add_parser("reset", help="Reset all industries to pending")
    reset_p.add_argument("--db", help="Override database path")
    reset_p.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm the reset operation",
    )

    # ── web ──────────────────────────────────────────────────────────
    web_p = sub.add_parser("web", help="Start the web dashboard server")
    web_p.add_argument("--host", default="127.0.0.1", help="Host address to bind to")
    web_p.add_argument("--port", type=int, default=8000, help="Port to listen on")
    web_p.add_argument("--db", help="Override database path")

    return parser


def _log_kwargs(settings: object) -> dict:
    s = settings.logging  # type: ignore[attr-defined]
    return {
        "log_dir": s.log_dir,
        "level": s.level,
        "console_level": s.console_level,
        "max_bytes": s.max_bytes,
        "backup_count": s.backup_count,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments and dispatch to the appropriate command."""
    parser = build_parser()
    args = parser.parse_args()

    # Load config before anything else
    reset_settings()
    settings = get_settings(args.config)

    # Apply CLI worker override
    if hasattr(args, "workers") and args.workers:
        settings.concurrency.worker_count = args.workers

    command_map = {
        "run": cmd_run,
        "report": cmd_report,
        "status": cmd_status,
        "reset": cmd_reset,
        "web": cmd_web,
    }

    handler = command_map.get(args.command)
    if not handler:
        parser.print_help()
        sys.exit(1)

    try:
        exit_code = asyncio.run(handler(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
