from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from sap_odata_agent.api.app_dependencies import get_case_repository, get_feedback_summarizer, get_orchestrator, get_sap_executor
from sap_odata_agent.domain.models import AgentRequest, CompiledRequest, ExecutionMode

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


class PageRequestModel(BaseModel):
    case_id: str = Field(..., description="Case id returned by the query API.")
    skip: int = Field(default=0, ge=0, description="OData skip offset for the requested page.")


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


@router.post("/page")
def read_page(
    payload: PageRequestModel,
    case_repository=Depends(get_case_repository),
    sap_executor=Depends(get_sap_executor),
) -> dict[str, Any]:
    entry = case_repository.get_by_case_id(payload.case_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Case not found.")

    base_url = entry.get("final_query_url") or (((entry.get("attempts") or [{}])[-1].get("request") or {}).get("url"))
    if not base_url:
        raise HTTPException(status_code=400, detail="Case does not contain a pageable query URL.")

    page_size = _page_size_from_entry(entry)
    page_url = _replace_query_params(base_url, {"$top": str(page_size), "$skip": str(payload.skip)})
    attempt = sap_executor.execute(CompiledRequest(method="GET", url=page_url), attempt_number=1)
    if not attempt.success:
        raise HTTPException(status_code=502, detail=attempt.error_message or "SAP page request failed.")

    data = attempt.response_preview or {}
    presentation = _build_page_presentation(entry, data)
    return {
        "case_id": payload.case_id,
        "success": True,
        "data": data,
        "presentation": presentation,
        "attempts": [attempt],
        "final_message": "Page loaded.",
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


def _replace_query_params(url: str, replacements: dict[str, str]) -> str:
    split = urllib.parse.urlsplit(url)
    params = dict(urllib.parse.parse_qsl(split.query, keep_blank_values=True))
    params.update(replacements)
    query = urllib.parse.urlencode(params, safe="$(),'/")
    return urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))


def _page_size_from_entry(entry: dict[str, Any]) -> int:
    data = entry.get("response_preview") or {}
    pagination = data.get("pagination") if isinstance(data, dict) else {}
    for raw_value in [
        (pagination or {}).get("page_size") if isinstance(pagination, dict) else None,
        (entry.get("final_plan") or {}).get("top"),
    ]:
        try:
            value = int(str(raw_value))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 50


def _build_page_presentation(entry: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    existing_presentation = entry.get("presentation") or {}
    columns = [column for column in existing_presentation.get("columns", []) if isinstance(column, str)]
    results = data.get("results") if isinstance(data.get("results"), list) else []
    clean_results = [
        {key: _format_display_value(value) for key, value in row.items() if key != "__metadata"}
        for row in results
        if isinstance(row, dict)
    ]
    if not columns and clean_results:
        columns = list(clean_results[0].keys())[:8]

    rows = [{column: row.get(column, "") for column in columns} for row in clean_results]
    pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
    total_count = _safe_int(data.get("result_count"), len(clean_results))
    skip = _safe_int(pagination.get("skip"), 0)
    displayed_count = len(rows)
    text = (
        f"查询结果总共{total_count}条，当前显示前{displayed_count}条"
        if skip <= 0
        else f"查询结果总共{total_count}条，当前显示第{skip + 1}-{skip + displayed_count}条"
    )
    return {
        "kind": "table",
        "title": existing_presentation.get("title") or "查询结果",
        "text": text,
        "columns": columns,
        "rows": rows,
    }


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return fallback


def _format_display_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    match = re.fullmatch(r"/?Date\((-?\d+)(?:[+-]\d+)?\)/?", value.strip())
    if not match:
        return value
    milliseconds = int(match.group(1))
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).strftime("%Y.%m.%d")


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

    api_skill_used = entry.get("api_skill_used") or (entry.get("schema_context_summary") or {}).get(
        "api_skill",
        {},
    )

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
        "feedback_memories_used": entry.get("feedback_memories_used", []),
        "api_skill_used": api_skill_used,
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
        "feedback_memories_used": entry.get("feedback_memories_used", []),
        "api_skill_used": api_skill_used,
        "result_snapshot": result_snapshot,
    }
