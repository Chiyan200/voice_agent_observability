"""
voice_obs_api/api/routers/calls.py

REST endpoints:
  GET  /calls                       — list calls (paginated)
  GET  /calls/failures              — Task 1: failure detection summary
  GET  /calls/{call_id}             — full call detail
  GET  /calls/{call_id}/replay      — all turns with latency
  POST /calls/{call_id}/seek        — seek to specific turn index
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.controllers.calls_controller import CallsController
from core.database import Database
from models.response_models import (
    CallDetailModel,
    PaginatedCallsModel,
    ReplayModel,
    SeekModel,
)
from services.calls_service import CallsService

router = APIRouter()


def _get_controller() -> CallsController:
    db  = Database.get_db()
    svc = CallsService(db)
    return CallsController(svc)


@router.get("", response_model=PaginatedCallsModel, summary="List all calls")
async def list_calls(
    page:      int           = Query(1,  ge=1,  description="Page number"),
    page_size: int           = Query(20, ge=1, le=100),
    user_id:   Optional[str] = Query(None),
    call_type: Optional[str] = Query(None),
    ctrl: CallsController    = Depends(_get_controller),
):
    return await ctrl.list_calls(page, page_size, user_id, call_type)


@router.get("/failures", summary="Task 1 — failure detection summary")
async def get_failure_summary(ctrl: CallsController = Depends(_get_controller)):
    """
    Auto-detects and classifies failed / degraded calls.
    Returns counts per failure category and up to 5 sample call_ids each.
    """
    return await ctrl.get_failure_summary()


@router.get("/{call_id}", response_model=CallDetailModel, summary="Get full call detail")
async def get_call(call_id: str, ctrl: CallsController = Depends(_get_controller)):
    return await ctrl.get_call(call_id)


@router.get("/{call_id}/replay", response_model=ReplayModel, summary="Replay all turns with latency")
async def replay_call(call_id: str, ctrl: CallsController = Depends(_get_controller)):
    """
    Returns every observation enriched with agent response latency.
    Use this as the data source for a call replay UI.
    """
    return await ctrl.get_replay(call_id)


@router.post("/{call_id}/seek", response_model=SeekModel, summary="Seek to a specific turn")
async def seek_turn(
    call_id: str,
    turn:    int               = Query(..., ge=0, description="Zero-based turn index"),
    ctrl:    CallsController   = Depends(_get_controller),
):
    return await ctrl.seek_turn(call_id, turn)
