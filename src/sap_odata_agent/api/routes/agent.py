from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from sap_odata_agent.api.app_dependencies import get_case_repository, get_feedback_summarizer, get_orchestrator
from sap_odata_agent.domain.models import AgentRequest, ExecutionMode

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class QueryRequestModel(BaseModel):
    user_input: str = Field(..., description="Natural-language request from the UI")
    conversation_id: str | None = Field(default=None)
    mode: ExecutionMode = Field(default=ExecutionMode.READ_ONLY)


class FeedbackRequestModel(BaseModel):
    case_id: str = Field(..., description="The case id returned by the query API.")
    status: Literal["correct", "incorrect"] = Field(..., description="Whether the result is correct.")
    comment: str = Field(default="", description="What is wrong with the current result.")
    expected_result: str = Field(default="", description="What result the user expected.")


@router.post("/query")
def run_query(payload: QueryRequestModel, orchestrator=Depends(get_orchestrator)) -> dict[str, Any]:
    request = AgentRequest(
        user_input=payload.user_input,
        conversation_id=payload.conversation_id,
        mode=payload.mode,
    )
    response = orchestrator.run(request)
    return {
        "case_id": response.case_id,
        "success": response.success,
        "needs_clarification": response.needs_clarification,
        "clarification_question": response.clarification_question,
        "clarification_options": response.clarification_options,
        "final_message": response.final_message,
        "plan": response.plan,
        "validation_issues": response.validation_issues,
        "attempts": response.attempts,
        "data": response.data,
        "presentation": response.presentation,
        "guardrail_decision": response.guardrail_decision,
        "critic_findings": response.critic_findings,
        "failure_attribution": response.failure_attribution,
        "presentation_verification": response.presentation_verification,
        "timings": response.timings,
        "timing_summary": response.timing_summary,
        "total_duration_ms": response.total_duration_ms,
    }


@router.post("/feedback")
def save_feedback(
    payload: FeedbackRequestModel,
    case_repository=Depends(get_case_repository),
    feedback_summarizer=Depends(get_feedback_summarizer),
) -> dict[str, Any]:
    updated = case_repository.update_feedback(
        case_id=payload.case_id,
        status=payload.status,
        comment=payload.comment,
        expected_result=payload.expected_result,
    )
    if updated is not None and payload.status == "incorrect":
        memory = feedback_summarizer.summarize(updated)
        case_repository.save_feedback_memory(payload.case_id, memory)
    return {
        "ok": updated is not None,
        "entry": _history_entry_to_payload(updated) if updated is not None else None,
    }


@router.get("/history")
def read_history(
    conversation_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    case_repository=Depends(get_case_repository),
) -> dict[str, Any]:
    entries = case_repository.list_recent(limit=limit, conversation_id=conversation_id)
    return {
        "items": [_history_entry_to_payload(entry) for entry in entries],
    }


def _history_entry_to_payload(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if entry is None:
        return None

    request = entry.get("request") or {}
    plan = entry.get("final_plan") or entry.get("initial_plan") or {}
    final_status = entry.get("final_status") or "failed"
    success = final_status == "success"
    needs_clarification = final_status == "clarification_requested"
    presentation = entry.get("presentation")
    error_summary = entry.get("error_summary") or ""

    if needs_clarification:
        final_message = (plan.get("clarification_question") or error_summary or "").strip()
    elif success:
        final_message = (presentation or {}).get("text") or "Query executed successfully."
    else:
        final_message = error_summary or "Query failed."

    result_snapshot = {
        "case_id": entry.get("case_id"),
        "success": success,
        "needs_clarification": needs_clarification,
        "clarification_question": plan.get("clarification_question"),
        "clarification_options": plan.get("clarification_options", []),
        "final_message": final_message,
        "plan": plan,
        "validation_issues": [],
        "attempts": entry.get("attempts", []),
        "data": entry.get("response_preview"),
        "presentation": presentation,
        "guardrail_decision": entry.get("guardrail_decision"),
        "critic_findings": entry.get("critic_findings", []),
        "failure_attribution": entry.get("failure_attribution"),
        "presentation_verification": entry.get("presentation_verification"),
        "timings": entry.get("timings", []),
        "timing_summary": entry.get("timing_summary", {}),
        "total_duration_ms": entry.get("total_duration_ms"),
    }

    return {
        "case_id": entry.get("case_id"),
        "created_at": entry.get("created_at"),
        "conversation_id": request.get("conversation_id"),
        "user_input": request.get("user_input"),
        "effective_user_input": entry.get("effective_user_input"),
        "mode": request.get("mode"),
        "final_status": final_status,
        "success": success,
        "needs_clarification": needs_clarification,
        "entity_set": plan.get("entity_set"),
        "final_query_url": entry.get("final_query_url"),
        "feedback": entry.get("feedback"),
        "presentation": presentation,
        "guardrail_decision": entry.get("guardrail_decision"),
        "critic_findings": entry.get("critic_findings", []),
        "failure_attribution": entry.get("failure_attribution"),
        "presentation_verification": entry.get("presentation_verification"),
        "timings": entry.get("timings", []),
        "timing_summary": entry.get("timing_summary", {}),
        "total_duration_ms": entry.get("total_duration_ms"),
        "result_snapshot": result_snapshot,
    }
