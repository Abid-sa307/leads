"""
Live terminal dashboard for the Industry Contact Discovery System.

Uses Rich's Live display to render a multi-panel dashboard showing:
  - Overall progress bar
  - Key statistics table
  - Currently active URLs
  - Recent log entries
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)
from rich.table import Table
from rich.text import Text

from storage.models import Statistics

logger = logging.getLogger("crawl")
console = Console()


class LiveDashboard:
    """
    Rich terminal dashboard updated at a configurable refresh rate.

    Usage:
        async with LiveDashboard(stats, active_urls) as dashboard:
            await pipeline.run()
    """

    def __init__(
        self,
        stats: Statistics,
        active_urls: list[str],
        refresh_rate: float = 1.0,
        total: int = 0,
    ) -> None:
        self._stats = stats
        self._active_urls = active_urls
        self._refresh_rate = refresh_rate
        self._total = total
        self._live: Optional[Live] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._log_lines: list[str] = []

    async def __aenter__(self) -> "LiveDashboard":
        self._running = True
        self._live = Live(
            self._build_layout(),
            console=console,
            refresh_per_second=int(1 / self._refresh_rate),
            screen=False,
        )
        self._live.start()
        self._task = asyncio.create_task(self._refresh_loop())
        return self

    async def __aexit__(self, *_: object) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._live:
            self._live.update(self._build_layout())
            self._live.stop()

    async def _refresh_loop(self) -> None:
        """Continuously update the dashboard."""
        while self._running:
            if self._live:
                self._live.update(self._build_layout())
            await asyncio.sleep(self._refresh_rate)

    def add_log_line(self, line: str) -> None:
        """Add a line to the recent activity log panel."""
        self._log_lines.append(line)
        if len(self._log_lines) > 20:
            self._log_lines.pop(0)

    # ------------------------------------------------------------------
    # Layout builder
    # ------------------------------------------------------------------

    def _build_layout(self) -> Layout:
        """Build the complete dashboard layout."""
        layout = Layout()
        layout.split_column(
            Layout(self._header_panel(), size=3),
            Layout(name="middle", ratio=1),
            Layout(self._footer_panel(), size=3),
        )
        layout["middle"].split_row(
            Layout(self._stats_panel(), ratio=2),
            Layout(self._active_panel(), ratio=3),
        )
        return layout

    def _header_panel(self) -> Panel:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return Panel(
            Text(f"Industry Contact Discovery System  |  {now}", justify="center", style="bold cyan"),
            style="cyan",
        )

    def _stats_panel(self) -> Panel:
        """Build the statistics table panel."""
        s = self._stats
        elapsed = s.elapsed_seconds
        eta = s.eta_seconds

        elapsed_str = str(timedelta(seconds=int(elapsed)))
        eta_str = str(timedelta(seconds=int(eta))) if eta else "-"

        total = self._total or s.total_industries or 1
        pct = int((s.processed / total) * 100) if total else 0

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Key", style="bold white", width=18)
        table.add_column("Value", style="bright_green")

        rows = [
            ("Total Industries", f"{s.total_industries:,}"),
            ("Processed", f"{s.processed:,}  ({pct}%)"),
            ("[+] Successful", f"[green]{s.successful:,}[/green]"),
            ("[-] Failed", f"[red]{s.failed:,}[/red]"),
            ("[>] Skipped", f"[yellow]{s.skipped:,}[/yellow]"),
            ("[~] Remaining", f"{s.pending:,}"),
            ("[@] Emails Found", f"[cyan]{s.emails_found:,}[/cyan]"),
            ("[#] Phones Found", f"[cyan]{s.phones_found:,}[/cyan]"),
            ("[*] Sites Resolved", f"{s.websites_resolved:,}"),
            ("[T] Elapsed", elapsed_str),
            ("[E] ETA", eta_str),
        ]

        for key, val in rows:
            table.add_row(key, val)

        # Progress bar
        progress = Progress(
            SpinnerColumn(spinner_name="line"),
            BarColumn(bar_width=None),
            MofNCompleteColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        )
        task = progress.add_task("", total=total, completed=s.processed)

        from rich.console import Group
        content = Group(table, Text(""), progress)

        return Panel(content, title="[bold]Statistics[/bold]", border_style="blue")

    def _active_panel(self) -> Panel:
        """Build the active workers / recent activity panel."""
        lines: list[Text] = []

        if self._active_urls:
            lines.append(Text("Currently Crawling:", style="bold yellow"))
            for url in self._active_urls[-8:]:
                short = url[:60] + "..." if len(url) > 60 else url
                lines.append(Text(f"  -> {short}", style="dim cyan"))
            lines.append(Text(""))

        if self._log_lines:
            lines.append(Text("Recent Activity:", style="bold yellow"))
            for line in self._log_lines[-10:]:
                lines.append(Text(f"  {line}", style="dim white"))

        if not lines:
            lines.append(Text("Waiting for workers to start...", style="dim"))

        from rich.console import Group
        return Panel(
            Group(*lines),
            title="[bold]Live Activity[/bold]",
            border_style="yellow",
        )

    def _footer_panel(self) -> Panel:
        return Panel(
            Text(
                "Press Ctrl+C to interrupt (progress is saved - run again to resume)",
                justify="center",
                style="dim",
            ),
            style="dim",
        )
