"""
server/consumers/call_event_consumer.py

SERVER SIDE — Long-running Kafka consumer that writes events to MongoDB.

Industry pattern: Consumer Group with manual error handling.
  - Each message type routes to a dedicated handler method
  - Pydantic validation on every incoming message
  - Dead-letter logging on parse or DB failure (no silent drops)
  - Graceful shutdown on Ctrl+C (Windows + Linux compatible)
"""

from __future__ import annotations

import json
import asyncio
import logging
import signal
import sys
from typing import Optional

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from aiokafka.errors import KafkaError
from pydantic import ValidationError

from shared.config.topics import ALL_TOPICS
from shared.models.events import (
    EventType,
    CallInitEvent,
    ObservationEvent,
    CallCloseEvent,
)
from shared.models.documents import ObservationDict, TimestampDict
from server.db.call_history_repository import CallHistoryRepository

logger = logging.getLogger(__name__)


class CallEventConsumer:
    """
    Kafka consumer that persists voice agent events to MongoDB.

    Run as a standalone service:
        consumer = CallEventConsumer()
        await consumer.run()
    """

    CONSUMER_GROUP_ID = "voice-agent-observability-writer"

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        mongo_uri: str = "mongodb://localhost:27017/",
        db_name: str = "voice_agent_obs",
    ):
        self._bootstrap_servers = bootstrap_servers
        self._repository = CallHistoryRepository(uri=mongo_uri, db_name=db_name)
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            *ALL_TOPICS,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self.CONSUMER_GROUP_ID,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            auto_commit_interval_ms=1000,
            max_poll_records=100,
        )
        await self._consumer.start()
        self._running = True
        logger.info(
            "CallEventConsumer started group=%s topics=%s",
            self.CONSUMER_GROUP_ID, ALL_TOPICS,
        )

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("CallEventConsumer stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start consuming. Blocks until Ctrl+C or process exits."""
        await self.start()
        self._register_signal_handlers()

        try:
            async for record in self._consumer:
                if not self._running:
                    break
                await self._dispatch(record)
        except KafkaError as exc:
            logger.error("Kafka error in consumer loop: %s", exc)
        except asyncio.CancelledError:
            logger.info("Consumer loop cancelled — shutting down")
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    async def _dispatch(self, record: ConsumerRecord) -> None:
        payload: dict = record.value
        event_type = payload.get("event")

        try:
            if event_type == EventType.CALL_INIT:
                await self._handle_call_init(CallInitEvent(**payload))

            elif event_type == EventType.OBSERVATION:
                await self._handle_observation(ObservationEvent(**payload))

            elif event_type == EventType.CALL_CLOSE:
                await self._handle_call_close(CallCloseEvent(**payload))

            else:
                logger.warning("Unknown event type=%s partition=%d offset=%d",
                               event_type, record.partition, record.offset)

        except (ValidationError, KeyError) as exc:
            # Dead-letter: log and continue — never crash the consumer loop
            logger.error(
                "Schema validation failed event_type=%s offset=%d error=%s payload=%s",
                event_type, record.offset, exc, payload,
            )
        except Exception as exc:
            logger.error(
                "Unexpected error handling event_type=%s offset=%d error=%s",
                event_type, record.offset, exc,
            )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_call_init(self, event: CallInitEvent) -> None:
        await self._repository.upsert_call(
            call_id=event.call_id,
            user_id=event.user_id,
            call_type=event.call_type.value,
        )
        logger.info("call_init persisted call_id=%s user_id=%s", event.call_id, event.user_id)

    async def _handle_observation(self, event: ObservationEvent) -> None:
        observation: ObservationDict = {
            "turn_id": event.turn_id,
            "type": event.component_type.value,
            "role": event.role.value,
            "duration_ms": event.duration_ms,
            "timestamp": TimestampDict(
                start_time=event.timestamp.start_time,
                end_time=event.timestamp.end_time,
            ),
            "content": event.content,
        }
        success = await self._repository.append_observation(event.call_id, observation)
        logger.info(
            "observation persisted call_id=%s component=%s duration_ms=%d success=%s",
            event.call_id, event.component_type, event.duration_ms, success,
        )

    async def _handle_call_close(self, event: CallCloseEvent) -> None:
        success = await self._repository.set_call_duration(
            call_id=event.call_id,
            duration_sec=event.call_duration_sec,
        )
        logger.info(
            "call_close persisted call_id=%s duration=%ds success=%s",
            event.call_id, event.call_duration_sec, success,
        )

    # ------------------------------------------------------------------
    # Graceful shutdown — Windows + Linux compatible
    # ------------------------------------------------------------------

    def _register_signal_handlers(self) -> None:
        if sys.platform == "win32":
            # Windows: signal module works but loop.add_signal_handler does not.
            # Use the default KeyboardInterrupt (Ctrl+C) instead.
            signal.signal(signal.SIGINT, self._sync_signal_handler)
            signal.signal(signal.SIGTERM, self._sync_signal_handler)
        else:
            # Linux / macOS: use asyncio's native signal handler
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(
                    sig,
                    lambda: asyncio.create_task(self.stop()),
                )

    def _sync_signal_handler(self, signum, frame) -> None:
        logger.info("Shutdown signal received (signal=%d) — stopping consumer", signum)
        self._running = False
