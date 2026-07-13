from __future__ import annotations

import urllib.parse
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from sap_odata_agent.api.app_dependencies import (
    get_case_repository,
    get_feedback_summarizer,
    get_orchestrator_for_profile,
    get_sap_executor,
)
from sap_odata_agent.application.progress import get_progress_broker, progress_context, publish_progress_event
from sap_odata_agent.domain.models import AgentRequest, CompiledRequest, ExecutionMode
from sap_odata_agent.infrastructure.llm.profiles import (
    describe_llm_profile,
    get_llm_profile,
    get_llm_profiles_payload,
)
from sap_odata_agent.infrastructure.sap.date_formatting import format_sap_json_date_for_display

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class QueryRequestModel(BaseModel):
    user_input: str = Field(..., description="Natural-language request from the UI")
    conversation_id: str | None = Field(default=None)
    mode: ExecutionMode = Field(default=ExecutionMode.READ_ONLY)
    llm_profile_id: str | None = Field(default=None, description="Selected full-chain LLM profile id")


class FeedbackRequestModel(BaseModel):
    case_id: str = Field(..., description="The case id returned by the query API.")
    status: Literal["correct", "incorrect"] = Field(..., description="Whether the result is correct.")
    comment: str = Field(default="", description="What is wrong with the current result.")
    expected_result: str = Field(default="", description="What result the user expected.")


class PageRequestModel(BaseModel):
    case_id: str = Field(..., description="Case id returned by the query API.")
    skip: int = Field(default=0, ge=0, description="OData skip offset for the requested page.")


@router.get("/model-profiles")
def read_model_profiles() -> dict[str, Any]:
    return get_llm_profiles_payload()


