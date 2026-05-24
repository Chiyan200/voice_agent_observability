"""
voice_obs_api/main.py

FastAPI application entry point.
Run: uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import calls_router, analysis_router, monitor_router
from core.config import settings
from core.database import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("Starting Voice Observability API...")
    await Database.connect(uri=settings.MONGO_URI, db_name=settings.MONGO_DB)
    logger.info("MongoDB connected")
    yield
    await Database.disconnect()
    logger.info("MongoDB disconnected")


app = FastAPI(
    title="Voice Agent Observability API",
    description="REST + WebSocket API for monitoring voice agent calls",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(calls_router,    prefix="/calls",    tags=["Calls"])
app.include_router(analysis_router, prefix="/analysis", tags=["Analysis"])
app.include_router(monitor_router,  prefix="/monitor",  tags=["Live Monitor"])


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": "1.0.0"}
