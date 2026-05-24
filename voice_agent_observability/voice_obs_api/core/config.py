"""
voice_obs_api/core/config.py
"""

from __future__ import annotations
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGO_URI: str = "mongodb://localhost:27017/"
    MONGO_DB: str = "voice_agent_obs"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
