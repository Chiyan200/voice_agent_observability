import asyncio
import json
import os
import logging
import io
import base64
import time
import sys
import uuid
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, WebSocket, HTTPException, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import requests
import numpy as np
from faster_whisper import WhisperModel
from gtts import gTTS

# Dynamic path configuration for voice agent observability module
OBS_DIR = Path(__file__).parent.parent / "voice_agent_observability"
if str(OBS_DIR) not in sys.path:
    sys.path.append(str(OBS_DIR))

try:
    from client.call_event_publisher import CallEventPublisher
    from shared.models.events import CallType, ComponentType, RoleType
except ImportError as e:
    _observability_import_error = e
else:
    _observability_import_error = None

# --- Structured Logging Configuration ---
class JSONFormatter(logging.Formatter):
    """Custom formatter to output logs as structured JSON."""
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            log_obj.update(record.extra_data)
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("voice_agent")

if _observability_import_error:
    logger.warning("Could not import observability components. Observability will be disabled.", extra={"extra_data": {"error": str(_observability_import_error)}})
else:
    logger.info("Successfully imported observability publisher and models")

# Suppress noisy third-party logs
logging.getLogger("faster_whisper").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

load_dotenv()

app = FastAPI(title="Local Voice Agent with LiveKit")
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

# Configuration
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny")
SAMPLE_RATE = 16000

# Initialize Whisper
logger.info("Initializing system", extra={"extra_data": {"whisper_model": WHISPER_MODEL, "ollama_model": OLLAMA_MODEL}})
try:
    whisper_model = WhisperModel(WHISPER_MODEL, device="cuda", compute_type="float16")
    logger.info("Whisper loaded successfully", extra={"extra_data": {"device": "cuda"}})
except Exception as e:
    logger.warning("CUDA unavailable, falling back to CPU", extra={"extra_data": {"error": str(e)}})
    whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

# Text-to-Speech configuration
TTS_LANGUAGE = "en"  # Can be changed to other language codes
TTS_SLOW = False     # Set True for slower speech

def text_to_audio(text: str) -> Optional[bytes]:
    """Convert text to audio bytes using Google Text-to-Speech (neural quality)."""
    if not text or len(text.strip()) == 0:
        return None
    
    try:
        # Use gTTS for neural quality voices
        tts = gTTS(text=text, lang=TTS_LANGUAGE, slow=TTS_SLOW, tld="com")
        
        # Save to bytes buffer
        audio_buffer = io.BytesIO()
        tts.write_to_fp(audio_buffer)
        audio_bytes = audio_buffer.getvalue()
        
        logger.info("Text-to-Speech conversion successful", extra={"extra_data": {
            "text_length": len(text),
            "audio_size_kb": round(len(audio_bytes) / 1024, 2),
            "language": TTS_LANGUAGE
        }})
        
        return audio_bytes
    except Exception as e:
        logger.error("Text-to-Speech conversion failed", extra={"extra_data": {"error": str(e), "text": text[:100]}})
        return None


def transcribe_audio(audio_bytes: bytes) -> Optional[str]:
    """Convert audio bytes to text using Whisper."""
    if len(audio_bytes) < 44:
        return None
    
    try:
        # First attempt: Try decoding as a valid media file
        audio_file = io.BytesIO(audio_bytes)
        segments, _ = whisper_model.transcribe(audio_file, language="en", beam_size=5)
        text = "".join([segment.text for segment in segments]).strip()
    except Exception:
        # Second attempt: Raw PCM 16-bit 16kHz mono audio fallback
        if len(audio_bytes) % 2 != 0:
            audio_bytes = audio_bytes[:-1]
            
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = whisper_model.transcribe(audio_np, language="en", beam_size=5)
        text = "".join([segment.text for segment in segments]).strip()
        
    return text if text else None

