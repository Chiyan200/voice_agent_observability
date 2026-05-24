"""
voice_obs_api/services/monitor_service.py

Simulates a live call stream and detects anomalies in real-time.
In production this would consume from Kafka instead.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from websocket.connection_manager import manager

logger = logging.getLogger(__name__)

COLL_CALLS    = "call_histories"
COLL_ANALYSIS = "post_call_analyses"

# Thresholds
LATENCY_WARNING_MS  = 2000
LATENCY_CRITICAL_MS = 4000
FRUSTRATION_WARNING = 0.5
FRUSTRATION_CRITICAL = 0.75


class MonitorService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._calls    = db[COLL_CALLS]
        self._analysis = db[COLL_ANALYSIS]
        self._streaming = False

    # ── Anomaly Detection ──────────────────────────────────────────────────────

    def _detect_anomalies(
        self,
        call_id: str,
        observations: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Scan observations for anomalies and return event dicts.
        """
        from services.calls_service import CallsService
        turns = CallsService._enrich_with_latency(observations)

        events = []
        now_ms = int(time.time() * 1000)

        for t in turns:
            lat = t.get("latency_ms") or 0

            if lat >= LATENCY_CRITICAL_MS:
                events.append({
                    "event_type": "anomaly",
                    "call_id":    call_id,
                    "severity":   "critical",
                    "message":    f"Critical latency spike: {lat} ms at turn {t['turn_index']}",
                    "payload":    {"latency_ms": lat, "turn_index": t["turn_index"], "turn_id": t["turn_id"]},
                    "timestamp_ms": now_ms,
                })
            elif lat >= LATENCY_WARNING_MS:
                events.append({
                    "event_type": "anomaly",
                    "call_id":    call_id,
                    "severity":   "warning",
                    "message":    f"High latency: {lat} ms at turn {t['turn_index']}",
                    "payload":    {"latency_ms": lat, "turn_index": t["turn_index"]},
                    "timestamp_ms": now_ms,
                })

            if t.get("tool_status") == "failure":
                events.append({
                    "event_type": "anomaly",
                    "call_id":    call_id,
                    "severity":   "critical",
                    "message":    f"Tool failure: {t['tool_name']} → {t['tool_output']}",
                    "payload":    {
                        "tool_name":   t["tool_name"],
                        "tool_input":  t["tool_input"],
                        "tool_output": t["tool_output"],
                        "turn_index":  t["turn_index"],
                    },
                    "timestamp_ms": now_ms,
                })

            if t.get("detected_emotion") == "frustrated":
                events.append({
                    "event_type": "anomaly",
                    "call_id":    call_id,
                    "severity":   "warning",
                    "message":    f"User frustration detected at turn {t['turn_index']}",
                    "payload":    {"emotion": "frustrated", "turn_index": t["turn_index"]},
                    "timestamp_ms": now_ms,
                })

        return events

    # ── Live stream simulator ──────────────────────────────────────────────────

    async def stream_call_live(self, call_id: str) -> None:
        """
        Replay a stored call turn-by-turn with realistic timing,
        broadcasting anomalies via WebSocket as they are discovered.
        """
        doc = await self._calls.find_one({"call_id": call_id})
        if not doc:
            await manager.broadcast_to_call(call_id, {
                "event_type": "error",
                "call_id":    call_id,
                "severity":   "critical",
                "message":    f"Call {call_id} not found",
                "payload":    {},
                "timestamp_ms": int(time.time() * 1000),
            })
            return

        observations = doc.get("observations", [])

        # Broadcast call_start
        await manager.broadcast_to_call(call_id, {
            "event_type": "call_start",
            "call_id":    call_id,
            "severity":   "info",
            "message":    f"Live replay started for call {call_id}",
            "payload":    {"total_turns": len(observations), "call_type": doc.get("call_type")},
            "timestamp_ms": int(time.time() * 1000),
        })
        await manager.broadcast_global({
            "event_type": "call_start",
            "call_id":    call_id,
            "severity":   "info",
            "message":    f"Call {call_id} started streaming",
            "payload":    {},
            "timestamp_ms": int(time.time() * 1000),
        })

        from services.calls_service import CallsService
        turns = CallsService._enrich_with_latency(observations)

        for turn in turns:
            # Simulate realistic pacing (capped to 1 s for demo)
            delay = min(turn["duration_ms"] / 1000.0, 1.0)
            await asyncio.sleep(delay)

            # Broadcast the observation
            obs_event = {
                "event_type": "observation",
                "call_id":    call_id,
                "severity":   "info",
                "message":    f"[{turn['role'].upper()}] {turn['type']}: {turn['content'][:80]}",
                "payload":    turn,
                "timestamp_ms": int(time.time() * 1000),
            }
            await manager.broadcast_to_call(call_id, obs_event)

            # Detect and broadcast anomalies for THIS turn
            single_turn_anomalies = self._detect_anomalies(call_id, [observations[turn["turn_index"]]])
            for anom in single_turn_anomalies:
                await manager.broadcast_to_call(call_id, anom)
                await manager.broadcast_global(anom)

        # Broadcast call_end
        end_event = {
            "event_type": "call_end",
            "call_id":    call_id,
            "severity":   "info",
            "message":    f"Call {call_id} replay complete",
            "payload":    {"call_duration": doc.get("call_duration")},
            "timestamp_ms": int(time.time() * 1000),
        }
        await manager.broadcast_to_call(call_id, end_event)
        await manager.broadcast_global(end_event)

    async def scan_all_calls_for_anomalies(self) -> List[Dict[str, Any]]:
        """
        One-shot scan of all stored calls — used for the /monitor/anomalies REST endpoint.
        """
        all_events: List[Dict[str, Any]] = []
        async for doc in self._calls.find({}):
            call_id = doc["call_id"]
            obs     = doc.get("observations", [])
            events  = self._detect_anomalies(call_id, obs)
            all_events.extend(events)
        return all_events
