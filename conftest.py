"""
Root conftest.py — pytest configuration and shared fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is always on sys.path for all test files
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
