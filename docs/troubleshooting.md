# Troubleshooting Guide

---

## Installation Issues

### `playwright install` fails

```
Error: Failed to install browsers
```

**Fix:** Ensure you have internet access and run:
```bash
playwright install chromium --with-deps
```

On Linux, you may need system dependencies:
```bash
sudo playwright install-deps chromium
```

---

### `ModuleNotFoundError: No module named 'playwright'`

Virtual environment is not activated, or dependencies are not installed.

```bash
.venv\Scripts\activate    # Windows
pip install -r requirements.txt
playwright install chromium
```

---

## Runtime Issues

### Industries are all showing `failed` status

**Causes and fixes:**
1. **No internet access** — check network connectivity
2. **All websites unreachable** — try `--workers 1` with `headless: false` to debug
3. **Firewall blocking Playwright** — whitelist Chromium in your firewall
4. **SSL certificate errors** — ensure `ssl_permissive: true` in config

---

### `No industries in database` even after import

The import ran successfully but wrote 0 industries. Check:
1. Your CSV has an `Industry Name` column (or accepted alias)
2. The file encoding is UTF-8 or Latin-1
3. Run with `--source test` and check the console output

---

### Pipeline is very slow

Default is 10 workers. Increase for faster processing:

```bash
python main.py run --input industries.csv --workers 30
```

Also increase `browser_pool_size` in `config.json`:
```json
{"concurrency": {"browser_pool_size": 15, "worker_count": 30}}
```

---

### `sqlite3.OperationalError: database is locked`

Only one instance of the pipeline should run at a time. Check for existing processes:
```bash
# Windows
tasklist | findstr python

# Kill extra instances
taskkill /IM python.exe
```

---

### Dashboard not rendering properly

If the Rich dashboard looks broken, try running without it by setting:
```bash
SD_DASHBOARD__REFRESH_RATE=999 python main.py run --input industries.csv
```

Or redirect output to a file for non-interactive environments:
```bash
python main.py run --input industries.csv > run.log 2>&1
```

---

## Data Issues

### No emails extracted from websites

**Debugging steps:**
1. Set `headless: false` in config to see what Playwright renders
2. Set log level to `DEBUG`: `SD_LOGGING__LEVEL=DEBUG`
3. Add the industry manually and test a single crawl
4. Check `logs/crawl.log` for page-level errors

---

### Emails from wrong domains are being captured

Increase `min_email_confidence` in config:
```json
{"extraction": {"min_email_confidence": 0.85, "prefer_same_domain_emails": true}}
```

---

### Phone numbers in wrong format

Change `phone_default_region` to match your target country:
```json
{"extraction": {"phone_default_region": "GB"}}
```

---

## Logs

| Log file | Contains |
|---|---|
| `logs/crawl.log` | All crawl events with timestamps |
| `logs/error.log` | Errors only |
| `logs/retry.log` | Retry attempts |
| `logs/statistics.log` | JSON statistics snapshots |

---

## Getting Help

1. Check `logs/error.log` for the specific error
2. Run `python main.py status` to see current DB state
3. Run with `SD_LOGGING__LEVEL=DEBUG` for verbose output
4. Open an issue with the error message and `logs/error.log` contents
