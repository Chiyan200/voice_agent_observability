"""
shared/models/events.py

Canonical event schemas shared between client and server.
Pydantic ensures validation on both the producer and consumer side.
"""

from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field
import time


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    CALL_INIT = "call_init"
    OBSERVATION = "observation"
    CALL_CLOSE = "call_close"


class ComponentType(str, Enum):
    STT = "stt"
    LLM = "llm"
    TTS = "tts"
    TOOL_CALL = "tool_call"


class RoleType(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class CallType(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    WEB_AGENT = "web-agent"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class TimestampMs(BaseModel):
    start_time: int = Field(..., description="Epoch milliseconds")
    end_time: int = Field(..., description="Epoch milliseconds")


# ---------------------------------------------------------------------------
# Kafka Event Payloads
# ---------------------------------------------------------------------------

class CallInitEvent(BaseModel):
    event: EventType = EventType.CALL_INIT
    call_id: str
    user_id: str
    call_type: CallType
    initiated_at: int = Field(default_factory=lambda: int(time.time() * 1000))


class ObservationEvent(BaseModel):
    event: EventType = EventType.OBSERVATION
    call_id: str
    turn_id: str
    component_type: ComponentType
    role: RoleType
    content: str
    duration_ms: int
    timestamp: TimestampMs


class CallCloseEvent(BaseModel):
    event: EventType = EventType.CALL_CLOSE
    call_id: str
    call_duration_sec: int
    closed_at: int = Field(default_factory=lambda: int(time.time() * 1000))