def generate_response(user_input: str) -> str:
    """Generate response using Ollama synchronously (runs in thread)."""
    system_prompt = """You are a helpful, friendly voice assistant. 
- Keep responses concise and natural for voice (under 150 words typically)
- Be conversational and warm
- If asked a technical question, explain simply
- Ask clarifying questions if needed"""
    
    try:
        start_time = time.time()
        response = requests.post(
            f"{OLLAMA_API_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": user_input,
                "system": system_prompt,
                "stream": False,
                "temperature": 0.7,
                "top_p": 0.9,
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            ai_response = result.get("response", "").strip()
            
            logger.info("Ollama generation complete", extra={"extra_data": {
                "latency_sec": round(time.time() - start_time, 2),
                "eval_tokens": result.get('eval_count', 0),
                "ai_text_preview": ai_response[:50] + "..."
            }})
            return ai_response
        else:
            return "Sorry, I encountered an error processing your request."
            
    except requests.exceptions.Timeout:
        return "I'm thinking about your question. Could you repeat that?"
    except Exception as e:
        logger.error("LLM Generation Error", extra={"extra_data": {"error": str(e)}})
        return "I encountered an unexpected error. Please try again."

@app.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket):
    """WebSocket endpoint for voice agent communication."""
    await websocket.accept()
    client_id = id(websocket)
    logger.info("Client connected", extra={"extra_data": {"client_id": client_id}})
    
    # ----------------- Observability Initialization -----------------
    call_id = f"call_{uuid.uuid4()}"
    user_id = "user_12345"  # Hardcoded real-time user example ID
    call_start_ms = int(time.time() * 1000)
    
    publisher = None
    if _observability_import_error is None and os.getenv("KAFKA_ENABLED", "true").lower() == "true":
        try:
            kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
            publisher = CallEventPublisher(bootstrap_servers=kafka_servers)
            await publisher.start()
            await publisher.emit_call_started(call_id, user_id, CallType.WEB_AGENT)
            logger.info("Observability started", extra={"extra_data": {"call_id": call_id, "user_id": user_id}})
        except Exception as e:
            logger.error("Failed to start Kafka event publisher. Observability disabled.", extra={"extra_data": {"error": str(e)}})
            publisher = None
    # ----------------------------------------------------------------
    
    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            
            if "audio" in data and data["audio"]:
                audio_bytes = base64.b64decode(data["audio"])
                
                # Unique ID generated for the current conversational turn
                turn_id = f"turn_{uuid.uuid4()}"
                
                # 1. Transcribe (STT)
                transcribed_text = None
                if publisher:
                    async with publisher.track(call_id, turn_id, ComponentType.STT, RoleType.USER) as ctx:
                        transcribed_text = transcribe_audio(audio_bytes)
                        ctx["content"] = transcribed_text or ""
                else:
                    transcribed_text = transcribe_audio(audio_bytes)
                
                if not transcribed_text:
                    continue
                
                logger.info("Transcription success", extra={"extra_data": {
                    "client_id": client_id,
                    "user_speech": transcribed_text,
                    "audio_size_kb": round(len(audio_bytes) / 1024, 2)
                }})
                
                # 2. Generate AI Response (LLM)
                ai_response = None
                if publisher:
                    async with publisher.track(call_id, turn_id, ComponentType.LLM, RoleType.ASSISTANT) as ctx:
                        ai_response = await asyncio.to_thread(generate_response, transcribed_text)
                        ctx["content"] = ai_response or ""
                else:
                    ai_response = await asyncio.to_thread(generate_response, transcribed_text)
                
                # 3. Convert to audio (TTS)
                response_audio = None
                if publisher:
                    async with publisher.track(call_id, turn_id, ComponentType.TTS, RoleType.ASSISTANT) as ctx:
                        response_audio = text_to_audio(ai_response)
                        ctx["content"] = ai_response or ""
                else:
                    response_audio = text_to_audio(ai_response)
                
                logger.info("Response generated and converted to audio", extra={"extra_data": {
                    "client_id": client_id,
                    "response_text": ai_response[:50] + "..." if ai_response and len(ai_response) > 50 else (ai_response or ""),
                    "audio_size_kb": round(len(response_audio)/1024, 2) if response_audio else 0
                }})
                
                # Send only audio response
                if response_audio:
                    audio_b64 = base64.b64encode(response_audio).decode('utf-8')
                    await websocket.send_text(json.dumps({
                        "type": "audio",
                        "audio": audio_b64
                    }))
            
            elif "ping" in data:
                await websocket.send_text(json.dumps({"type": "pong"}))
                
    except WebSocketDisconnect:
        logger.info("Client disconnected gracefully", extra={"extra_data": {"client_id": client_id}})
    except Exception as e:
        logger.error("WebSocket Error", extra={"extra_data": {"client_id": client_id, "error": type(e).__name__, "details": str(e)}})
    finally:
        # ----------------- Observability Cleanup -----------------
        if publisher:
            try:
                await publisher.emit_call_ended(call_id, call_start_ms)
                await publisher.stop()
                logger.info("Observability stopped", extra={"extra_data": {"call_id": call_id}})
            except Exception as e:
                logger.error("Error during observability cleanup", extra={"extra_data": {"error": str(e)}})
        # ---------------------------------------------------------
        logger.info("Client disconnected", extra={"extra_data": {"client_id": client_id}})

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Web Server", extra={"extra_data": {"host": "0.0.0.0", "port": 8000}})
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None) # log_config=None prevents Uvicorn from overriding our JSON logger