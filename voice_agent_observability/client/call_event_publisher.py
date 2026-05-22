"""
client/call_event_publisher.py

CLIENT SIDE — Installed in your WebSocket / voice agent service.

Responsibilities:
  - Time each pipeline component (STT, LLM, TTS, tool_call)
  - Publish structured, validated events to Kafka
  - Never touches MongoDB directly

Industry pattern: Thin event emitter. No business logic. Fire-and-forget
with at-least-once delivery guarantee via send_and_wait().
"""

from __future__ import annotations

import json
import time
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from shared.config.topics import TOPIC_CALL_INIT, TOPIC_CALL_OBSERVATION, TOPIC_CALL_CLOSE
from shared.models.events import (
    CallInitEvent,
    ObservationEvent,
    CallCloseEvent,
    CallType,
    ComponentType,
    RoleType,
    TimestampMs,
)

logger = logging.getLogger(__name__)


class CallEventPublisher:
    """
    Publishes voice agent lifecycle events to Kafka.

    Usage (in your WebSocket handler):

        publisher = CallEventPublisher(bootstrap_servers="localhost:9092")
        await publisher.start()

        await publisher.emit_call_started(call_id, user_id, CallType.WEB_AGENT)

        async with publisher.track("call_id", "turn_001", ComponentType.STT, RoleType.USER) as ctx:
            transcript = await stt_engine.transcribe(audio)
            ctx["content"] = transcript

        await publisher.emit_call_ended(call_id, call_start_ms)
        await publisher.stop()
    """

    def __init__(self, bootstrap_servers: str = "localhost:9092"):
        self._bootstrap_servers = bootstrap_servers
        self._producer: Optional[AIOKafkaProducer] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the Kafka producer. Call once on WebSocket connect."""
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks="all",                    # Wait for all replicas
            enable_idempotence=True,       # Exactly-once producer semantics
            compression_type="gzip",       # Compress payloads
            max_batch_size=16384,
            linger_ms=5,                   # Small batching window
        )
        await self._producer.start()
        logger.info("CallEventPublisher started → brokers=%s", self._bootstrap_servers)

    async def stop(self) -> None:
        """Flush and close the producer. Call once on WebSocket disconnect."""
        if self._producer:
            await self._producer.stop()
            logger.info("CallEventPublisher stopped")

    # ------------------------------------------------------------------
    # Public emit methods
    # ------------------------------------------------------------------

    async def emit_call_started(
        self,
        call_id: str,
        user_id: str,
        call_type: CallType,
    ) -> None:
        """Emit when WebSocket connection opens."""
        event = CallInitEvent(
            call_id=call_id,
            user_id=user_id,
            call_type=call_type,
        )
        await self._publish(TOPIC_CALL_INIT, call_id, event.model_dump())
        logger.info("emit_call_started call_id=%s", call_id)

    async def emit_call_ended(
        self,
        call_id: str,
        call_start_ms: int,
    ) -> None:
        """Emit when WebSocket connection closes."""
        end_ms = int(time.time() * 1000)
        event = CallCloseEvent(
            call_id=call_id,
            call_duration_sec=int((end_ms - call_start_ms) / 1000),
        )
        await self._publish(TOPIC_CALL_CLOSE, call_id, event.model_dump())
        logger.info("emit_call_ended call_id=%s duration=%ds", call_id, event.call_duration_sec)

    # ------------------------------------------------------------------
    # Context manager — times a pipeline component block
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def track(
        self,
        call_id: str,
        turn_id: str,
        component_type: ComponentType,
        role: RoleType,
        content: str = "",
    ) -> AsyncIterator[dict]:
        """
        Times a pipeline block and emits an ObservationEvent on exit.

        async with publisher.track(call_id, turn_id, ComponentType.STT, RoleType.USER) as ctx:
            transcript = await stt_engine.transcribe(audio)
            ctx["content"] = transcript          # ← set output before exiting
        """
        start_ms = int(time.time() * 1000)
        ctx: dict = {"content": content}

        try:
            yield ctx
        finally:
            end_ms = int(time.time() * 1000)
            event = ObservationEvent(
                call_id=call_id,
                turn_id=turn_id,
                component_type=component_type,
                role=role,
                content=ctx["content"],
                duration_ms=end_ms - start_ms,
                timestamp=TimestampMs(start_time=start_ms, end_time=end_ms),
            )
            await self._publish(TOPIC_CALL_OBSERVATION, call_id, event.model_dump())
            logger.debug(
                "track emitted component=%s duration_ms=%d call_id=%s",
                component_type, event.duration_ms, call_id,
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _publish(self, topic: str, key: str, payload: dict) -> None:
        if self._producer is None:
            raise RuntimeError("CallEventPublisher is not started. Call await publisher.start() first.")
        try:
            await self._producer.send_and_wait(topic, value=payload, key=key)
        except KafkaError as exc:
            logger.error("Failed to publish to topic=%s key=%s error=%s", topic, key, exc)
            raise
