"""
voice_obs_api/services/calls_service.py

Business / analytics logic for call history.
Controllers call this; this never touches HTTP or WebSocket concerns.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

COLL_CALLS    = "call_histories"
COLL_ANALYSIS = "post_call_analyses"


class CallsService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._calls    = db[COLL_CALLS]
        self._analysis = db[COLL_ANALYSIS]

    # ── List / get ─────────────────────────────────────────────────────────────

    async def list_calls(
        self,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[str] = None,
        call_type: Optional[str] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """Return (total, page_items) with lightweight summary fields."""
        query: Dict[str, Any] = {}
        if user_id:
            query["user_id"] = user_id
        if call_type:
            query["call_type"] = call_type

        total = await self._calls.count_documents(query)
        skip  = (page - 1) * page_size

        cursor = self._calls.find(query, {"observations": 1, "call_id": 1,
                                          "user_id": 1, "call_type": 1,
                                          "call_duration": 1}) \
                             .skip(skip).limit(page_size)

        # Collect analysis call_ids for has_analysis flag
        all_docs = await cursor.to_list(length=page_size)
        call_ids = [d["call_id"] for d in all_docs]
        analysed_ids = set()
        async for a in self._analysis.find({"call_id": {"$in": call_ids}}, {"call_id": 1}):
            analysed_ids.add(a["call_id"])

        summaries = []
        for doc in all_docs:
            obs = doc.get("observations", [])
            tool_failures = sum(
                1 for o in obs if o.get("tool_status") == "failure"
            )
            summaries.append({
                "call_id":       doc["call_id"],
                "user_id":       doc.get("user_id", ""),
                "call_type":     doc.get("call_type", ""),
                "call_duration": doc.get("call_duration", 0),
                "total_turns":   len({o["turn_id"] for o in obs}),
                "tool_failures": tool_failures,
                "has_analysis":  doc["call_id"] in analysed_ids,
            })

        return total, summaries

    async def get_call(self, call_id: str) -> Optional[Dict[str, Any]]:
        return await self._calls.find_one({"call_id": call_id})

    # ── Replay ─────────────────────────────────────────────────────────────────

    async def get_replay(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Return all observations enriched with per-turn latency."""
        doc = await self._calls.find_one({"call_id": call_id})
        if not doc:
            return None

        observations = doc.get("observations", [])
        turns = self._enrich_with_latency(observations)

        return {
            "call_id":     call_id,
            "total_turns": len(turns),
            "turns":       turns,
        }

    async def seek_turn(self, call_id: str, turn_index: int) -> Optional[Dict[str, Any]]:
        """Return a single turn by index."""
        doc = await self._calls.find_one({"call_id": call_id})
        if not doc:
            return None

        observations = doc.get("observations", [])
        turns = self._enrich_with_latency(observations)

        if turn_index < 0 or turn_index >= len(turns):
            return None

        return {
            "call_id":    call_id,
            "turn_index": turn_index,
            "turn":       turns[turn_index],
        }

    # ── Failure detection ─────────────────────────────────────────────────────

    def classify_failures(self, observations: List[Dict[str, Any]]) -> List[str]:
        """
        Returns a list of failure category strings for a call.
        Taxonomy: tool_failure | latency_spike | sentiment_crash |
                  hallucination | topic_drift | incomplete_resolution
        """
        failures: List[str] = []
        turns = self._enrich_with_latency(observations)

        # 1. Tool failures
        tool_fails = [t for t in turns if t.get("tool_status") == "failure"]
        if len(tool_fails) >= 2:
            failures.append("tool_failure")

        # 2. Latency spikes (>3 s agent response time)
        spikes = [t for t in turns if (t.get("latency_ms") or 0) > 3000]
        if spikes:
            failures.append("latency_spike")

        # 3. Emotion / sentiment crash mid-call
        emotions = [t.get("detected_emotion") for t in turns if t.get("detected_emotion")]
        if "frustrated" in emotions or emotions.count("excited") >= 3:
            failures.append("sentiment_crash")

        # 4. Duplicate LLM responses (hallucination proxy)
        llm_contents = [t["content"] for t in turns if t["type"] == "llm"]
        if len(llm_contents) != len(set(llm_contents)):
            failures.append("hallucination")

        # 5. User repeated themselves ≥ 2 times (topic drift / misunderstanding)
        stt_contents = [t["content"] for t in turns if t["type"] == "stt"]
        if len(stt_contents) != len(set(stt_contents)):
            failures.append("topic_drift")

        return failures

    # ── Dashboard / drift ─────────────────────────────────────────────────────

    async def get_dashboard(self) -> Dict[str, Any]:
        """Aggregate metrics across all calls for the drift dashboard."""
        total_calls  = await self._calls.count_documents({})
        all_analyses = await self._analysis.find({}).to_list(length=1000)
        all_calls    = await self._calls.find({}).to_list(length=1000)

        # ── Latency stats ───────────────────────────────────────────────────
        latency_stats = []
        failed_call_ids: set[str] = set()
        total_duration = 0

        for doc in all_calls:
            obs = doc.get("observations", [])
            total_duration += doc.get("call_duration", 0)
            turns = self._enrich_with_latency(obs)
            latencies = [t["latency_ms"] for t in turns if t.get("latency_ms")]

            if latencies:
                latencies_sorted = sorted(latencies)
                p95_idx = max(0, int(len(latencies_sorted) * 0.95) - 1)
                latency_stats.append({
                    "call_id":        doc["call_id"],
                    "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
                    "max_latency_ms": max(latencies),
                    "p95_latency_ms": latencies_sorted[p95_idx],
                })

            failures = self.classify_failures(obs)
            if failures:
                failed_call_ids.add(doc["call_id"])

        # ── Tool stats ──────────────────────────────────────────────────────
        tool_map: Dict[str, Dict[str, int]] = {}
        for doc in all_calls:
            for obs in doc.get("observations", []):
                name = obs.get("tool_name")
                if not name:
                    continue
                if name not in tool_map:
                    tool_map[name] = {"total": 0, "failures": 0}
                tool_map[name]["total"] += 1
                if obs.get("tool_status") == "failure":
                    tool_map[name]["failures"] += 1

        tool_stats = [
            {
                "tool_name":    k,
                "total_calls":  v["total"],
                "failures":     v["failures"],
                "success_rate": round(
                    (v["total"] - v["failures"]) / v["total"] * 100, 1
                ) if v["total"] else 0,
            }
            for k, v in tool_map.items()
        ]

        # ── Sentiment trends ────────────────────────────────────────────────
        sentiment_trends = [
            {
                "call_id":          a["call_id"],
                "user_sentiment":   a.get("sentiment", {}).get("user", {}).get("sentiment_label", "neutral"),
                "frustration_score": a.get("sentiment", {}).get("user", {}).get("frustration_score", 0.0),
                "analyzed_at":      a.get("analyzed_at"),
            }
            for a in all_analyses
        ]

        # ── Outliers: calls with avg latency > 3s OR >1 tool failure ───────
        outlier_ids = [
            s["call_id"] for s in latency_stats if s["avg_latency_ms"] > 3000
        ] + list(failed_call_ids)
        outlier_ids = list(set(outlier_ids))

        avg_duration = round(total_duration / total_calls, 1) if total_calls else 0

        return {
            "total_calls":         total_calls,
            "failed_calls":        len(failed_call_ids),
            "avg_call_duration_sec": avg_duration,
            "latency_stats":       latency_stats,
            "tool_stats":          tool_stats,
            "sentiment_trends":    sentiment_trends,
            "outlier_call_ids":    outlier_ids,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _enrich_with_latency(
        observations: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Flatten observations into a turn list and compute response latency:
        latency_ms = LLM start_time − preceding STT end_time
        """
        enriched = []
        last_stt_end: Optional[int] = None

        for i, obs in enumerate(observations):
            ts = obs.get("timestamp", {})
            start = ts.get("start_time") or (ts.get("start_time", {}) or {})
            end   = ts.get("end_time")   or (ts.get("end_time", {}) or {})

            # Handle nested $numberLong from Mongo
            if isinstance(start, dict):
                start = int(start.get("$numberLong", 0))
            if isinstance(end, dict):
                end = int(end.get("$numberLong", 0))

            latency_ms: Optional[int] = None
            if obs.get("type") == "llm" and last_stt_end is not None:
                latency_ms = max(0, start - last_stt_end)

            if obs.get("type") == "stt":
                last_stt_end = end

            enriched.append({
                "turn_index":      i,
                "turn_id":         obs.get("turn_id", ""),
                "type":            obs.get("type", ""),
                "role":            obs.get("role", ""),
                "content":         obs.get("content", ""),
                "duration_ms":     obs.get("duration_ms", 0),
                "timestamp":       {"start_time": start, "end_time": end},
                "latency_ms":      latency_ms,
                "tool_name":       obs.get("tool_name"),
                "tool_input":      obs.get("tool_input"),
                "tool_output":     obs.get("tool_output"),
                "tool_status":     obs.get("tool_status"),
                "detected_emotion": obs.get("detected_emotion"),
            })

        return enriched
