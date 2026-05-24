"""
voice_obs_api/core/database.py

Motor (async MongoDB) singleton — shared across the app.
"""

from __future__ import annotations
import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class Database:
    _client: AsyncIOMotorClient | None = None
    _db: AsyncIOMotorDatabase | None = None

    @classmethod
    async def connect(cls, uri: str, db_name: str) -> None:
        cls._client = AsyncIOMotorClient(uri)
        cls._db = cls._client[db_name]
        logger.info("Database connected: db=%s", db_name)

    @classmethod
    async def disconnect(cls) -> None:
        if cls._client:
            cls._client.close()

    @classmethod
    def get_db(cls) -> AsyncIOMotorDatabase:
        if cls._db is None:
            raise RuntimeError("Database not connected — call Database.connect() first")
        return cls._db
