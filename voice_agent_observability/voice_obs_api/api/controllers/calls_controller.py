"""
voice_obs_api/api/controllers/calls_controller.py

Controller layer — translates service data into Pydantic response models.
Keeps routers thin and testable.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from models.response_models import (
    CallDetailModel,
    CallSummaryModel,
    ObservationModel,
    PaginatedCallsModel,
    ReplayModel,
    SeekModel,
    TimestampModel,
    TurnReplayModel,
)
from services.calls_service import CallsService


def _obs_to_model(o: dict) -> ObservationModel:
    ts = o.get("timestamp", {})
    return ObservationModel(
        turn_id=o.get("turn_id", ""),
        type=o.get("type", ""),
        role=o.get("role", ""),
        duration_ms=o.get("duration_ms", 0),
        timestamp=TimestampModel(
            start_time=ts.get("start_time", 0),
            end_time=ts.get("end_time", 0),
        ),
        content=o.get("content", ""),
        tool_name=o.get("tool_name"),
        tool_input=o.get("tool_input"),
        tool_output=o.get("tool_output"),
        tool_status=o.get("tool_status"),
        detected_emotion=o.get("detected_emotion"),
    )


def _turn_to_model(t: dict) -> TurnReplayModel:
    ts = t.get("timestamp", {})
    return TurnReplayModel(
        turn_index=t["turn_index"],
        turn_id=t.get("turn_id", ""),
        type=t.get("type", ""),
        role=t.get("role", ""),
        content=t.get("content", ""),
        duration_ms=t.get("duration_ms", 0),
        timestamp=TimestampModel(
            start_time=ts.get("start_time", 0),
            end_time=ts.get("end_time", 0),
        ),
        latency_ms=t.get("latency_ms"),
        tool_name=t.get("tool_name"),
        tool_input=t.get("tool_input"),
        tool_output=t.get("tool_output"),
        tool_status=t.get("tool_status"),
        detected_emotion=t.get("detected_emotion"),
    )


class CallsController:
    def __init__(self, service: CallsService):
        self._svc = service

    async def list_calls(
        self,
        page: int,
        page_size: int,
        user_id: Optional[str],
        call_type: Optional[str],
    ) -> PaginatedCallsModel:
        total, items = await self._svc.list_calls(page, page_size, user_id, call_type)
        return PaginatedCallsModel(
            total=total,
            page=page,
            page_size=page_size,
            items=[CallSummaryModel(**item) for item in items],
        )

    async def get_call(self, call_id: str) -> CallDetailModel:
        doc = await self._svc.get_call(call_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"Call '{call_id}' not found")

        # Normalise $numberLong timestamps in observations
        normalised_obs = []
        for obs in doc.get("observations", []):
            ts = obs.get("timestamp", {})
            s = ts.get("start_time", 0)
            e = ts.get("end_time", 0)
            if isinstance(s, dict):
                s = int(s.get("$numberLong", 0))
            if isinstance(e, dict):
                e = int(e.get("$numberLong", 0))
            normalised_obs.append({**obs, "timestamp": {"start_time": s, "end_time": e}})

        return CallDetailModel(
            call_id=doc["call_id"],
            user_id=doc.get("user_id", ""),
            call_type=doc.get("call_type", ""),
            call_duration=doc.get("call_duration", 0),
            observations=[_obs_to_model(o) for o in normalised_obs],
        )

    async def get_replay(self, call_id: str) -> ReplayModel:
        data = await self._svc.get_replay(call_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"Call '{call_id}' not found")
        return ReplayModel(
            call_id=data["call_id"],
            total_turns=data["total_turns"],
            turns=[_turn_to_model(t) for t in data["turns"]],
        )

    async def seek_turn(self, call_id: str, turn: int) -> SeekModel:
        data = await self._svc.seek_turn(call_id, turn)
        if not data:
            raise HTTPException(
                status_code=404,
                detail=f"Turn {turn} not found in call '{call_id}'",
            )
        return SeekModel(
            call_id=data["call_id"],
            turn_index=data["turn_index"],
            turn=_turn_to_model(data["turn"]),
        )

    async def get_failure_summary(self) -> dict:
        """
        Task 1 — failure detection across all calls with counts and sample call_ids.
        """
        _, all_summaries = await self._svc.list_calls(page=1, page_size=10000)
        
        # We need full observations — re-fetch
        from core.database import Database
        db = Database.get_db()
        
        taxonomy: dict[str, list[str]] = {
            "tool_failure":          [],
            "latency_spike":         [],
            "sentiment_crash":       [],
            "hallucination":         [],
            "topic_drift":           [],
            "incomplete_resolution": [],
        }

        async for doc in db["call_histories"].find({}):
            call_id  = doc["call_id"]
            obs      = doc.get("observations", [])
            failures = self._svc.classify_failures(obs)

            # incomplete_resolution: call ended with tool failures never resolved
            has_unresolved = any(
                o.get("tool_status") == "failure"
                for o in obs
            ) and not any(
                o.get("tool_status") == "success"
                for o in obs
            )
            if has_unresolved:
                failures.append("incomplete_resolution")

            for f in set(failures):
                if f in taxonomy:
                    taxonomy[f].append(call_id)

        return {
            "failure_counts": {k: len(v) for k, v in taxonomy.items()},
            "sample_call_ids": {k: v[:5] for k, v in taxonomy.items()},
        }
