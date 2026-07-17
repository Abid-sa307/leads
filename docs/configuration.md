# Configuration Guide

All configuration is managed through `config/config.json`.
Environment variables with the prefix `SD_` override JSON values.

---

## Full Configuration Reference

```json
{
  "concurrency": {
    "browser_pool_size": 5,           // Number of Playwright browser contexts
    "worker_count": 10,               // Number of async worker coroutines
    "requests_per_second_per_domain": 1.0, // Rate limit per domain
    "max_concurrent_domains": 20      // Max unique domains at once
  },
  "timeouts": {
    "page_load_seconds": 30,          // Max wait for page to load
    "request_seconds": 15,            // Max wait for HTTP response
    "dns_seconds": 5,                 // DNS lookup timeout
    "resolve_timeout_seconds": 20     // Website resolution total timeout
  },
  "retries": {
    "max_attempts": 3,                // Total crawl attempts per industry
    "backoff_factor": 2.0,            // Exponential backoff multiplier
    "retry_on_status": [429, 500, 502, 503, 504]
  },
  "crawler": {
    "headless": true,                 // Run Chromium headlessly
    "user_agent": "...",              // Browser user-agent string
    "accept_language": "en-US,en;q=0.9",
    "pages_to_visit": ["/", "/contact", "/about", "/careers"],
    "respect_robots_txt": true,
    "ssl_permissive": true,           // Ignore SSL certificate errors
    "max_pages_per_industry": 10      // Stop after N pages per industry
  },
  "resolver": {
    "use_cache": true,                // Cache resolved URLs in SQLite
    "search_engine": "duckduckgo",
    "verify_before_crawl": true       // HEAD request to verify URL
  },
  "extraction": {
    "prefer_same_domain_emails": true,
    "extract_exec_email": true,
    "extract_hr_email": true,
    "min_email_confidence": 0.7,      // Minimum score to keep email
    "phone_default_region": "US"
  },
  "storage": {
    "db_path": "data/industries.db",
    "output_dir": "data/output",
    "backup_on_start": true           // Backup DB before each run
  },
  "logging": {
    "level": "INFO",                  // File log level
    "log_dir": "logs",
    "max_bytes": 10485760,            // 10 MB per log file
    "backup_count": 5,
    "console_level": "INFO"
  },
  "dashboard": {
    "refresh_rate": 1.0,              // Dashboard update interval (seconds)
    "show_active_workers": true
  },
  "reports": {
    "auto_generate_on_complete": true,
    "include_raw_html": false
  }
}
```

---

## Performance Tuning

### For 100,000+ industries overnight

```json
{
  "concurrency": {
    "browser_pool_size": 10,
    "worker_count": 20,
    "requests_per_second_per_domain": 2.0
  },
  "timeouts": {
    "page_load_seconds": 20
  }
}
```

### For slow/unreliable networks

```json
{
  "timeouts": {
    "page_load_seconds": 60,
    "request_seconds": 30
  },
  "retries": {
    "max_attempts": 5,
    "backoff_factor": 3.0
  }
}
```

### For testing / debugging

```json
{
  "concurrency": {
    "browser_pool_size": 1,
    "worker_count": 1
  },
  "crawler": {
    "headless": false
  },
  "logging": {
    "level": "DEBUG",
    "console_level": "DEBUG"
  }
}
```

---

## Environment Variable Examples

```bash
# Override worker count
SD_CONCURRENCY__WORKER_COUNT=30

# Use a custom database path
SD_STORAGE__DB_PATH=/data/production/industries.db

# Enable visible browser (for debugging)
SD_CRAWLER__HEADLESS=false

# Verbose logging
SD_LOGGING__LEVEL=DEBUG
SD_LOGGING__CONSOLE_LEVEL=DEBUG
```
