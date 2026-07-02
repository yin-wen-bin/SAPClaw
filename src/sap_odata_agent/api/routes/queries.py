from __future__ import annotations

import time
import urllib.parse
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from sap_odata_agent.api.app_dependencies import (
    get_case_repository,
    get_orchestrator_for_profile,
    get_sap_executor,
)
from sap_odata_agent.api.auth import require_internal_api_key
from sap_odata_agent.domain.models import AgentRequest, CompiledRequest, ExecutionMode
from sap_odata_agent.infrastructure.llm.profiles import get_llm_profile
from sap_odata_agent.infrastructure.sap.date_formatting import format_sap_json_date_for_display


router = APIRouter(
    prefix="/api/v1",
    tags=["queries"],
    dependencies=[Depends(require_internal_api_key)],
)


class InternalQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str = Field(..., min_length=1, description="Natural-language query to run against SAP.")
    conversation_id: str | None = Field(default=None)
    llm_profile_id: str | None = Field(default=None)


@router.post("/queries", response_model=None)
def run_internal_query(payload: InternalQueryRequest) -> dict[str, Any] | JSONResponse:
    try:
        profile = get_llm_profile(payload.llm_profile_id)
    except ValueError as exc:
        return _error_response(
            status_code=400,
            code="invalid_llm_profile",
            message=str(exc),
        )

    if payload.llm_profile_id and not profile.enabled:
        return _error_response(
            status_code=400,
            code="llm_profile_not_configured",
            message=f"LLM profile is not configured: {profile.id}",
        )

    effective_profile_id = profile.id if profile.enabled else None
    orchestrator = get_orchestrator_for_profile(effective_profile_id)
    request = AgentRequest(
        user_input=payload.input,
        conversation_id=payload.conversation_id,
        mode=ExecutionMode.READ_ONLY,
        llm_profile_id=effective_profile_id,
    )
    response = orchestrator.run(request)

    if _plan_requires_write(response.plan):
        return JSONResponse(
            status_code=400,
            content=_agent_response_payload(
                response,
                status="error",
                error={
                    "code": "unsupported_operation",
                    "message": "Only read-only GET queries are supported by this API.",
                },
            ),
        )

    return _agent_response_payload(response)


@router.get("/queries/{case_id}/pages", response_model=None)
def read_internal_query_page(
    case_id: str,
    skip: int = Query(default=0, ge=0),
    case_repository=Depends(get_case_repository),
    sap_executor=Depends(get_sap_executor),
) -> dict[str, Any] | JSONResponse:
    entry = case_repository.get_by_case_id(case_id)
    if entry is None:
        return _error_response(
            status_code=404,
            code="case_not_found",
            message="Case not found.",
            case_id=case_id,
        )

    if _entry_plan_requires_write(entry):
        return _error_response(
            status_code=400,
            code="unsupported_operation",
            message="Only read-only GET queries can be paged by this API.",
            case_id=case_id,
        )

    base_url = entry.get("final_query_url") or (((entry.get("attempts") or [{}])[-1].get("request") or {}).get("url"))
    if not base_url:
        return _error_response(
            status_code=400,
            code="page_url_unavailable",
            message="Case does not contain a pageable query URL.",
            case_id=case_id,
        )

    started_at = time.perf_counter()
    local_data = _stored_local_page(entry, skip)
    if local_data is not None:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        presentation = _build_page_presentation(entry, local_data)
        return _page_response_payload(case_id, local_data, presentation, entry, duration_ms)

    page_size = _page_size_from_entry(entry)
    page_url = _replace_query_params(base_url, {"$top": str(page_size), "$skip": str(skip)})
    attempt = sap_executor.execute(CompiledRequest(method="GET", url=page_url), attempt_number=1)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)

    if not attempt.success:
        return _error_response(
            status_code=502,
            code="sap_page_request_failed",
            message=attempt.error_message or "SAP page request failed.",
            case_id=case_id,
            duration_ms=duration_ms,
        )

    data = attempt.response_preview or {}
    presentation = _build_page_presentation(entry, data)
    return _page_response_payload(case_id, data, presentation, entry, duration_ms)


def _agent_response_payload(
    response: Any,
    *,
    status: str | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    resolved_status = status or _status_from_agent_response(response)
    presentation = _presentation_payload(response.presentation)
    data = _data_payload(response.data, response.presentation)
    presentation_text = (presentation or {}).get("text") or ""
    message = response.final_message or presentation_text

    if error is None and resolved_status == "error":
        error = {
            "code": _error_code_from_agent_response(response),
            "message": message or "Query failed.",
        }
    kg_debug = ((_get_value(response.plan, "planner_diagnostics", {}) or {}).get("kg_debug") or {}) if response.plan else {}

    return {
        "case_id": response.case_id,
        "status": resolved_status,
        "message": message,
        "answer": presentation_text or message,
        "presentation": presentation,
        "data": data,
        "metadata": {
            "service_name": _get_value(response.plan, "service_name", ""),
            "entity_set": _get_value(response.plan, "entity_set", ""),
            **{
                key: value
                for key, value in {
                    "kg_enabled": kg_debug.get("kg_enabled"),
                    "kg_build_version": kg_debug.get("kg_build_version"),
                    "kg_evidence_used": kg_debug.get("kg_evidence_used"),
                    "kg_semantic_warnings": kg_debug.get("kg_semantic_warnings"),
                }.items()
                if value not in (None, [], "")
            },
        },
        "duration_ms": response.total_duration_ms,
        "error": error,
    }


def _page_response_payload(
    case_id: str,
    data: dict[str, Any],
    presentation: dict[str, Any],
    entry: dict[str, Any],
    duration_ms: float,
) -> dict[str, Any]:
    plan = entry.get("final_plan") or entry.get("initial_plan") or {}
    return {
        "case_id": case_id,
        "status": "success",
        "message": "Page loaded.",
        "answer": presentation.get("text") or "Page loaded.",
        "presentation": _presentation_payload(presentation),
        "data": _data_payload(data, presentation),
        "metadata": {
            "service_name": plan.get("service_name") or "",
            "entity_set": plan.get("entity_set") or "",
        },
        "duration_ms": duration_ms,
        "error": None,
    }


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    case_id: str | None = None,
    duration_ms: float | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "case_id": case_id,
            "status": "error",
            "message": message,
            "answer": "",
            "presentation": None,
            "data": {"columns": [], "rows": [], "pagination": {}},
            "metadata": {"service_name": "", "entity_set": ""},
            "duration_ms": duration_ms,
            "error": {"code": code, "message": message},
        },
    )


