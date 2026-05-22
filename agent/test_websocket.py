import asyncio
import json
import base64
import websockets
import wave
import logging
import numpy as np
from pathlib import Path
import io
import sys
import time

# Try to import pyaudio, fallback if not available
try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False
    print("⚠️  Warning: pyaudio not available, audio playback will be skipped")

# --- Structured Logging Configuration ---
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            log_obj.update(record.extra_data)
        return json.dumps(log_obj)

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("test_client")

# Server configuration
SERVER_HOST = "localhost"
SERVER_PORT = 8000
WS_URL = f"ws://{SERVER_HOST}:{SERVER_PORT}/ws/agent"
CONNECTION_TIMEOUT = 10
MESSAGE_TIMEOUT = 30
MAX_RETRIES = 3

AUDIO_SEQUENCE = [
    {"order": 1, "file": "utils/greet.wav"},
    {"order": 2, "file": "utils/mid.wav"},
    {"order": 3, "file": "utils/end.wav"},
]

def wav_to_pcm16k(raw_wav_path: str):
    """Convert WAV file to raw 16kHz PCM"""
    with wave.open(raw_wav_path, 'rb') as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        audio_data = wf.readframes(wf.getnframes())

        samples = np.frombuffer(audio_data, dtype=np.int16 if sampwidth == 2 else np.uint8)
        if n_channels == 2:
            samples = samples[::2]

        if framerate != 16000:
            num_samples = int(len(samples) * 16000 / framerate)
            samples = np.interp(
                np.linspace(0, len(samples), num_samples),
                np.arange(len(samples)),
                samples
            ).astype(np.int16)
        else:
            samples = samples.astype(np.int16)

        return samples.tobytes()

async def send_audio(ws, file_path: str):
    file_path = Path(file_path)
    if not file_path.exists():
        logger.error("Audio file missing", extra={"extra_data": {"file": str(file_path)}})
        return False

    try:
        pcm_bytes = wav_to_pcm16k(str(file_path))
        audio_b64 = base64.b64encode(pcm_bytes).decode('utf-8')

        await ws.send(json.dumps({"audio": audio_b64}))
        logger.info("Audio sent", extra={"extra_data": {"file": file_path.name, "size_kb": round(len(pcm_bytes)/1024, 2)}})
        return True
    except Exception as e:
        logger.error("Failed to send audio", extra={"extra_data": {"file": file_path.name, "error": str(e)}})
        return False

def play_audio_bytes(audio_bytes: bytes):
    """Play audio bytes using pyaudio if available"""
    if not HAS_PYAUDIO:
        logger.warning("pyaudio not available, skipping audio playback")
        # Save audio to file for manual playback
        try:
            with open('response_audio.mp3', 'wb') as f:
                f.write(audio_bytes)
            logger.info("Audio saved to response_audio.mp3 (use media player to play)")
        except Exception as e:
            logger.error("Failed to save audio file", extra={"extra_data": {"error": str(e)}})
        return
    
    try:
        # Read WAV/MP3 format using soundfile
        import soundfile as sf
        audio_io = io.BytesIO(audio_bytes)
        # Decode as 16-bit PCM integer array (robust and widely supported)
        data, samplerate = sf.read(audio_io, dtype='int16')
        n_channels = 1 if len(data.shape) == 1 else data.shape[1]
        
        # Play using pyaudio
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=n_channels,
            rate=samplerate,
            output=True
        )
        
        duration = len(data) / samplerate
        logger.info("Playing audio...", extra={"extra_data": {"duration": duration}})
        stream.write(data.tobytes())
        stream.stop_stream()
        stream.close()
        p.terminate()
        
        logger.info("✅ Audio playback completed")
    except Exception as e:
        logger.error("Audio playback failed", extra={"extra_data": {"error": str(e)}})
        # Save to file as fallback
        try:
            with open('response_audio.mp3', 'wb') as f:
                f.write(audio_bytes)
            logger.info("Audio saved to response_audio.mp3 (playback failed)")
        except Exception as save_err:
            logger.error("Failed to save fallback audio file", extra={"extra_data": {"error": str(save_err)}})

async def connect_with_retry(max_retries=MAX_RETRIES):
    """Connect to WebSocket with exponential backoff retry logic"""
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"WebSocket connection attempt {attempt}/{max_retries}", extra={"extra_data": {"url": WS_URL}})
            ws = await asyncio.wait_for(
                websockets.connect(WS_URL, ping_interval=20, ping_timeout=30),
                timeout=CONNECTION_TIMEOUT
            )
            logger.info("✅ Connected to server successfully")
            return ws
        except asyncio.TimeoutError:
            logger.error(f"Connection timeout on attempt {attempt}", extra={"extra_data": {"timeout": CONNECTION_TIMEOUT}})
            if attempt < max_retries:
                wait_time = 2 ** attempt  # Exponential backoff
                logger.info(f"Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
        except ConnectionRefusedError:
            logger.error(f"Connection refused on attempt {attempt}", extra={"extra_data": {"message": "Is the server running on " + WS_URL + "?"}})
            if attempt < max_retries:
                wait_time = 2 ** attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
        except Exception as e:
            logger.error(f"Connection error on attempt {attempt}: {type(e).__name__}", extra={"extra_data": {"error": str(e)}})
            if attempt < max_retries:
                wait_time = 2 ** attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
    
    raise Exception(f"Failed to connect after {max_retries} attempts")

async def test_conversation():
    logger.info("Starting conversation test", extra={"extra_data": {"url": WS_URL}})
    
    ws = None
    try:
        # Connect with retry logic
        ws = await connect_with_retry()
        
        for item in AUDIO_SEQUENCE:
            logger.info("Executing sequence step", extra={"extra_data": {"step": item["order"]}})
            
            success = await send_audio(ws, item["file"])
            if not success:
                continue

            # Wait for the audio response
            try:
                response_str = await asyncio.wait_for(ws.recv(), timeout=MESSAGE_TIMEOUT)
                data = json.loads(response_str)

                msg_type = data.get("type")
                
                if msg_type == "audio":
                    audio_b64 = data.get("audio")
                    if audio_b64:
                        audio_bytes = base64.b64decode(audio_b64)
                        logger.info("Audio response received from server", extra={"extra_data": {
                            "turn": data.get("turn"),
                            "audio_size_kb": round(len(audio_bytes)/1024, 2)
                        }})
                        
                        # Play the audio
                        play_audio_bytes(audio_bytes)
                    else:
                        logger.warning("Empty audio response received")
                else:
                    logger.warning(f"Unexpected message type: {msg_type}")
                
            except asyncio.TimeoutError:
                logger.error("Timeout waiting for server response", extra={"extra_data": {
                    "step": item["order"],
                    "timeout": MESSAGE_TIMEOUT
                }})
                continue
            except json.JSONDecodeError as e:
                logger.error("Failed to parse server response", extra={"extra_data": {"error": str(e)}})
                continue
            except Exception as e:
                logger.error("Error processing server response", extra={"extra_data": {"error": str(e), "type": type(e).__name__}})
                continue

            await asyncio.sleep(2)  # Give the server breathing room before the next file

        logger.info("✅ Test sequence completed successfully")
        
    except Exception as e:
        logger.error("Test failed", extra={"extra_data": {"error": str(e), "type": type(e).__name__}})
        sys.exit(1)
    finally:
        if ws:
            try:
                await ws.close()
                logger.info("WebSocket connection closed")
            except:
                pass

if __name__ == "__main__":
    try:
        asyncio.run(test_conversation())
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.error("Fatal error", extra={"extra_data": {"error": str(e)}})
        sys.exit(1)