"""
voice_obs_api/api/routers/monitor.py

Live monitoring endpoints:
  GET  /monitor/anomalies                    — one-shot anomaly scan (REST)
  WS   /monitor/ws                           — global live feed (all calls)
  WS   /monitor/ws/{call_id}                 — per-call live feed
  POST /monitor/simulate/{call_id}           — trigger a live replay simulation
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, BackgroundTasks

from core.database import Database
from services.monitor_service import MonitorService
from websocket.connection_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_monitor_service() -> MonitorService:
    db = Database.get_db()
    return MonitorService(db)


# ── REST ───────────────────────────────────────────────────────────────────────

@router.get("/anomalies", summary="One-shot anomaly scan across all calls")
async def get_anomalies(svc: MonitorService = Depends(_get_monitor_service)):
    """
    Scans all stored calls and returns all detected anomaly events.
    Use this for historical anomaly review; WebSocket endpoints for live feed.
    """
    events = await svc.scan_all_calls_for_anomalies()
    return {
        "total_anomalies": len(events),
        "events": events,
    }


@router.post(
    "/simulate/{call_id}",
    summary="Trigger live replay simulation for a call",
)
async def simulate_call(
    call_id:    str,
    background: BackgroundTasks,
    svc:        MonitorService = Depends(_get_monitor_service),
):
    """
    Replays a stored call turn-by-turn with realistic pacing.
    Connect to WS /monitor/ws/{call_id} first to receive events.
    """
    background.add_task(svc.stream_call_live, call_id)
    return {
        "message": f"Simulation started for call_id={call_id}. "
                   f"Connect to ws://<host>/monitor/ws/{call_id} to receive events.",
    }


# ── WebSocket — per-call ───────────────────────────────────────────────────────

@router.websocket("/ws/{call_id}")
async def websocket_call(websocket: WebSocket, call_id: str):
    """
    Real-time feed for a single call.
    Connect BEFORE calling POST /monitor/simulate/{call_id}.

    Message schema: LiveEventModel
    {
      "event_type": "observation" | "anomaly" | "call_start" | "call_end" | "error",
      "call_id":    str,
      "severity":   "info" | "warning" | "critical",
      "message":    str,
      "payload":    {...},
      "timestamp_ms": int
    }
    """
    await manager.subscribe_call(websocket, call_id)
    try:
        while True:
            # Keep connection alive; server is the broadcaster
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.unsubscribe_call(websocket, call_id)
        logger.info("Client disconnected from call feed call_id=%s", call_id)


# ── WebSocket — global ─────────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_global(websocket: WebSocket):
    """
    Global monitoring feed — receives anomaly and call lifecycle events
    across ALL active calls. Ideal for the monitoring dashboard.

    Message schema: same as per-call WS above.
    """
    await manager.subscribe_global(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.unsubscribe_global(websocket)
        logger.info("Client disconnected from global monitor feed")