def _status_from_agent_response(response: Any) -> str:
    if response.needs_clarification:
        return "needs_clarification"
    return "success" if response.success else "error"


def _error_code_from_agent_response(response: Any) -> str:
    if _plan_requires_write(response.plan):
        return "unsupported_operation"
    if response.validation_issues:
        return "validation_failed"
    return "query_failed"


def _plan_requires_write(plan: Any) -> bool:
    if plan is None:
        return False
    if str(_get_value(plan, "http_method", "GET")).upper() != "GET":
        return True
    if bool(_get_value(plan, "requires_confirmation", False)):
        return True
    for step in _get_value(plan, "steps", []) or []:
        if str(_get_value(step, "http_method", "GET")).upper() != "GET":
            return True
    return False


def _entry_plan_requires_write(entry: dict[str, Any]) -> bool:
    plan = entry.get("final_plan") or entry.get("initial_plan") or {}
    if str(plan.get("http_method") or "GET").upper() != "GET":
        return True
    if bool(plan.get("requires_confirmation")):
        return True
    for step in plan.get("steps") or []:
        if isinstance(step, dict) and str(step.get("http_method") or "GET").upper() != "GET":
            return True
    return False


def _presentation_payload(presentation: Any) -> dict[str, Any] | None:
    if presentation is None:
        return None
    return {
        "kind": _get_value(presentation, "kind", "text"),
        "title": _get_value(presentation, "title", ""),
        "text": _get_value(presentation, "text", ""),
    }


def _data_payload(data: Any, presentation: Any = None) -> dict[str, Any]:
    columns = [
        str(column)
        for column in (_get_value(presentation, "columns", []) if presentation is not None else [])
        if str(column).strip()
    ]
    rows = [
        dict(row)
        for row in (_get_value(presentation, "rows", []) if presentation is not None else [])
        if isinstance(row, dict)
    ]

    if not rows:
        raw_rows = _extract_result_rows(data)
        rows = [_clean_result_row(row) for row in raw_rows]

    if not columns and rows:
        columns = list(rows[0].keys())

    normalized_rows = [
        {column: _format_display_value(row.get(column, "")) for column in columns}
        for row in rows
    ]
    pagination = data.get("pagination") if isinstance(data, dict) and isinstance(data.get("pagination"), dict) else {}

    return {
        "columns": columns,
        "rows": normalized_rows,
        "pagination": dict(pagination),
    }


def _extract_result_rows(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    results = data.get("results")
    if isinstance(results, list):
        return [row for row in results if isinstance(row, dict)]
    result = data.get("result")
    if isinstance(result, dict):
        return [result]
    return []


def _clean_result_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _format_display_value(value)
        for key, value in row.items()
        if key != "__metadata"
    }


def _build_page_presentation(entry: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    existing_presentation = entry.get("presentation") or {}
    rows = [_clean_result_row(row) for row in _extract_result_rows(data)]
    columns = [column for column in existing_presentation.get("columns", []) if isinstance(column, str)]
    if not columns and rows:
        columns = list(rows[0].keys())

    pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
    total_count = _safe_int(data.get("result_count"), len(rows))
    skip = _safe_int(pagination.get("skip"), 0)
    displayed_count = len(rows)
    if displayed_count == 0:
        text = "No rows returned."
    elif skip <= 0:
        text = f"Loaded {displayed_count} of {total_count} rows."
    else:
        text = f"Loaded rows {skip + 1}-{skip + displayed_count} of {total_count}."

    return {
        "kind": "table",
        "title": existing_presentation.get("title") or "Query results",
        "text": text,
        "columns": columns,
        "rows": [{column: row.get(column, "") for column in columns} for row in rows],
    }


def _replace_query_params(url: str, replacements: dict[str, str]) -> str:
    split = urllib.parse.urlsplit(url)
    params = dict(urllib.parse.parse_qsl(split.query, keep_blank_values=True))
    params.update(replacements)
    query = urllib.parse.urlencode(params, safe="$(),'/")
    return urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))


def _stored_local_page(entry: dict[str, Any], skip: int) -> dict[str, Any] | None:
    data = entry.get("response_preview") or {}
    if not isinstance(data, dict):
        return None
    rows = data.get("_all_results")
    if not isinstance(rows, list) or skip >= len(rows):
        return None
    pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
    display_limit = _safe_int(pagination.get("display_limit"), 50)
    if display_limit <= 0:
        display_limit = 50
    page_rows = rows[skip : skip + display_limit]
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
        value = _safe_int(raw_value, 0)
        if value > 0:
            return value
    return 50


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return fallback


def _get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _format_display_value(value: Any) -> Any:
    return format_sap_json_date_for_display(value)
