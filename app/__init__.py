"""App package."""
from .logger import setup_logging
from .pipeline import Pipeline

__all__ = ["Pipeline", "setup_logging"]
