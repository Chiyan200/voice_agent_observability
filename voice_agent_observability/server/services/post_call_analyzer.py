"""
server/services/post_call_analyzer.py

SERVER SIDE — Independent post-call sentiment and quality analyzer service.
Consumes 'voice_agent.call_close' Kafka topic and runs asynchronously.
"""

import os
import sys
import json
import uuid
import time
import asyncio
import logging
import signal
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import numpy as np
import soundfile as sf
import librosa
import torch
import requests
from transformers import pipeline
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError
from pydantic import BaseModel, Field, ValidationError

# Configure path so imports work correctly
OBS_DIR = Path(__file__).parent.parent.parent
if str(OBS_DIR) not in sys.path:
    sys.path.append(str(OBS_DIR))

from shared.config.topics import TOPIC_CALL_CLOSE
from shared.models.events import CallCloseEvent
from shared.models.documents import (
    PostCallAnalysisDict,
    SentimentAnalysisDict,
    UserSentimentDict,
    AssistantSentimentDict,
    QaEvaluationDict,
    AudioMetricsDict
)
from server.db.call_history_repository import CallHistoryRepository
from server.db.post_analysis_repository import PostAnalysisRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("post_call_analyzer")

# LLM Configuration
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")


class PostCallAnalyzer:
    """
    Independent service that consumes the call close topic,
    gathers the call details, analyzes sentiments & quality,
    and stores the report in a new Mongo collection.
    """

    CONSUMER_GROUP_ID = "voice-agent-post-call-analyzer"

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        mongo_uri: str = "mongodb://localhost:27017/",
        db_name: str = "voice_agent_obs",
    ):
        self._bootstrap_servers = bootstrap_servers
        self._history_repository = CallHistoryRepository(uri=mongo_uri, db_name=db_name)
        self._analysis_repository = PostAnalysisRepository(uri=mongo_uri, db_name=db_name)
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._running = False

        # Initialize Audio Emotion Recognition Model
        # Downloads automatically on first run and caches to ~/.cache/huggingface/
        logger.info("Initializing Speech Emotion Recognition model...")
        self.device = 0 if torch.cuda.is_available() else -1
        self.emotion_pipeline = pipeline(
            "audio-classification", 
            model="superb/wav2vec2-base-superb-er",
            device=self.device
        )
        logger.info("Emotion model loaded successfully on %s", "GPU" if self.device == 0 else "CPU")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            TOPIC_CALL_CLOSE,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self.CONSUMER_GROUP_ID,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            auto_commit_interval_ms=1000,
        )
        await self._consumer.start()
        self._running = True
        logger.info(
            "PostCallAnalyzer started group=%s topic=%s",
            self.CONSUMER_GROUP_ID, TOPIC_CALL_CLOSE
        )

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("PostCallAnalyzer stopped")

    async def run(self) -> None:
        try:
            await self.start()
            self._register_signal_handlers()
            
            async for record in self._consumer:
                if not self._running:
                    break
                
                payload = record.value
                try:
                    event = CallCloseEvent(**payload)
                    logger.info("Received call close event for call_id=%s.", event.call_id)
                    asyncio.create_task(self.analyze_call(event.call_id))
                except ValidationError as exc:
                    logger.error("Failed to parse CallCloseEvent payload: %s", exc)
                except Exception as exc:
                    logger.error("Unexpected error parsing event: %s", exc)
                    
        except KafkaError as exc:
            logger.error("Kafka error in analyzer loop: %s", exc)
        except asyncio.CancelledError:
            logger.info("Analyzer loop cancelled — shutting down")
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # Core Analysis Logic
    # ------------------------------------------------------------------

    async def analyze_call(self, call_id: str) -> None:
        await asyncio.sleep(2.0)

        try:
            call_history = await self._history_repository.get_call(call_id)
            if not call_history:
                await asyncio.sleep(3.0)
                call_history = await self._history_repository.get_call(call_id)
                if not call_history:
                    logger.error("Abandoned analysis: call history missing for %s", call_id)
                    return

            user_id = call_history.get("user_id", "unknown_user")
            observations = call_history.get("observations", [])

            transcript_turns = []
            user_speaking_time_sec = 0.0
            assistant_speaking_time_sec = 0.0

            for obs in observations:
                role = obs.get("role")
                obs_type = obs.get("type")
                content = obs.get("content", "").strip()
                duration_ms = obs.get("duration_ms", 0)

                if obs_type == "stt" and role == "user":
                    user_speaking_time_sec += duration_ms / 1000.0
                    transcript_turns.append(f"User: {content}")
                elif obs_type == "tts" and role == "assistant":
                    assistant_speaking_time_sec += duration_ms / 1000.0
                    transcript_turns.append(f"Assistant: {content}")

            full_transcript = "\n".join(transcript_turns)

            # 3. Analyze Call Audio Metrics (Offloaded to executor to prevent blocking)
            loop = asyncio.get_event_loop()
            audio_metrics = await loop.run_in_executor(None, self._analyze_audio_file, user_id, call_id)
            
            audio_metrics["user_speaking_time_sec"] = user_speaking_time_sec
            audio_metrics["assistant_speaking_time_sec"] = assistant_speaking_time_sec

            # 4. Deep Quality & Sentiment Evaluation using local Ollama LLM
            llm_result = await self._evaluate_quality_via_llm(full_transcript)

            # 5. Build Final Analysis Document
            analysis_doc: PostCallAnalysisDict = {
                "analyze_id": f"analysis_{uuid.uuid4()}",
                "call_id": call_id,
                "analyzed_at": datetime.utcnow(),
                "sentiment": {
                    "user": {
                        "sentiment_label": llm_result.get("user_sentiment", "neutral"),
                        "frustration_score": llm_result.get("frustration_score", 0.0),
                        "vocal_energy": audio_metrics.get("vocal_energy", "neutral"), 
                        "confidence": llm_result.get("user_confidence", 0.8),
                    },
                    "assistant": {
                        "tone": llm_result.get("assistant_tone", "polite"),
                        "speech_rate_wpm": self._calculate_speech_rate(observations),
                    }
                },
                "qa_evaluation": {
                    "is_hallucinating": llm_result.get("is_hallucinating", False),
                    "hallucination_reasoning": llm_result.get("hallucination_reasoning", ""),
                    "correctly_answered": llm_result.get("correctly_answered", True),
                    "unresolved_queries": llm_result.get("unresolved_queries", []),
                    "conversation_summary": llm_result.get("conversation_summary", "No summary available."),
                },
                "call_audio_metrics": audio_metrics
            }

            await self._analysis_repository.save_analysis(analysis_doc)
            logger.info("Successfully saved post-call analysis for call_id=%s. Analyze ID: %s", 
                        call_id, analysis_doc["analyze_id"])

        except Exception as exc:
            logger.error("Failed post-call analysis for call_id=%s: %s", call_id, exc, exc_info=True)

    # ------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------

    def _analyze_audio_file(self, user_id: str, call_id: str) -> Dict[str, Any]:
        """
        Parses the physical WAV file to measure durations, compute silence,
        and perform deep neural network emotion inference.
        """
        rec_dir = Path(__file__).parent.parent.parent.parent / "call_recording" / user_id
        wav_path = rec_dir / f"{call_id}.wav"
        
        metrics = {
            "wav_file_exists": False,
            "total_duration_sec": 0.0,
            "silence_ratio": 0.0,
            "vocal_energy": "neutral",
            "emotion_scores": {}
        }

        if not wav_path.exists():
            logger.warning("Call recording file not found at: %s", wav_path)
            return metrics

        try:
            metrics["wav_file_exists"] = True
            
            # Use Librosa to load and strictly resample to 16kHz for Wav2Vec2 compatibility
            y, sr = librosa.load(str(wav_path), sr=16000)
            metrics["total_duration_sec"] = round(len(y) / sr, 2)

            if len(y) > 0:
                # --- 1. Silence Calculation ---
                frame_len = int(sr * 0.1)  # 100ms
                if frame_len > 0:
                    num_frames = len(y) // frame_len
                    silent_frames = 0
                    for i in range(num_frames):
                        frame = y[i * frame_len : (i + 1) * frame_len]
                        rms = np.sqrt(np.mean(frame**2))
                        if rms < 0.01:
                            silent_frames += 1
                    metrics["silence_ratio"] = round(silent_frames / num_frames, 2) if num_frames > 0 else 0.0

                # --- 2. Advanced Emotion Recognition ---
                # Chunk audio into 5-second segments to prevent Out-Of-Memory on long calls
                chunk_length = 5 * sr
                chunks = [y[i:i + chunk_length] for i in range(0, len(y), chunk_length)]
                
                aggregated_scores = {}
                processed_chunks = 0
                
                for chunk in chunks:
                    if len(chunk) < sr: continue # Skip trailing audio less than 1 second
                    
                    # Run Hugging Face pipeline
                    predictions = self.emotion_pipeline(chunk)
                    
                    # Predictions format: [{'label': 'angry', 'score': 0.8}, ...]
                    for pred in predictions:
                        label = pred['label']
                        score = pred['score']
                        aggregated_scores[label] = aggregated_scores.get(label, 0) + score
                        
                    processed_chunks += 1

                if processed_chunks > 0:
                    # Average the scores across all processed chunks
                    final_scores = {k: round(v / processed_chunks, 4) for k, v in aggregated_scores.items()}
                    dominant_emotion = max(final_scores, key=final_scores.get)
                    
                    metrics["emotion_scores"] = final_scores
                    metrics["vocal_energy"] = dominant_emotion
                else:
                    metrics["vocal_energy"] = "neutral"

            logger.info("Audio emotion computed for call_id=%s. Dominant emotion: %s", 
                        call_id, metrics["vocal_energy"])
                        
        except Exception as e:
            logger.error("Failed to parse WAV audio file for emotion deduction: %s", e)

        return metrics

    def _calculate_speech_rate(self, observations: List[Dict[str, Any]]) -> float:
        total_words = 0
        total_duration_ms = 0

        for obs in observations:
            if obs.get("type") == "tts" and obs.get("role") == "assistant":
                content = obs.get("content", "")
                words = len(content.split())
                duration = obs.get("duration_ms", 0)

                total_words += words
                total_duration_ms += duration

        if total_duration_ms > 0:
            duration_min = total_duration_ms / 60000.0
            return round(total_words / duration_min, 1)
        return 0.0

    async def _evaluate_quality_via_llm(self, transcript: str) -> Dict[str, Any]:
        fallback_res = {
            "user_sentiment": "neutral",
            "frustration_score": 0.0,
            "user_confidence": 0.9,
            "assistant_tone": "polite",
            "is_hallucinating": False,
            "hallucination_reasoning": "Not audited.",
            "correctly_answered": True,
            "unresolved_queries": [],
            "conversation_summary": "Summary unavailable due to LLM timeout.",
        }

        if not transcript.strip():
            return fallback_res

        system_prompt = """You are a post-call speech audit system. 
Output a single JSON object containing exact analysis metrics.
{
  "user_sentiment": "positive|neutral|frustrated|angry",
  "frustration_score": 0.0,
  "user_confidence": 0.8,
  "assistant_tone": "polite|warm|robotic|repetitive|apologetic",
  "is_hallucinating": false,
  "hallucination_reasoning": "",
  "correctly_answered": true,
  "unresolved_queries": [],
  "conversation_summary": "summary"
}
Return ONLY raw JSON."""

        try:
            loop = asyncio.get_event_loop()
            
            def run_request():
                return requests.post(
                    f"{OLLAMA_API_URL}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": transcript,
                        "system": system_prompt,
                        "stream": False,
                        "temperature": 0.1,
                        "format": "json"
                    },
                    timeout=20
                )

            response = await loop.run_in_executor(None, run_request)

            if response.status_code == 200:
                result = response.json()
                raw_response = result.get("response", "").strip()
                try:
                    return json.loads(raw_response)
                except json.JSONDecodeError:
                    if "```" in raw_response:
                        cleaned = raw_response.split("```")[1]
                        if cleaned.startswith("json"):
                            cleaned = cleaned[4:]
                        return json.loads(cleaned.strip())
                    raise
        except Exception as e:
            logger.error("Ollama API failed: %s", e)

        return fallback_res

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _register_signal_handlers(self) -> None:
        if sys.platform == "win32":
            signal.signal(signal.SIGINT, self._sync_signal_handler)
            signal.signal(signal.SIGTERM, self._sync_signal_handler)
        else:
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

    def _sync_signal_handler(self, signum, frame) -> None:
        logger.info("Shutdown signal received — stopping analyzer")
        self._running = False


async def main():
    analyzer = PostCallAnalyzer()
    await analyzer.run()


if __name__ == "__main__":
    asyncio.run(main())