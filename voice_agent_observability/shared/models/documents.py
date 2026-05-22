"""
shared/models/documents.py

MongoDB document schemas (TypedDicts for motor compatibility).
"""

from typing import TypedDict, List


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


class CallHistoryDict(TypedDict):
    call_id: str
    user_id: str
    call_type: str
    call_duration: int
    observations: List[ObservationDict]
