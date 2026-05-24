"""
voice_obs_api/websocket/connection_manager.py

Manages all active WebSocket connections for the live monitoring feed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Thread-safe WebSocket connection pool."""

    def __init__(self):
        # call_id → set of websockets (supports multiple observers per call)
        self._call_subscribers: Dict[str, Set[WebSocket]] = {}
        # Global dashboard subscribers
        self._global_subscribers: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def subscribe_call(self, websocket: WebSocket, call_id: str) -> None:
        await websocket.accept()
        async with self._lock:
            if call_id not in self._call_subscribers:
                self._call_subscribers[call_id] = set()
            self._call_subscribers[call_id].add(websocket)
        logger.info("WS client subscribed to call_id=%s", call_id)

    async def subscribe_global(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._global_subscribers.add(websocket)
        logger.info("WS client subscribed to global monitor feed")

    async def unsubscribe_call(self, websocket: WebSocket, call_id: str) -> None:
        async with self._lock:
            subs = self._call_subscribers.get(call_id, set())
            subs.discard(websocket)
        logger.info("WS client unsubscribed from call_id=%s", call_id)

    async def unsubscribe_global(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._global_subscribers.discard(websocket)

    async def broadcast_to_call(self, call_id: str, message: dict) -> None:
        """Send message to all subscribers of a specific call."""
        async with self._lock:
            targets = list(self._call_subscribers.get(call_id, set()))

        dead: List[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        # Prune dead connections
        async with self._lock:
            for ws in dead:
                self._call_subscribers.get(call_id, set()).discard(ws)

    async def broadcast_global(self, message: dict) -> None:
        """Send message to all global monitor subscribers."""
        async with self._lock:
            targets = list(self._global_subscribers)

        dead: List[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        async with self._lock:
            for ws in dead:
                self._global_subscribers.discard(ws)

    @property
    def active_call_ids(self) -> List[str]:
        return list(self._call_subscribers.keys())

    @property
    def global_subscriber_count(self) -> int:
        return len(self._global_subscribers)


# Singleton shared across routers
manager = ConnectionManager()
