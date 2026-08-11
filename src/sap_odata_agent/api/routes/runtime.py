from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from sap_odata_agent.api.app_dependencies import get_runtime_service
from sap_odata_agent.api.auth import require_internal_api_key, require_loopback_client
from sap_odata_agent.application.runtime_models import (
    RuntimeCatalogRequest,
    RuntimeFeedbackRequest,
    RuntimeGetRequest,
    RuntimeGuidanceRequest,
    RuntimePageRequest,
    RuntimePlanRequest,
    RuntimeSchemaRequest,
)
from sap_odata_agent.application.runtime import SapClawRuntimeService


router = APIRouter(
    prefix="/api/v1/runtime",
    tags=["runtime"],
    dependencies=[Depends(require_internal_api_key)],
)

viewer_router = APIRouter(
    prefix="/api/v1/runtime",
    tags=["runtime-viewer"],
    dependencies=[Depends(require_loopback_client)],
)


@router.get("/health")
def runtime_health(
    runtime: SapClawRuntimeService = Depends(get_runtime_service),
) -> dict[str, Any]:
    return runtime.health()


@viewer_router.get("/cases/{case_id}")
def runtime_case_snapshot(
    case_id: str,
    runtime: SapClawRuntimeService = Depends(get_runtime_service),
) -> dict[str, Any]:
    return runtime.case_snapshot(case_id)


@router.post("/catalog")
def runtime_catalog(
    payload: RuntimeCatalogRequest,
    runtime: SapClawRuntimeService = Depends(get_runtime_service),
) -> dict[str, Any]:
    return runtime.catalog(payload)


@router.post("/schema")
def runtime_schema(
    payload: RuntimeSchemaRequest,
    runtime: SapClawRuntimeService = Depends(get_runtime_service),
) -> dict[str, Any]:
    return runtime.schema(payload)


@router.post("/guidance")
def runtime_guidance(
    payload: RuntimeGuidanceRequest,
    runtime: SapClawRuntimeService = Depends(get_runtime_service),
) -> dict[str, Any]:
    return runtime.guidance(payload)


@router.post("/validate-plan")
def runtime_validate_plan(
    payload: RuntimePlanRequest,
    runtime: SapClawRuntimeService = Depends(get_runtime_service),
) -> dict[str, Any]:
    return runtime.validate_plan(payload.plan, payload.user_input)


@router.post("/execute-plan")
def runtime_execute_plan(
    payload: RuntimePlanRequest,
    runtime: SapClawRuntimeService = Depends(get_runtime_service),
) -> dict[str, Any]:
    return runtime.execute_plan(
        payload.plan,
        user_input=payload.user_input,
        conversation_id=payload.conversation_id,
        resume_case_id=payload.resume_case_id,
    )


@router.post("/execute-get")
def runtime_execute_get(
    payload: RuntimeGetRequest,
    runtime: SapClawRuntimeService = Depends(get_runtime_service),
) -> dict[str, Any]:
    return runtime.execute_get(payload)


@viewer_router.post("/page")
def runtime_page(
    payload: RuntimePageRequest,
    runtime: SapClawRuntimeService = Depends(get_runtime_service),
) -> dict[str, Any]:
    return runtime.page(payload)


@router.post("/feedback")
def runtime_feedback(
    payload: RuntimeFeedbackRequest,
    runtime: SapClawRuntimeService = Depends(get_runtime_service),
) -> dict[str, Any]:
    return runtime.feedback(
        case_id=payload.case_id,
        status=payload.status,
        comment=payload.comment,
        expected_result=payload.expected_result,
    )