@router.get("/progress/{conversation_id}")
def stream_query_progress(conversation_id: str) -> StreamingResponse:
    broker = get_progress_broker()
    return StreamingResponse(
        broker.subscribe(conversation_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/query")
def run_query(payload: QueryRequestModel) -> dict[str, Any]:
    try:
        profile = get_llm_profile(payload.llm_profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.llm_profile_id and not profile.enabled:
        raise HTTPException(status_code=400, detail=f"LLM profile is not configured: {profile.id}")
    effective_profile_id = profile.id if profile.enabled else None
    orchestrator = get_orchestrator_for_profile(effective_profile_id)
    request = AgentRequest(
        user_input=payload.user_input,
        conversation_id=payload.conversation_id,
        mode=payload.mode,
        llm_profile_id=effective_profile_id,
    )
    with progress_context(payload.conversation_id):
        publish_progress_event(key="query.received", label="接收查询请求", status="running")
        try:
            response = orchestrator.run(request)
        except Exception as exc:
            publish_progress_event(
                key="query.failed",
                label="查询失败",
                status="failed",
                error_message=str(exc),
                terminal=True,
            )
            raise
        publish_progress_event(
            key="query.completed",
            label="查询完成" if response.success else "查询已结束",
            status="succeeded" if response.success else "completed",
            terminal=True,
        )
    llm_profile = describe_llm_profile(effective_profile_id)
    kg_debug = ((response.plan.planner_diagnostics or {}).get("kg_debug") or {}) if response.plan else {}
    payload = {
        "case_id": response.case_id,
        "llm_profile_id": effective_profile_id,
        "llm_profile": llm_profile,
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
    payload.update(
        {
            key: value
            for key, value in {
                "kg_enabled": kg_debug.get("kg_enabled"),
                "kg_build_version": kg_debug.get("kg_build_version"),
                "kg_evidence_used": kg_debug.get("kg_evidence_used"),
                "kg_semantic_warnings": kg_debug.get("kg_semantic_warnings"),
            }.items()
            if value not in (None, [], "")
        }
    )
    return payload


@router.post("/page")
def read_page(
    payload: PageRequestModel,
    case_repository=Depends(get_case_repository),
    sap_executor=Depends(get_sap_executor),
) -> dict[str, Any]:
    entry = case_repository.get_by_case_id(payload.case_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Case not found.")

    runtime_pagination = ((entry.get("runtime_request") or {}).get("pagination") or {})
    is_thin_case = entry.get("execution_origin") == "thin_mcp"
    business_top = _optional_positive_int(runtime_pagination.get("business_top")) if is_thin_case else None
    initial_skip = max(0, _safe_int(runtime_pagination.get("initial_skip"), 0)) if is_thin_case else 0
    effective_end = initial_skip + business_top if business_top is not None else None
    if effective_end is not None and payload.skip >= effective_end:
        raise HTTPException(status_code=416, detail="Requested page exceeds the plan's top limit.")
    if is_thin_case:
        stored_data = entry.get("response_preview") if isinstance(entry.get("response_preview"), dict) else {}
        known_total = _safe_int(stored_data.get("result_count"), -1)
        if payload.skip > 0 and known_total >= 0 and payload.skip >= known_total:
            raise HTTPException(status_code=416, detail="Requested page exceeds the result count.")

    local_data = _stored_local_page(entry, payload.skip)
    if local_data is not None:
        presentation = _build_page_presentation(entry, local_data)
        return {
            "case_id": payload.case_id,
            "success": True,
            "data": local_data,
            "presentation": presentation,
            "attempts": [],
            "final_message": "Page loaded.",
        }

    base_url = entry.get("final_query_url") or (((entry.get("attempts") or [{}])[-1].get("request") or {}).get("url"))
    if not base_url:
        raise HTTPException(status_code=400, detail="Case does not contain a pageable query URL.")

    page_size = _page_size_from_entry(entry)
    remaining = min(page_size, effective_end - payload.skip) if effective_end is not None else page_size
    page_url = _replace_query_params(
        base_url,
        {"$top": str(remaining), "$skip": str(payload.skip)},
        remove={"$skiptoken"} if is_thin_case else None,
    )
    attempt = sap_executor.execute(CompiledRequest(method="GET", url=page_url), attempt_number=1)
    if not attempt.success:
        raise HTTPException(status_code=502, detail=attempt.error_message or "SAP page request failed.")

    data = attempt.response_preview or {}
    if is_thin_case:
        data = _thin_page_data(data, payload.skip, page_size, effective_end)
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


@router.get("/cases/{case_id}")
def read_case_snapshot(
    case_id: str,
    case_repository=Depends(get_case_repository),
) -> dict[str, Any]:
    entry = case_repository.get_by_case_id(case_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    payload = _history_entry_to_payload(entry) or {}
    snapshot = payload.get("result_snapshot")
    if not isinstance(snapshot, dict):
        raise HTTPException(status_code=410, detail="Case result snapshot is unavailable.")
    return {
        "case_id": case_id,
        "success": True,
        "result_snapshot": snapshot,
    }


def _replace_query_params(
    url: str,
    replacements: dict[str, str],
    remove: set[str] | None = None,
) -> str:
    split = urllib.parse.urlsplit(url)
    params = dict(urllib.parse.parse_qsl(split.query, keep_blank_values=True))
    for key in remove or set():
        params.pop(key, None)
    params.update(replacements)
    query = urllib.parse.urlencode(params, safe="$(),'/")
    return urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))


def _thin_page_data(
    data: dict[str, Any],
    skip: int,
    page_size: int,
    effective_end: int | None,
) -> dict[str, Any]:
    normalized = dict(data)
    rows = [item for item in data.get("results") or [] if isinstance(item, dict)]
    if effective_end is not None:
        rows = rows[: max(0, effective_end - skip)]
    raw_total = _safe_int(data.get("result_count"), skip + len(rows))
    total = min(raw_total, effective_end) if effective_end is not None else raw_total
    has_next = skip + len(rows) < total
    normalized.update(
        {
            "result_count": total,
            "returned_count": len(rows),
            "displayed_count": len(rows),
            "results": rows,
            "pagination": {
                **(data.get("pagination") or {}),
                "page_size": page_size,
                "display_limit": page_size,
                "skip": skip,
                "page_number": (skip // page_size) + 1,
                "has_next": has_next,
                "next_skip": skip + len(rows) if has_next else None,
            },
        }
    )
    return normalized


def _stored_local_page(entry: dict[str, Any], skip: int) -> dict[str, Any] | None:
    data = entry.get("response_preview") or {}
    if not isinstance(data, dict):
        return None
    rows = data.get("_all_results")
    window_start = _safe_int(data.get("_result_window_start"), 0)
    offset = skip - window_start
    if not isinstance(rows, list) or offset < 0 or offset >= len(rows):
        return None
    pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
    display_limit = _safe_int(pagination.get("display_limit"), 50)
    if display_limit <= 0:
        display_limit = 50
    page_rows = rows[offset : offset + display_limit]
    if skip > 0 and not page_rows:
        return None
    total_count = _safe_int(data.get("result_count"), len(rows))
    next_skip = skip + len(page_rows) if skip + len(page_rows) < len(rows) else None
    page_data = dict(data)
    page_pagination = dict(pagination)
    page_pagination.update(
        {
            "page_size": display_limit,
            "display_limit": display_limit,
            "skip": skip,
            "page_number": (skip // display_limit) + 1,
            "has_next": next_skip is not None,
            "next_skip": next_skip,
            "local_has_next": next_skip is not None,
        }
    )
    page_data.update(
        {
            "result_count": total_count,
            "returned_count": len(rows),
            "displayed_count": len(page_rows),
            "results": page_rows,
            "pagination": page_pagination,
        }
    )
    return page_data


def _page_size_from_entry(entry: dict[str, Any]) -> int:
    data = entry.get("response_preview") or {}
    pagination = data.get("pagination") if isinstance(data, dict) else {}
    for raw_value in [
        (pagination or {}).get("display_limit") if isinstance(pagination, dict) else None,
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
        columns = list(clean_results[0].keys())

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


def _optional_positive_int(value: Any) -> int | None:
    parsed = _safe_int(value, 0)
    return parsed if parsed > 0 else None


def _format_display_value(value: Any) -> Any:
    return format_sap_json_date_for_display(value)


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
    llm_profile_id = request.get("llm_profile_id")
    llm_profile = describe_llm_profile(llm_profile_id)

    result_snapshot = {
        "case_id": entry.get("case_id"),
        "llm_profile_id": llm_profile_id,
        "llm_profile": llm_profile,
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
        "execution_origin": entry.get("execution_origin"),
        "request_kind": entry.get("request_kind"),
    }
    schema_context_summary = entry.get("schema_context_summary") or {}
    kg_payload = {
        "kg_enabled": schema_context_summary.get("kg_enabled"),
        "kg_build_version": schema_context_summary.get("kg_build_version"),
        "kg_evidence_used": schema_context_summary.get("kg_evidence_used"),
        "kg_semantic_warnings": schema_context_summary.get("kg_semantic_warnings"),
    }
    result_snapshot.update({key: value for key, value in kg_payload.items() if value not in (None, [], "")})

    return {
        "case_id": entry.get("case_id"),
        "created_at": entry.get("created_at"),
        "conversation_id": request.get("conversation_id"),
        "user_input": request.get("user_input"),
        "llm_profile_id": llm_profile_id,
        "llm_profile": llm_profile,
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
        "execution_origin": entry.get("execution_origin"),
        "request_kind": entry.get("request_kind"),
        **{key: value for key, value in kg_payload.items() if value not in (None, [], "")},
        "result_snapshot": result_snapshot,
    }
