# Installation Guide

## Requirements

- Python 3.13+
- Windows 10/11, macOS 12+, or Linux (Ubuntu 20.04+)
- Internet access (for Playwright browser download + website crawling)
- ~500 MB disk space (Chromium + dependencies)

---

## Step-by-Step Installation

### 1. Navigate to the project directory

```bash
cd industry-discovery
```

### 2. Create a virtual environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright's Chromium browser

```bash
playwright install chromium
```

> This downloads ~130 MB. It only needs to be done once per machine.

### 5. Verify installation

```bash
python -c "import playwright; import aiosqlite; import pydantic; print('OK')"
```

---

## Running Tests

```bash
pytest tests/ -v
```

All tests should pass without network access (external calls are mocked).

---

## Upgrade

```bash
pip install -r requirements.txt --upgrade
playwright install chromium
```
