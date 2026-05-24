"""
tests/test_call_flow_integration.py

Integration test — simulates a full WebSocket session end-to-end.

Flow:
    WebSocket session (this file)
        └─► CallEventPublisher   [client/]
                └─► Kafka topics
                        └─► CallEventConsumer  [server/]  ← run separately
                                └─► CallHistoryRepository
                                        └─► MongoDB

Run:
    # Terminal 1 — start the consumer service
    python -m server.main

    # Terminal 2 — run this test
    python -m tests.test_call_flow_integration
"""

import asyncio
import logging

from client.call_event_publisher import CallEventPublisher
from shared.models.events import CallType, ComponentType, RoleType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mock pipeline engines — identical behaviour to original test
# ---------------------------------------------------------------------------

async def mock_stt_engine() -> str:
    logger.info("[STT] Converting audio to text...")
    await asyncio.sleep(1)
    return "Check account balance"


async def mock_tool_call_engine() -> str:
    logger.info("[ToolCall] Executing function...")
    await asyncio.sleep(2)
    return "Function call completed successfully."


async def mock_llm_engine(
    publisher: CallEventPublisher,
    call_id: str,
    turn_id: str,
) -> str:
    logger.info("[LLM] Generating response...")
    await asyncio.sleep(2)

    # Nested tool_call observation inside LLM block
    async with publisher.track(
        call_id=call_id,
        turn_id=turn_id,
        component_type=ComponentType.TOOL_CALL,
        role=RoleType.ASSISTANT,
    ) as ctx:
        result = await mock_tool_call_engine()
        ctx["content"] = result

    return "Your current checking account balance is $1,250."


# ---------------------------------------------------------------------------
# Simulated WebSocket session
# ---------------------------------------------------------------------------

def generate_mock_wav_base64(frequency=440, duration_sec=0.5, sr=16000):
    import io
    import numpy as np
    import soundfile as sf
    import base64
    
    t = np.linspace(0, duration_sec, int(sr * duration_sec))
    data = 0.5 * np.sin(2 * np.pi * frequency * t)
    
    wav_io = io.BytesIO()
    sf.write(wav_io, data, sr, format="WAV", subtype="PCM_16")
    return base64.b64encode(wav_io.getvalue()).decode('utf-8')


async def simulate_websocket_session() -> None:
    CALL_ID = "call_integration_test_001"
    TURN_ID = "turn_001"

    publisher = CallEventPublisher(bootstrap_servers="localhost:9092")
    await publisher.start()

    import time
    call_start_ms = int(time.time() * 1000)

    # ── WebSocket OPEN ───────────────────────────────────────────────────
    logger.info("=== STEP 1: WebSocket OPEN ===")
    await publisher.emit_call_started(
        call_id=CALL_ID,
        user_id="user_77",
        call_type=CallType.WEB_AGENT,
        user_call_recording=True,
    )

    # ── STT ─────────────────────────────────────────────────────────────
    logger.info("=== STEP 2: STT ===")
    async with publisher.track(
        call_id=CALL_ID,
        turn_id=TURN_ID,
        component_type=ComponentType.STT,
        role=RoleType.USER,
    ) as ctx:
        transcript = await mock_stt_engine()
        ctx["content"] = transcript
        ctx["audio_b64"] = generate_mock_wav_base64(frequency=440, duration_sec=0.5, sr=16000)

    logger.info("STT result: '%s'", transcript)

    # ── LLM (with nested tool_call) ──────────────────────────────────────
    logger.info("=== STEP 3: LLM ===")
    async with publisher.track(
        call_id=CALL_ID,
        turn_id=TURN_ID,
        component_type=ComponentType.LLM,
        role=RoleType.ASSISTANT,
    ) as ctx:
        response = await mock_llm_engine(publisher, CALL_ID, TURN_ID)
        ctx["content"] = response

    logger.info("LLM result: '%s'", response)

    # ── TTS ─────────────────────────────────────────────────────────────
    logger.info("=== STEP 3.5: TTS ===")
    async with publisher.track(
        call_id=CALL_ID,
        turn_id=TURN_ID,
        component_type=ComponentType.TTS,
        role=RoleType.ASSISTANT,
    ) as ctx:
        logger.info("[TTS] Converting text to audio...")
        await asyncio.sleep(1)
        ctx["content"] = response
        ctx["audio_b64"] = generate_mock_wav_base64(frequency=880, duration_sec=0.5, sr=24000)

    # ── WebSocket CLOSE ──────────────────────────────────────────────────
    logger.info("=== STEP 4: WebSocket CLOSE ===")
    await asyncio.sleep(1)
    await publisher.emit_call_ended(call_id=CALL_ID, call_start_ms=call_start_ms)

    await publisher.stop()
    logger.info("✅ Session complete. Check server.main logs for DB writes.")


if __name__ == "__main__":
    asyncio.run(simulate_websocket_session())
