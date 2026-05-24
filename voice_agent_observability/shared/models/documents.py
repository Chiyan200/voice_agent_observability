"""
shared/models/documents.py

MongoDB document schemas (TypedDicts for motor compatibility).
"""

from typing import TypedDict, List, Optional


class TimestampDict(TypedDict):
    start_time: int  # Epoch millisecond
    end_time: int    # Epoch millisecond


class ObservationDict(TypedDict):
    turn_id: str
    type: str        # ComponentType value
    role: str        # RoleType value
    duration_ms: int
    timestamp: TimestampDict
    content: str
    tool_name: Optional[str]
    tool_input: Optional[str]
    tool_output: Optional[str]
    tool_status: Optional[str]
    detected_emotion: Optional[str]


class CallHistoryDict(TypedDict):
    call_id: str
    user_id: str
    call_type: str
    call_duration: int
    observations: List[ObservationDict]


from datetime import datetime

class UserSentimentDict(TypedDict):
    sentiment_label: str
    frustration_score: float
    vocal_energy: str
    confidence: float

class AssistantSentimentDict(TypedDict):
    tone: str
    speech_rate_wpm: float

class SentimentAnalysisDict(TypedDict):
    user: UserSentimentDict
    assistant: AssistantSentimentDict

class QaEvaluationDict(TypedDict):
    is_hallucinating: bool
    hallucination_reasoning: str
    correctly_answered: bool
    unresolved_queries: List[str]
    conversation_summary: str

class AudioMetricsDict(TypedDict):
    wav_file_exists: bool
    total_duration_sec: float
    user_speaking_time_sec: float
    assistant_speaking_time_sec: float
    silence_ratio: float

class PostCallAnalysisDict(TypedDict):
    analyze_id: str
    call_id: str
    analyzed_at: datetime
    sentiment: SentimentAnalysisDict
    qa_evaluation: QaEvaluationDict
    call_audio_metrics: AudioMetricsDict
