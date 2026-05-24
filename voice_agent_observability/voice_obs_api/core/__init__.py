"""
voice_obs_api/core/__init__.py

Core application configuration and database singletons.
"""

from .database import Database
from .config import Settings, settings

__all__ = [
    "Database",
    "Settings",
    "settings"
]