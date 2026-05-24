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
import numpy as np

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
        self._active_recordings: dict = {}

    # ------------------------------------------------------------------
    # Audio Decoding & Resampling Utility
    # ------------------------------------------------------------------

    def _decode_to_mono_pcm16_at_16khz(self, audio_bytes: bytes, component_type: str) -> np.ndarray:
        import io
        import soundfile as sf
        import numpy as np

        if component_type == "stt":
            # STT is user speech. If it doesn't start with RIFF (WAV header),
            # it is raw PCM from test_websocket.py. Bypassing soundfile auto-detection
            # avoids libmpg123 parsing it as MP3 and cropping it.
            if not audio_bytes.startswith(b"RIFF"):
                if len(audio_bytes) % 2 != 0:
                    audio_bytes = audio_bytes[:-1]
                return np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        try:
            # Attempt decoding with soundfile (supports WAV container, MP3, etc.)
            data, sr = sf.read(io.BytesIO(audio_bytes))
            if data.ndim > 1:
                # Downmix stereo/multi-channel to mono by averaging channels
                data = np.mean(data, axis=1)
            
            # Resample to 16000 Hz if needed
            if sr != 16000:
                duration = len(data) / sr
                num_samples = int(duration * 16000)
                src_indices = np.linspace(0, len(data) - 1, len(data))
                target_indices = np.linspace(0, len(data) - 1, num_samples)
                data = np.interp(target_indices, src_indices, data)
            return data.astype(np.float32)
        except Exception as e:
            logger.warning("Soundfile decoding failed, falling back to raw PCM 16-bit 16kHz mono: %s", e)
            # Fallback to raw 16-bit mono 16kHz PCM
            if len(audio_bytes) % 2 != 0:
                audio_bytes = audio_bytes[:-1]
            return np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    def _deduct_speech_emotion(self, pcm_data: np.ndarray, sr: int = 16000) -> str:
        """
        Real-time acoustic speech emotion detection using RMS energy, 
        Zero Crossing Rate (ZCR), and Autocorrelation-based Pitch (F0) tracking.
        """
        import numpy as np

        if len(pcm_data) < 100:
            return "neutral"

        # 1. RMS Energy (loudness indicator)
        rms = np.sqrt(np.mean(pcm_data ** 2))

        # 2. Zero Crossing Rate (tempo / turbulence indicator)
        zero_crossings = np.nonzero(np.diff(pcm_data > 0))[0]
        zcr = len(zero_crossings) / len(pcm_data) if len(pcm_data) > 0 else 0.0

        # 3. Fundamental Frequency (F0) using Autocorrelation Peak
        pitch = 120.0  # Fallback pitch (male/neutral F0)
        try:
            r = np.correlate(pcm_data, pcm_data, mode='full')
            half = len(r) // 2
            r = r[half:]
            
            # Focus on human speech pitch range lag [40, 200] samples
            lag_start, lag_end = 40, min(200, len(r))
            if lag_end > lag_start:
                peak_lag = np.argmax(r[lag_start:lag_end]) + lag_start
                if r[peak_lag] > 0.3 * r[0]:  # Ensure peak is strong/voiced
                    pitch = sr / peak_lag
        except Exception:
            pass

        # 4. Emotion Deduction rules:
        # - High energy (RMS > 0.12) & high/variable pitch (F0 > 200 Hz) or fast tempo (ZCR > 0.15) -> frustrated/agitated
        # - High energy (RMS > 0.10) & high/variable pitch -> excited
        # - Extremely low energy (RMS < 0.015) -> calm
        # - Stable average values -> neutral
        if rms > 0.12:
            if pitch > 200.0 or zcr > 0.15:
                return "frustrated"
            else:
                return "excited"
        elif rms > 0.08:
            if pitch > 180.0:
                return "excited"
            else:
                return "neutral"
        elif rms < 0.015:
            return "calm"
        else:
            return "neutral"

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
        try:
            await self.start()
            self._register_signal_handlers()
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
        
        # Check if call recording is requested
        if getattr(event, "user_call_recording", True):
            if event.call_id not in self._active_recordings:
                self._active_recordings[event.call_id] = {
                    "user_id": event.user_id,
                    "call_start_ms": event.initiated_at,
                    "segments": []
                }
            else:
                # Update user_id and call_start_ms since it might have been lazily initialized
                self._active_recordings[event.call_id]["user_id"] = event.user_id
                self._active_recordings[event.call_id]["call_start_ms"] = event.initiated_at
            logger.info("Call recording enabled and configured for call_id=%s user_id=%s", event.call_id, event.user_id)
        else:
            # If recording is explicitly disabled, drop any lazily-recorded segments
            self._active_recordings.pop(event.call_id, None)
            logger.info("Call recording explicitly disabled for call_id=%s", event.call_id)

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
            "tool_name": event.tool_name,
            "tool_input": event.tool_input,
            "tool_output": event.tool_output,
            "tool_status": event.tool_status,
            "detected_emotion": event.detected_emotion,
        }

        # Handle recording & real-time audio emotion deduction
        if getattr(event, "audio_b64", None):
            if event.call_id not in self._active_recordings:
                # Lazily initialize: default to "user_12345" which will be updated when call_init arrives
                self._active_recordings[event.call_id] = {
                    "user_id": "user_12345",
                    "call_start_ms": event.timestamp.start_time,
                    "segments": []
                }
                logger.info("Lazily initialized recording session for call_id=%s on observation", event.call_id)
            
            try:
                import base64
                audio_bytes = base64.b64decode(event.audio_b64)
                pcm_data = self._decode_to_mono_pcm16_at_16khz(audio_bytes, event.component_type.value)
                if len(pcm_data) > 0:
                    self._active_recordings[event.call_id]["segments"].append({
                        "start_time": event.timestamp.start_time,
                        "pcm_data": pcm_data
                    })
                    logger.info("Appended recorded segment for call_id=%s, start_time=%d, length=%d",
                                event.call_id, event.timestamp.start_time, len(pcm_data))
                    
                    # Run real-time Speech Emotion Deduction for User turns (STT)
                    if event.component_type.value == "stt":
                        detected = self._deduct_speech_emotion(pcm_data)
                        observation["detected_emotion"] = detected
                        logger.info("Real-time Audio Emotion detected: %s", detected)
            except Exception as exc:
                logger.error("Failed to process audio segment for call_id=%s: %s", event.call_id, exc)

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

        # Finalize call recording if active
        if event.call_id in self._active_recordings:
            try:
                recording = self._active_recordings.pop(event.call_id)
                user_id = recording["user_id"]
                segments = recording["segments"]
                call_start_ms = recording.get("call_start_ms")
                
                if segments:
                    import os
                    import numpy as np
                    import soundfile as sf
                    
                    # Sort segments chronologically to ensure correct user-assistant turn order
                    segments.sort(key=lambda s: s["start_time"])
                    
                    # Determine actual start of call
                    earliest_segment_start = segments[0]["start_time"]
                    if not call_start_ms:
                        call_start_ms = earliest_segment_start
                    else:
                        call_start_ms = min(call_start_ms, earliest_segment_start)
                        
                    # Calculate end time of call based on last segment or call close event
                    last_segment_end = earliest_segment_start
                    for s in segments:
                        # 16000 samples per second = 16 samples per millisecond
                        duration_ms = int(len(s["pcm_data"]) / 16.0)
                        seg_end = s["start_time"] + duration_ms
                        if seg_end > last_segment_end:
                            last_segment_end = seg_end
                            
                    call_end_ms = event.closed_at
                    call_end_ms = max(call_end_ms, last_segment_end)
                    
                    total_duration_ms = call_end_ms - call_start_ms
                    if total_duration_ms <= 0:
                        total_duration_ms = 1000
                        
                    total_samples = int((total_duration_ms / 1000.0) * 16000)
                    full_pcm = np.zeros(total_samples, dtype=np.float32)
                    
                    for s in segments:
                        rel_start_ms = s["start_time"] - call_start_ms
                        if rel_start_ms < 0:
                            rel_start_ms = 0
                            
                        start_sample = int((rel_start_ms / 1000.0) * 16000)
                        pcm_data = s["pcm_data"]
                        end_sample = start_sample + len(pcm_data)
                        
                        # Pad full_pcm if segment exceeds current size
                        if end_sample > len(full_pcm):
                            padding = np.zeros(end_sample - len(full_pcm), dtype=np.float32)
                            full_pcm = np.concatenate([full_pcm, padding])
                            
                        # Overlay segment (additive mixing avoids overwriting overlapping speech)
                        full_pcm[start_sample:end_sample] += pcm_data
                        
                    # Clip to prevent digital distortion/clipping
                    full_pcm = np.clip(full_pcm, -1.0, 1.0)
                    
                    # Directory format: call_recording/<user_id>/<call_id>.wav
                    dir_path = os.path.join("call_recording", user_id)
                    os.makedirs(dir_path, exist_ok=True)
                    file_path = os.path.join(dir_path, f"{event.call_id}.wav")
                    
                    # Write WAV file cleanly
                    sf.write(file_path, full_pcm, 16000, subtype="PCM_16")
                    logger.info("Saved call recording for user_id=%s call_id=%s at %s (duration: %.2fs)", 
                                user_id, event.call_id, file_path, len(full_pcm)/16000.0)
                else:
                    logger.info("No audio segments captured for call_id=%s, skipping recording write", event.call_id)
            except Exception as exc:
                logger.error("Failed to save final call recording for call_id=%s: %s", event.call_id, exc)

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
