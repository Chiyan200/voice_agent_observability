"""
voice_obs_api/services/analysis_service.py
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

COLL_ANALYSIS = "post_call_analyses"
COLL_CALLS    = "call_histories"


class AnalysisService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._analysis = db[COLL_ANALYSIS]
        self._calls    = db[COLL_CALLS]

    async def get_by_call_id(self, call_id: str) -> Optional[Dict[str, Any]]:
        return await self._analysis.find_one({"call_id": call_id}, {"_id": 0})

    async def get_by_analyze_id(self, analyze_id: str) -> Optional[Dict[str, Any]]:
        return await self._analysis.find_one({"analyze_id": analyze_id}, {"_id": 0})

    async def list_analyses(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        total  = await self._analysis.count_documents({})
        skip   = (page - 1) * page_size
        cursor = self._analysis.find({}, {"_id": 0}).skip(skip).limit(page_size)
        items  = await cursor.to_list(length=page_size)
        return {"total": total, "page": page, "page_size": page_size, "items": items}

    async def get_failure_report(self, call_id: str) -> Optional[Dict[str, Any]]:
        """
        Structured per-call failure report (Task 2 of the assignment).
        Identifies exact turn, root-cause category, what happened, what should have happened.
        """
        call    = await self._calls.find_one({"call_id": call_id})
        analysis = await self._analysis.find_one({"call_id": call_id}, {"_id": 0})

        if not call:
            return None

        from services.calls_service import CallsService

        obs    = call.get("observations", [])
        turns  = CallsService._enrich_with_latency(obs)

        failure_turns = []
        for t in turns:
            reasons = []

            if t.get("tool_status") == "failure":
                reasons.append({
                    "category":    "tool_failure",
                    "what_happened": (
                        f"Tool '{t['tool_name']}' called with input {t['tool_input']} "
                        f"returned: {t['tool_output']}"
                    ),
                    "what_should_happen": (
                        "Agent should validate the account ID format before "
                        "calling the tool, or surface the exact API error to the user."
                    ),
                })

            if (t.get("latency_ms") or 0) > 3000:
                reasons.append({
                    "category":    "latency_spike",
                    "what_happened": f"Agent response latency was {t['latency_ms']} ms",
                    "what_should_happen": "Response should arrive within 1500 ms for natural conversation.",
                })

            if t.get("detected_emotion") == "frustrated":
                reasons.append({
                    "category":    "sentiment_crash",
                    "what_happened": "User emotion detected as frustrated",
                    "what_should_happen": "Agent should de-escalate and offer alternative resolution.",
                })

            if reasons:
                failure_turns.append({
                    "turn_index":  t["turn_index"],
                    "turn_id":     t["turn_id"],
                    "type":        t["type"],
                    "role":        t["role"],
                    "content":     t["content"],
                    "timestamp":   t["timestamp"],
                    "root_causes": reasons,
                })

        # Check for hallucination (duplicate LLM responses across turns)
        llm_contents = [t["content"] for t in turns if t["type"] == "llm"]
        hallucination_flag = len(llm_contents) != len(set(llm_contents))

        # Unresolved queries from QA evaluation
        unresolved = []
        if analysis:
            unresolved = analysis.get("qa_evaluation", {}).get("unresolved_queries", [])

        return {
            "call_id":          call_id,
            "call_duration_sec": call.get("call_duration", 0),
            "total_turns":      len(turns),
            "hallucination_detected": hallucination_flag,
            "unresolved_queries": unresolved,
            "failure_turns":    failure_turns,
            "overall_failure_categories": list({
                rc["category"]
                for ft in failure_turns
                for rc in ft["root_causes"]
            }),
            "qa_summary": analysis.get("qa_evaluation", {}).get("conversation_summary", "No analysis available.") if analysis else "No analysis available.",
        }
