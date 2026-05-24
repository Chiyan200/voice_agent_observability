"""
server/db/post_analysis_repository.py

SERVER SIDE — MongoDB persistence layer for post-call analyses.
"""

from __future__ import annotations

import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo.results import UpdateResult

from shared.models.documents import PostCallAnalysisDict

logger = logging.getLogger(__name__)


class PostAnalysisRepository:
    """
    Async MongoDB repository for post-call analysis documents.
    """

    COLLECTION_NAME = "post_call_analyses"

    def __init__(
        self,
        uri: str = "mongodb://localhost:27017/",
        db_name: str = "voice_agent_obs",
    ):
        self._client = AsyncIOMotorClient(uri)
        self._collection: AsyncIOMotorCollection = (
            self._client[db_name][self.COLLECTION_NAME]
        )
        logger.info("PostAnalysisRepository connected db=%s", db_name)

    async def save_analysis(self, analysis: PostCallAnalysisDict) -> str:
        """
        Saves a post-call analysis document to the database.
        Overwrites existing documents if the analyze_id or call_id already exists.
        Returns the analyze_id.
        """
        # Ensure a unique index exists on analyze_id
        await self._collection.create_index("analyze_id", unique=True)
        await self._collection.create_index("call_id")

        await self._collection.update_one(
            {"analyze_id": analysis["analyze_id"]},
            {"$set": analysis},
            upsert=True,
        )
        logger.info("save_analysis analyze_id=%s call_id=%s saved successfully", 
                    analysis["analyze_id"], analysis["call_id"])
        return analysis["analyze_id"]

    async def get_analysis_by_call_id(self, call_id: str) -> PostCallAnalysisDict | None:
        """
        Retrieves a post-call analysis report by the call_id.
        """
        result = await self._collection.find_one({"call_id": call_id})
        return result
