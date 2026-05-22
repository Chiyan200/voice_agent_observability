"""
server/main.py

Entry point for the observability consumer service.
Run: python -m server.main
"""

import asyncio
import logging

from server.consumers.call_event_consumer import CallEventConsumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

async def main():
    consumer = CallEventConsumer(
        bootstrap_servers="localhost:9092",
        mongo_uri="mongodb://localhost:27017/",
        db_name="voice_agent_obs",
    )
    await consumer.run()


if __name__ == "__main__":
    asyncio.run(main())
