"""
voice_obs_api/models/response_models.py

Pydantic models for API request/response validation.
These are separate from the DB TypedDicts — controllers map between them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Shared sub-models ──────────────────────────────────────────────────────────

class TimestampModel(BaseModel):
    start_time: int = Field(..., description="Epoch milliseconds")
    end_time: int = Field(..., description="Epoch milliseconds")


class ObservationModel(BaseModel):
    turn_id: str
    type: str
    role: str
    duration_ms: int
    timestamp: TimestampModel
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None
    tool_output: Optional[str] = None
    tool_status: Optional[str] = None
    detected_emotion: Optional[str] = None


# ── Call History ───────────────────────────────────────────────────────────────

class CallSummaryModel(BaseModel):
    """Lightweight listing row — used in GET /calls."""
    call_id: str
    user_id: str
    call_type: str
    call_duration: int
    total_turns: int
    tool_failures: int
    has_analysis: bool = False


class CallDetailModel(BaseModel):
    """Full document — used in GET /calls/:id."""
    call_id: str
    user_id: str
    call_type: str
    call_duration: int
    observations: List[ObservationModel]


# ── Replay ────────────────────────────────────────────────────────────────────

class TurnReplayModel(BaseModel):
    """One turn inside a replay step."""
    turn_index: int
    turn_id: str
    type: str
    role: str
    content: str
    duration_ms: int
    timestamp: TimestampModel
    latency_ms: Optional[int] = Field(
        None,
        description="Time from previous STT end to this LLM start (agent response latency)",
    )
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None
    tool_output: Optional[str] = None
    tool_status: Optional[str] = None
    detected_emotion: Optional[str] = None


class ReplayModel(BaseModel):
    """Full replay payload — GET /calls/:id/replay."""
    call_id: str
    total_turns: int
    turns: List[TurnReplayModel]


class SeekModel(BaseModel):
    """Single-turn seek result — POST /calls/:id/seek?turn=N."""
    call_id: str
    turn_index: int
    turn: TurnReplayModel


# ── Post-Call Analysis ─────────────────────────────────────────────────────────

class UserSentimentModel(BaseModel):
    sentiment_label: str
    frustration_score: float
    vocal_energy: str
    confidence: float


class AssistantSentimentModel(BaseModel):
    tone: str
    speech_rate_wpm: float


class SentimentModel(BaseModel):
    user: UserSentimentModel
    assistant: AssistantSentimentModel


class QaEvaluationModel(BaseModel):
    is_hallucinating: bool
    hallucination_reasoning: str
    correctly_answered: bool
    unresolved_queries: List[str]
    conversation_summary: str


class AudioMetricsModel(BaseModel):
    wav_file_exists: bool
    total_duration_sec: float
    silence_ratio: float
    vocal_energy: str
    emotion_scores: Dict[str, float] = {}
    user_speaking_time_sec: float
    assistant_speaking_time_sec: float


class AnalysisModel(BaseModel):
    analyze_id: str
    call_id: str
    analyzed_at: datetime
    sentiment: SentimentModel
    qa_evaluation: QaEvaluationModel
    call_audio_metrics: AudioMetricsModel


# ── Dashboard / Drift ─────────────────────────────────────────────────────────

class LatencyStatModel(BaseModel):
    call_id: str
    avg_latency_ms: float
    max_latency_ms: float
    p95_latency_ms: float


class ToolStatsModel(BaseModel):
    tool_name: str
    total_calls: int
    failures: int
    success_rate: float


class SentimentTrendModel(BaseModel):
    call_id: str
    user_sentiment: str
    frustration_score: float
    analyzed_at: datetime


class DashboardModel(BaseModel):
    total_calls: int
    failed_calls: int
    avg_call_duration_sec: float
    latency_stats: List[LatencyStatModel]
    tool_stats: List[ToolStatsModel]
    sentiment_trends: List[SentimentTrendModel]
    outlier_call_ids: List[str]


# ── Live Monitor (WebSocket) ───────────────────────────────────────────────────

class LiveEventModel(BaseModel):
    event_type: str          # "anomaly" | "observation" | "call_start" | "call_end"
    call_id: str
    severity: str            # "info" | "warning" | "critical"
    message: str
    payload: Dict[str, Any] = {}
    timestamp_ms: int


# ── Pagination wrapper ─────────────────────────────────────────────────────────

class PaginatedCallsModel(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[CallSummaryModel]
