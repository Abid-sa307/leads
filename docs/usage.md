# Usage Guide

## CLI Overview

```
python main.py <command> [options]
```

### Commands

| Command | Description |
|---|---|
| `run` | Import industries and run the discovery pipeline |
| `status` | Show current database statistics |
| `report` | Generate reports without re-crawling |
| `reset` | Reset all industry statuses to pending |

---

## `run` — Discover industry contacts

```bash
python main.py run [--input FILE] [--workers N] [--source LABEL] [--db PATH]
```

**Options:**

| Option | Description |
|---|---|
| `--input` | Path to CSV, Excel, or JSON industry list (optional if DB already populated) |
| `--workers` | Override concurrency worker count |
| `--source` | Label for this import batch (stored in `source` field) |
| `--db` | Override the database path |
| `--config` | Path to config.json (default: `config/config.json`) |

**Examples:**

```bash
# First run: import and crawl
python main.py run --input data/sample_industries.csv

# Resume interrupted run (no --input needed)
python main.py run

# High-throughput run
python main.py run --input big_list.csv --workers 30

# Custom database
python main.py run --input industries.csv --db /data/production.db
```

---

## `status` — Check progress

```bash
python main.py status
```

Outputs a table like:

```
      Industry Contact Discovery — Status
──────────────────────────────────────────────────
  Total industries            10,000
  done                        8,432
  failed                        321
  pending                     1,247
──────────────────────────────────────────────────
```

---

## `report` — Generate reports

```bash
python main.py report [--db PATH]
```

Writes these files to `data/output/`:

| File | Contents |
|---|---|
| `summary.csv` | All industries with status `done` |
| `failed.csv` | All industries with status `failed` |
| `duplicate.csv` | Rows skipped during import |
| `invalid.csv` | Contacts that failed validation |
| `statistics.json` | Aggregate run metrics |
| `industries_full.xlsx` | Full database export (all statuses) |

---

## `reset` — Full re-run

```bash
python main.py reset --confirm
```

Resets all industry statuses to `pending` so the next `run` re-crawls everything.

> ⚠️ This does not delete extracted contact data — it only resets the crawl status.

---

## Interrupt and Resume

Press **Ctrl+C** at any time to stop the pipeline. Progress is saved after every industry. Run again to resume:

```bash
# Stop with Ctrl+C
# ...later...
# Automatically picks up where it left off
python main.py run   
```

---

## Input File Formats

### CSV

```csv
Industry Name,City,State,Country,Website
Lincoln Industries,Springfield,IL,US,https://lincoln.com
Adams Corp,Chicago,IL,US,
```

### Excel (.xlsx)

Same column structure as CSV. First sheet is used.

### JSON

```json
[
  {"Industry Name": "Lincoln Industries", "City": "Springfield", "State": "IL"},
  {"Industry Name": "Adams Corp", "City": "Chicago", "State": "IL"}
]
```

Or wrapped in an object:

```json
{
  "industries": [
    {"Industry Name": "Lincoln Industries", "City": "Springfield", "State": "IL"}
  ]
}
```

### Accepted Column Aliases

The importer accepts many common column name variants:

| Field | Accepted names |
|---|---|
| industry_name | `Industry Name`, `Industry`, `Name`, `Company`, `Company Name`, `Firm`, `Organization` |
| city | `City`, `Town` |
| state | `State`, `Province`, `Region`, `St` |
| country | `Country`, `Nation` |
| website | `Website`, `URL`, `Web`, `Site`, `Homepage` |

---

## Environment Variable Overrides

Any setting can be overridden with `SD_` prefixed environment variables:

```bash
# Double underscore (__) separates nested keys
SD_CONCURRENCY__WORKER_COUNT=30 python main.py run --input industries.csv
SD_CRAWLER__HEADLESS=false python main.py run --input test.csv
```
