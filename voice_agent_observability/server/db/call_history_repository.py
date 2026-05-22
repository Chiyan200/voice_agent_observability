"""
server/db/call_history_repository.py

SERVER SIDE — MongoDB persistence layer.

Named "Repository" following the Repository Pattern:
  - Single class owns all read/write operations for one collection
  - Business logic (consumer) never builds queries directly
  - Swap MongoDB for any other store by replacing this file only
"""

from __future__ import annotations

import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo.results import UpdateResult

from shared.models.documents import CallHistoryDict, ObservationDict

logger = logging.getLogger(__name__)


class CallHistoryRepository:
    """
    Async MongoDB repository for call history documents.

    Collection schema:
        {
          "_id":          "<call_id>",
          "call_id":      str,
          "user_id":      str,
          "call_type":    str,
          "call_duration": int,       # seconds
          "observations": [ ObservationDict, ... ]
        }
    """

    COLLECTION_NAME = "call_histories"

    def __init__(
        self,
        uri: str = "mongodb://localhost:27017/",
        db_name: str = "voice_agent_obs",
    ):
        self._client = AsyncIOMotorClient(uri)
        self._collection: AsyncIOMotorCollection = (
            self._client[db_name][self.COLLECTION_NAME]
        )
        logger.info("CallHistoryRepository connected db=%s", db_name)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def upsert_call(
        self, call_id: str, user_id: str, call_type: str
    ) -> str:
        """
        Idempotent call initialisation.
        Creates the document if it does not exist; no-ops if it does.
        Returns the call_id.
        """
        document: CallHistoryDict = {
            "call_id": call_id,
            "user_id": user_id,
            "call_type": call_type,
            "call_duration": 0,
            "observations": [],
        }
        await self._collection.update_one(
            {"_id": call_id},
            {"$setOnInsert": document},
            upsert=True,
        )
        logger.debug("upsert_call call_id=%s", call_id)
        return call_id

    async def append_observation(
        self, call_id: str, observation: ObservationDict
    ) -> bool:
        """Push a single observation into the observations array."""
        result: UpdateResult = await self._collection.update_one(
            {"_id": call_id},
            {"$push": {"observations": observation}},
        )
        success = result.modified_count > 0
        if not success:
            logger.warning("append_observation: no document found for call_id=%s", call_id)
        return success

    async def set_call_duration(
        self, call_id: str, duration_sec: int
    ) -> bool:
        """Set the final call duration when the session closes."""
        result: UpdateResult = await self._collection.update_one(
            {"_id": call_id},
            {"$set": {"call_duration": duration_sec}},
        )
        success = result.modified_count > 0
        if not success:
            logger.warning("set_call_duration: no document found for call_id=%s", call_id)
        return success
