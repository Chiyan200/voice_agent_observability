"""
voice_obs_api/api/routers/analysis.py

REST endpoints:
  GET /analysis/dashboard          — drift dashboard (Task 4 data)
  GET /analysis/{call_id}          — post-call analysis for a call
  GET /analysis/{call_id}/report   — structured failure report (Task 2)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.controllers.analysis_controller import AnalysisController
from core.database import Database
from models.response_models import AnalysisModel, DashboardModel
from services.analysis_service import AnalysisService
from services.calls_service import CallsService

router = APIRouter()


def _get_controller() -> AnalysisController:
    db = Database.get_db()
    return AnalysisController(
        analysis_svc=AnalysisService(db),
        calls_svc=CallsService(db),
    )


@router.get("/dashboard", response_model=DashboardModel, summary="Drift detection dashboard data")
async def get_dashboard(ctrl: AnalysisController = Depends(_get_controller)):
    """
    Aggregated view: latency distributions, tool success rates,
    sentiment trends, failure patterns, and outlier call_ids.
    """
    return await ctrl.get_dashboard()


@router.get("/{call_id}", response_model=AnalysisModel, summary="Get post-call analysis")
async def get_analysis(call_id: str, ctrl: AnalysisController = Depends(_get_controller)):
    return await ctrl.get_analysis_for_call(call_id)


@router.get("/{call_id}/report", summary="Task 2 — structured failure attribution report")
async def get_failure_report(call_id: str, ctrl: AnalysisController = Depends(_get_controller)):
    """
    Per-call structured failure report: exact turn, root cause,
    what the agent did, what it should have done.
    """
    return await ctrl.get_failure_report(call_id)
