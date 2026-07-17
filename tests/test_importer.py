"""Unit tests for the IndustryImporter."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import sys
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from importers.importer import IndustryImporter
from storage.models import CrawlStatus


class TestIndustryImporter:
    """Tests for CSV, Excel, and JSON import functionality."""

    def setup_method(self):
        self.importer = IndustryImporter()

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    def test_import_csv_basic(self, tmp_path):
        """Should parse a well-formed CSV and return Industry objects."""
        csv_file = tmp_path / "industries.csv"
        csv_file.write_text(
            "Industry Name,City,State,Country,Website\n"
            "Lincoln Industries,Springfield,IL,US,https://lincoln.com\n"
            "Adams Corp,Boston,MA,US,\n",
            encoding="utf-8",
        )
        industries, skipped = self.importer.load(csv_file, source="test")
        assert len(industries) == 2
        assert len(skipped) == 0
        assert industries[0].industry_name == "Lincoln Industries"
        assert industries[0].city == "Springfield"
        assert industries[0].website == "https://lincoln.com"
        assert industries[1].website is None

    def test_import_csv_deduplication(self, tmp_path):
        """Duplicate rows (same name+city+state) should be skipped."""
        csv_file = tmp_path / "dupes.csv"
        csv_file.write_text(
            "Industry Name,City,State\n"
            "Lincoln Industries,Springfield,IL\n"
            "Lincoln Industries,Springfield,IL\n",  # duplicate
            encoding="utf-8",
        )
        industries, skipped = self.importer.load(csv_file)
        assert len(industries) == 1
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "duplicate"

    def test_import_csv_missing_name(self, tmp_path):
        """Rows with empty industry name should be in skipped list."""
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text(
            "Industry Name,City\n"
            ",Boston\n"
            "Real Industry,Chicago\n",
            encoding="utf-8",
        )
        industries, skipped = self.importer.load(csv_file)
        assert len(industries) == 1
        assert len(skipped) == 1

    def test_import_csv_column_aliases(self, tmp_path):
        """Column aliases should be normalised to canonical names."""
        csv_file = tmp_path / "aliases.csv"
        csv_file.write_text(
            "company name,town,province,nation\n"
            "Test Industry,Springfield,IL,US\n",
            encoding="utf-8",
        )
        industries, _ = self.importer.load(csv_file)
        assert len(industries) == 1
        assert industries[0].industry_name == "Test Industry"
        assert industries[0].city == "Springfield"
        assert industries[0].state == "IL"

    def test_import_csv_url_normalisation(self, tmp_path):
        """URLs without scheme should get https:// prepended."""
        csv_file = tmp_path / "nohttps.csv"
        csv_file.write_text(
            "Industry Name,Website\n"
            "Test Industry,www.testindustry.com\n",
            encoding="utf-8",
        )
        industries, _ = self.importer.load(csv_file)
        assert industries[0].website == "https://www.testindustry.com"

    def test_import_csv_missing_required_column(self, tmp_path):
        """CSV with no industry_name column should raise ImportError."""
        from importers.importer import ImportError as IE
        csv_file = tmp_path / "bad.csv"
        csv_file.write_text("City,State\nBoston,MA\n", encoding="utf-8")
        with pytest.raises(IE):
            self.importer.load(csv_file)

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------

    def test_import_json_array(self, tmp_path):
        """JSON array of objects should be imported correctly."""
        data = [
            {"Industry Name": "Alpha Corp", "City": "Dallas", "State": "TX"},
            {"Industry Name": "Beta LLC", "City": "Austin", "State": "TX"},
        ]
        json_file = tmp_path / "industries.json"
        json_file.write_text(json.dumps(data), encoding="utf-8")
        industries, _ = self.importer.load(json_file)
        assert len(industries) == 2
        assert industries[0].industry_name == "Alpha Corp"

    def test_import_json_object_with_key(self, tmp_path):
        """JSON object wrapping an array should auto-detect the array key."""
        data = {
            "meta": {"total": 1},
            "industries": [{"Industry Name": "Gamma Inc", "City": "Miami", "State": "FL"}],
        }
        json_file = tmp_path / "wrapped.json"
        json_file.write_text(json.dumps(data), encoding="utf-8")
        industries, _ = self.importer.load(json_file)
        assert len(industries) == 1
        assert industries[0].industry_name == "Gamma Inc"

    # ------------------------------------------------------------------
    # Excel
    # ------------------------------------------------------------------

    def test_import_excel(self, tmp_path):
        """Excel file should import correctly."""
        df = pd.DataFrame(
            [
                {"Company Name": "Excel Inc", "City": "Seattle", "State": "WA", "Country": "US"},
            ]
        )
        xlsx_file = tmp_path / "industries.xlsx"
        df.to_excel(xlsx_file, index=False)
        industries, _ = self.importer.load(xlsx_file)
        assert len(industries) == 1
        assert industries[0].industry_name == "Excel Inc"
        assert industries[0].crawl_status == CrawlStatus.PENDING

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def test_import_unsupported_format(self, tmp_path):
        """Unsupported file extension should raise ImportError."""
        from importers.importer import ImportError as IE
        bad_file = tmp_path / "industries.xml"
        bad_file.write_text("<root/>")
        with pytest.raises(IE, match="Unsupported"):
            self.importer.load(bad_file)

    def test_import_file_not_found(self):
        """Non-existent file should raise ImportError."""
        from importers.importer import ImportError as IE
        with pytest.raises(IE, match="not found"):
            self.importer.load("nonexistent_file.csv")

    def test_crawl_status_is_pending(self, tmp_path):
        """Imported industries should always have PENDING status."""
        csv_file = tmp_path / "s.csv"
        csv_file.write_text("Industry Name\nTest Industry\n", encoding="utf-8")
        industries, _ = self.importer.load(csv_file)
        assert all(s.crawl_status == CrawlStatus.PENDING for s in industries)
