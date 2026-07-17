"""
Industry list importer for CSV, Excel, and JSON formats.

Auto-detects file format, normalises column names, deduplicates records,
and bulk-inserts into the database.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

import pandas as pd

from storage.models import CrawlStatus, Industry

logger = logging.getLogger("crawl")

# ---------------------------------------------------------------------------
# Column name aliases (case-insensitive mapping -> canonical field name)
# ---------------------------------------------------------------------------

COLUMN_ALIASES: dict[str, str] = {
    # industry_name
    "industry name": "industry_name",
    "industry": "industry_name",
    "name": "industry_name",
    "company": "industry_name",
    "company name": "industry_name",
    "firm": "industry_name",
    "firm name": "industry_name",
    "organization": "industry_name",
    "organization name": "industry_name",
    "industryname": "industry_name",
    # city
    "city": "city",
    "town": "city",
    # state
    "state": "state",
    "province": "state",
    "region": "state",
    "st": "state",
    # country
    "country": "country",
    "nation": "country",
    # website
    "website": "website",
    "url": "website",
    "web": "website",
    "site": "website",
    "homepage": "website",
    "industry website": "website",
    "industry url": "website",
    "company website": "website",
    "company url": "website",
}


class ImportError(Exception):
    """Raised when an import file cannot be parsed."""


class IndustryImporter:
    """
    Imports industry lists from CSV, Excel (.xlsx/.xls), and JSON files.

    Example:
        importer = IndustryImporter()
        industries, skipped = importer.load("my_industries.csv", source="batch_1")
    """

    def load(
        self,
        file_path: str | Path,
        source: Optional[str] = None,
    ) -> tuple[list[Industry], list[dict]]:
        """
        Load and parse an industry list file.

        Args:
            file_path: Path to the import file.
            source: Optional label for the import batch (stored in Industry.source).

        Returns:
            Tuple of (valid_industries, skipped_rows) where skipped_rows is a list
            of dicts containing rows that could not be parsed.

        Raises:
            ImportError: If the file format is unsupported or unreadable.
        """
        path = Path(file_path)
        if not path.exists():
            raise ImportError(f"File not found: {path}")

        suffix = path.suffix.lower()
        logger.info("Importing industries from %s (format: %s)", path.name, suffix)

        try:
            if suffix == ".csv":
                df = self._read_csv(path)
            elif suffix in (".xlsx", ".xls"):
                df = self._read_excel(path)
            elif suffix == ".json":
                df = self._read_json(path)
            else:
                raise ImportError(f"Unsupported file format: '{suffix}'")
        except ImportError:
            raise
        except Exception as exc:
            raise ImportError(f"Failed to read '{path.name}': {exc}") from exc

        df = self._normalise_columns(df)
        self._validate_required_columns(df, path.name)

        valid_industries: list[Industry] = []
        skipped_rows: list[dict] = []
        seen: set[tuple] = set()

        for idx, row in df.iterrows():
            parsed, skip_reason = self._parse_row(row, source)
            if parsed is None:
                skipped_rows.append({"row": idx, "reason": skip_reason, "data": row.to_dict()})
                continue

            dedup_key = (
                (parsed.industry_name or "").lower().strip(),
                (parsed.city or "").lower().strip(),
                (parsed.state or "").lower().strip(),
            )
            if dedup_key in seen:
                skipped_rows.append({"row": idx, "reason": "duplicate", "data": row.to_dict()})
                continue
            seen.add(dedup_key)
            valid_industries.append(parsed)

        logger.info(
            "Import complete: %d valid, %d skipped from %s",
            len(valid_industries),
            len(skipped_rows),
            path.name,
        )
        return valid_industries, skipped_rows

    # ------------------------------------------------------------------
    # Format readers
    # ------------------------------------------------------------------

    def _read_csv(self, path: Path) -> pd.DataFrame:
        """Read a CSV file, trying multiple encodings."""
        for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                return pd.read_csv(path, dtype=str, encoding=encoding, keep_default_na=False)
            except UnicodeDecodeError:
                continue
        raise ImportError(f"Could not decode '{path.name}' with any supported encoding.")

    def _read_excel(self, path: Path) -> pd.DataFrame:
        """Read the first sheet of an Excel workbook."""
        return pd.read_excel(path, dtype=str, keep_default_na=False)

    def _read_json(self, path: Path) -> pd.DataFrame:
        """
        Read a JSON file.

        Supports:
        - Array of objects: [{...}, {...}]
        - Object with a key containing the array: {"industries": [{...}]}
        """
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

        if isinstance(data, list):
            return pd.DataFrame(data, dtype=str)
        if isinstance(data, dict):
            # Find the first list value
            for key, value in data.items():
                if isinstance(value, list):
                    logger.debug("JSON: using key '%s' as records array", key)
                    return pd.DataFrame(value, dtype=str)
        raise ImportError("JSON must be an array of objects or a dict containing one.")

    # ------------------------------------------------------------------
    # Column normalisation
    # ------------------------------------------------------------------

    def _normalise_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rename columns using the alias map (case-insensitive)."""
        rename_map: dict[str, str] = {}
        for col in df.columns:
            canonical = COLUMN_ALIASES.get(col.strip().lower())
            if canonical:
                rename_map[col] = canonical
        return df.rename(columns=rename_map)

    def _validate_required_columns(self, df: pd.DataFrame, filename: str) -> None:
        """Ensure at minimum 'industry_name' is present."""
        if "industry_name" not in df.columns:
            raise ImportError(
                f"'{filename}' must contain an industry name column. "
                f"Found columns: {list(df.columns)}"
            )

    # ------------------------------------------------------------------
    # Row parser
    # ------------------------------------------------------------------

    def _parse_row(
        self, row: pd.Series, source: Optional[str]
    ) -> tuple[Optional[Industry], Optional[str]]:
        """
        Convert a DataFrame row to an Industry model.

        Returns:
            (Industry, None) on success, or (None, reason_string) on failure.
        """
        name = str(row.get("industry_name", "")).strip()
        if not name or name.lower() in ("nan", "none", ""):
            return None, "missing industry_name"

        website_raw = str(row.get("website", "")).strip()
        if website_raw.lower() in ("nan", "none", ""):
            website_raw = None  # type: ignore[assignment]

        def clean(val: str) -> Optional[str]:
            s = str(val).strip()
            return None if s.lower() in ("nan", "none", "") else s

        try:
            industry = Industry(
                industry_name=name,
                city=clean(row.get("city", "")),
                state=clean(row.get("state", "")),
                country=clean(row.get("country", "")) or "US",
                website=website_raw,
                raw_website_input=website_raw,
                source=source or "import",
                crawl_status=CrawlStatus.PENDING,
                created_at=datetime.now(UTC),
            )
        except Exception as exc:
            return None, str(exc)

        return industry, None
