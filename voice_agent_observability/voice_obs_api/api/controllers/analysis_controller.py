"""
voice_obs_api/api/controllers/analysis_controller.py
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import HTTPException

from models.response_models import (
    AnalysisModel,
    AudioMetricsModel,
    AssistantSentimentModel,
    DashboardModel,
    LatencyStatModel,
    QaEvaluationModel,
    SentimentModel,
    SentimentTrendModel,
    ToolStatsModel,
    UserSentimentModel,
)
from services.analysis_service import AnalysisService
from services.calls_service import CallsService


def _coerce_datetime(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val
    if isinstance(val, dict) and "$date" in val:
        return datetime.fromisoformat(val["$date"].replace("Z", "+00:00"))
    if isinstance(val, str):
        return datetime.fromisoformat(val)
    return datetime.utcnow()


def _doc_to_analysis_model(doc: Dict[str, Any]) -> AnalysisModel:
    sent = doc.get("sentiment", {})
    usr  = sent.get("user", {})
    ast  = sent.get("assistant", {})
    qa   = doc.get("qa_evaluation", {})
    am   = doc.get("call_audio_metrics", {})

    return AnalysisModel(
        analyze_id=doc["analyze_id"],
        call_id=doc["call_id"],
        analyzed_at=_coerce_datetime(doc.get("analyzed_at")),
        sentiment=SentimentModel(
            user=UserSentimentModel(
                sentiment_label=usr.get("sentiment_label", "neutral"),
                frustration_score=usr.get("frustration_score", 0.0),
                vocal_energy=usr.get("vocal_energy", "neutral"),
                confidence=usr.get("confidence", 0.9),
            ),
            assistant=AssistantSentimentModel(
                tone=ast.get("tone", "polite"),
                speech_rate_wpm=ast.get("speech_rate_wpm", 0.0),
            ),
        ),
        qa_evaluation=QaEvaluationModel(
            is_hallucinating=qa.get("is_hallucinating", False),
            hallucination_reasoning=qa.get("hallucination_reasoning", ""),
            correctly_answered=qa.get("correctly_answered", True),
            unresolved_queries=qa.get("unresolved_queries", []),
            conversation_summary=qa.get("conversation_summary", ""),
        ),
        call_audio_metrics=AudioMetricsModel(
            wav_file_exists=am.get("wav_file_exists", False),
            total_duration_sec=am.get("total_duration_sec", 0.0),
            silence_ratio=am.get("silence_ratio", 0.0),
            vocal_energy=am.get("vocal_energy", "neutral"),
            emotion_scores=am.get("emotion_scores", {}),
            user_speaking_time_sec=am.get("user_speaking_time_sec", 0.0),
            assistant_speaking_time_sec=am.get("assistant_speaking_time_sec", 0.0),
        ),
    )


class AnalysisController:
    def __init__(self, analysis_svc: AnalysisService, calls_svc: CallsService):
        self._analysis = analysis_svc
        self._calls    = calls_svc

    async def get_analysis_for_call(self, call_id: str) -> AnalysisModel:
        doc = await self._analysis.get_by_call_id(call_id)
        if not doc:
            raise HTTPException(
                status_code=404,
                detail=f"No post-call analysis found for call '{call_id}'",
            )
        return _doc_to_analysis_model(doc)

    async def get_failure_report(self, call_id: str) -> Dict[str, Any]:
        report = await self._analysis.get_failure_report(call_id)
        if not report:
            raise HTTPException(status_code=404, detail=f"Call '{call_id}' not found")
        return report

    async def get_dashboard(self) -> DashboardModel:
        data = await self._calls.get_dashboard()
        return DashboardModel(
            total_calls=data["total_calls"],
            failed_calls=data["failed_calls"],
            avg_call_duration_sec=data["avg_call_duration_sec"],
            latency_stats=[LatencyStatModel(**s) for s in data["latency_stats"]],
            tool_stats=[ToolStatsModel(**s) for s in data["tool_stats"]],
            sentiment_trends=[
                SentimentTrendModel(
                    call_id=t["call_id"],
                    user_sentiment=t["user_sentiment"],
                    frustration_score=t["frustration_score"],
                    analyzed_at=_coerce_datetime(t["analyzed_at"]),
                )
                for t in data["sentiment_trends"]
            ],
            outlier_call_ids=data["outlier_call_ids"],
        )
