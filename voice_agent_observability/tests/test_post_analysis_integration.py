"""
tests/test_post_analysis_integration.py

Integration test for verifying the PostCallAnalyzer service.
"""

import io
import os
import sys
import base64
import asyncio
import logging
from datetime import datetime
import time
import json
from pymongo import MongoClient

# Configure path so imports work correctly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from client.call_event_publisher import CallEventPublisher
from shared.models.events import CallType, ComponentType, RoleType
from server.services.post_call_analyzer import PostCallAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def generate_mock_wav_bytes(frequency=440, duration_sec=0.5, sr=16000):
    import numpy as np
    import soundfile as sf
    t = np.linspace(0, duration_sec, int(sr * duration_sec))
    data = 0.5 * np.sin(2 * np.pi * frequency * t)
    wav_io = io.BytesIO()
    sf.write(wav_io, data, sr, format="WAV", subtype="PCM_16")
    return wav_io.getvalue()


async def run_mock_call_flow():
    CALL_ID = "call_post_analysis_test_001"
    USER_ID = "user_99"
    
    logger.info("Initializing event publisher...")
    publisher = CallEventPublisher(bootstrap_servers="localhost:9092")
    await publisher.start()
    
    # ── Call Started ──────────────────────────────────────────────────────
    logger.info("Sending CALL_INIT...")
    await publisher.emit_call_started(
        call_id=CALL_ID,
        user_id=USER_ID,
        call_type=CallType.WEB_AGENT,
        user_call_recording=True,
    )
    await asyncio.sleep(1.0)
    
    # ── STT (User speaks with raw WAV bytes) ──────────────────────────────
    logger.info("Sending STT observation...")
    user_wav = generate_mock_wav_bytes(frequency=300, duration_sec=1.5, sr=16000)
    async with publisher.track(
        call_id=CALL_ID,
        turn_id="turn_001",
        component_type=ComponentType.STT,
        role=RoleType.USER,
    ) as ctx:
        ctx["content"] = "Can you check if my account is open?"
        ctx["audio_b64"] = base64.b64encode(user_wav).decode('utf-8')
        
    await asyncio.sleep(1.0)

    # ── LLM (AI Processes) ────────────────────────────────────────────────
    logger.info("Sending LLM observation...")
    async with publisher.track(
        call_id=CALL_ID,
        turn_id="turn_001",
        component_type=ComponentType.LLM,
        role=RoleType.ASSISTANT,
    ) as ctx:
        ctx["content"] = "Yes, your account is fully active and open."
        
    await asyncio.sleep(1.0)

    # ── TTS (AI Speaks back) ──────────────────────────────────────────────
    logger.info("Sending TTS observation...")
    ai_wav = generate_mock_wav_bytes(frequency=440, duration_sec=1.0, sr=24000)
    async with publisher.track(
        call_id=CALL_ID,
        turn_id="turn_001",
        component_type=ComponentType.TTS,
        role=RoleType.ASSISTANT,
    ) as ctx:
        ctx["content"] = "Yes, your account is fully active and open."
        ctx["audio_b64"] = base64.b64encode(ai_wav).decode('utf-8')

    await asyncio.sleep(1.0)

    # ── Call Closed ───────────────────────────────────────────────────────
    logger.info("Sending CALL_CLOSE...")
    await publisher.emit_call_ended(call_id=CALL_ID, call_start_ms=int(time.time()*1000) - 5000)
    
    await publisher.stop()
    logger.info("Mock call flow completed and closed.")


async def verify_analysis_stored():
    logger.info("Connecting to MongoDB to check generated report...")
    client = MongoClient("mongodb://localhost:27017/")
    db = client["voice_agent_obs"]
    collection = db["post_call_analyses"]
    
    for attempt in range(1, 11):
        logger.info(f"Checking MongoDB collection for call analysis (attempt {attempt}/10)...")
        doc = collection.find_one({"call_id": "call_post_analysis_test_001"})
        if doc:
            logger.info("🎉 SUCCESS! Post-call analysis found in database!")
            print("\n" + "=" * 60)
            print("MongoDB post_call_analyses Document:")
            print("=" * 60)
            print(json.dumps(doc, indent=2, default=str))
            print("=" * 60 + "\n")
            return True
        await asyncio.sleep(2.0)
        
    logger.error("❌ TIMEOUT: Post-call analysis report was not found in MongoDB.")
    return False


async def main():
    import time
    
    logger.info("=== STEP 1: Starting Standalone PostCallAnalyzer Service ===")
    analyzer = PostCallAnalyzer()
    await analyzer.start()
    
    # Run analyzer consumer loop as a background task
    loop_task = asyncio.create_task(analyzer.run())
    await asyncio.sleep(2.0)
    
    logger.info("=== STEP 2: Running Simulated Call Flow ===")
    await run_mock_call_flow()
    
    # Let the analyzer fetch and process the close event
    logger.info("Waiting for Analyzer to process close event and LLM evaluate...")
    await asyncio.sleep(8.0)
    
    logger.info("=== STEP 3: Verifying MongoDB Results ===")
    success = await verify_analysis_stored()
    
    logger.info("Cleaning up services...")
    await analyzer.stop()
    loop_task.cancel()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
