"""
shared/config/topics.py

Single source of truth for all Kafka topic names.
Both the client (producer) and server (consumer) import from here.
"""

TOPIC_CALL_INIT = "voice_agent.call_init"
TOPIC_CALL_OBSERVATION = "voice_agent.call.observation"
TOPIC_CALL_CLOSE = "voice_agent.call_close"

ALL_TOPICS = [
    TOPIC_CALL_INIT,
    TOPIC_CALL_OBSERVATION,
    TOPIC_CALL_CLOSE,
]
