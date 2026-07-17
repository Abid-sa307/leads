"""
Report and export module for the Industry Contact Discovery System.

Generates the following output files on completion:
  - summary.csv        — all industries with status=done
  - failed.csv         — all industries with status=failed
  - duplicate.csv      — rows skipped during import (duplicates)
  - invalid.csv        — contacts that failed validation
  - statistics.json    — run-level aggregated metrics

Also supports on-demand export of the full database to Excel.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

import pandas as pd

from storage.database import Database
from storage.models import Industry, Statistics

logger = logging.getLogger("crawl")


class Exporter:
    """
    Generates CSV, Excel, and JSON reports from the industry database.

    All output is written to the configured output directory.
    """

    def __init__(self, output_dir: str = "data/output") -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Full report suite
    # ------------------------------------------------------------------

    async def generate_all_reports(
        self,
        db: Database,
        stats: Optional[Statistics] = None,
        duplicates: Optional[list[dict]] = None,
        invalid_contacts: Optional[list[dict]] = None,
    ) -> dict[str, Path]:
        """
        Generate all standard reports.

        Args:
            db: Open Database instance.
            stats: Final pipeline statistics.
            duplicates: Rows skipped during import (from importer).
            invalid_contacts: Contacts rejected by the validator.

        Returns:
            Dict mapping report name -> file path.
        """
        outputs: dict[str, Path] = {}

        # summary.csv
        done_industries = []
        async for industry in db.get_all_done():
            done_industries.append(industry)
        outputs["summary"] = self._write_industries_csv(done_industries, "summary.csv")

        # failed.csv
        failed_industries = await db.get_all_failed()
        outputs["failed"] = self._write_industries_csv(failed_industries, "failed.csv")

        # duplicate.csv
        if duplicates:
            outputs["duplicate"] = self._write_dict_csv(duplicates, "duplicate.csv")

        # invalid.csv
        if invalid_contacts:
            outputs["invalid"] = self._write_dict_csv(invalid_contacts, "invalid.csv")

        # statistics.json
        if stats:
            outputs["statistics"] = self._write_statistics(stats)

        # Full Excel export
        all_industries = await db.get_all_industries()
        outputs["full_excel"] = self._write_excel(all_industries)

        logger.info(
            "Reports generated in %s: %s",
            self._output_dir,
            ", ".join(outputs.keys()),
        )
        return outputs

    # ------------------------------------------------------------------
    # Individual writers
    # ------------------------------------------------------------------

    def _write_industries_csv(self, industries: list[Industry], filename: str) -> Path:
        """Write a list of Industry records to a CSV file."""
        path = self._output_dir / filename

        if not industries:
            # Write empty file with headers
            df = pd.DataFrame(columns=_INDUSTRY_COLUMNS)
        else:
            rows = [_industry_to_row(s) for s in industries]
            df = pd.DataFrame(rows, columns=_INDUSTRY_COLUMNS)

        df.to_csv(path, index=False, encoding="utf-8-sig")
        logger.info("Written: %s (%d rows)", filename, len(df))
        return path

    def _write_dict_csv(self, records: list[dict], filename: str) -> Path:
        """Write a list of dicts to a CSV file."""
        path = self._output_dir / filename
        pd.DataFrame(records).to_csv(path, index=False, encoding="utf-8-sig")
        logger.info("Written: %s (%d rows)", filename, len(records))
        return path

    def _write_statistics(self, stats: Statistics) -> Path:
        """Write statistics to a JSON file."""
        path = self._output_dir / "statistics.json"
        data = stats.model_dump(mode="json")
        data["generated_at"] = datetime.now(UTC).isoformat()
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
        logger.info("Written: statistics.json")
        return path

    def _write_excel(self, industries: list[Industry]) -> Path:
        """Write complete industry database to Excel with formatting."""
        path = self._output_dir / "industries_full.xlsx"

        if not industries:
            pd.DataFrame(columns=_INDUSTRY_COLUMNS).to_excel(path, index=False)
            return path

        rows = [_industry_to_row(s) for s in industries]
        df = pd.DataFrame(rows, columns=_INDUSTRY_COLUMNS)

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Industries")

            ws = writer.sheets["Industries"]

            # Auto-width columns
            for col_idx, col_name in enumerate(df.columns, start=1):
                max_len = max(
                    len(str(col_name)),
                    df[col_name].astype(str).str.len().max() or 0,
                )
                ws.column_dimensions[
                    ws.cell(row=1, column=col_idx).column_letter
                ].width = min(max_len + 2, 50)

        logger.info("Written: industries_full.xlsx (%d rows)", len(df))
        return path


# ---------------------------------------------------------------------------
# CSV columns
# ---------------------------------------------------------------------------

_INDUSTRY_COLUMNS = [
    "id",
    "industry_name",
    "city",
    "state",
    "country",
    "website",
    "email",
    "phone",
    "exec_email",
    "hr_email",
    "source",
    "crawl_status",
    "retry_count",
    "error_message",
    "last_updated",
]


def _industry_to_row(industry: Industry) -> dict:
    """Convert an Industry model to a flat dict for DataFrame rows."""
    return {
        "id": industry.id,
        "industry_name": industry.industry_name,
        "city": industry.city,
        "state": industry.state,
        "country": industry.country,
        "website": industry.website,
        "email": industry.email,
        "phone": industry.phone,
        "exec_email": industry.exec_email,
        "hr_email": industry.hr_email,
        "source": industry.source,
        "crawl_status": industry.crawl_status.value,
        "retry_count": industry.retry_count,
        "error_message": industry.error_message,
        "last_updated": industry.last_updated.isoformat() if industry.last_updated else None,
    }
