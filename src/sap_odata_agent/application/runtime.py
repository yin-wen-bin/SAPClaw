from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import uuid
from dataclasses import asdict, replace
from datetime import datetime
from itertools import product
from typing import Any

from sap_odata_agent.application.result_transformer import ResultTransformError, ResultTransformer
from sap_odata_agent.application.schema_feasibility_validator import SchemaFeasibilityValidator
from sap_odata_agent.application.runtime_models import (
    RuntimeCatalogRequest,
    RuntimeGetRequest,
    RuntimeGuidanceRequest,
    RuntimePageRequest,
    RuntimeSchemaRequest,
    RuntimeQueryPlan,
    validation_issue_payload,
)
from sap_odata_agent.domain.models import (
    RuntimeValidationContext,
    CompiledRequest,
    ExecutionAttempt,
    FilterCondition,
    FunctionParameter,
    OutputContract,
    QueryPlan,
)
from sap_odata_agent.infrastructure.config.settings import Settings
from sap_odata_agent.infrastructure.indexing.api_catalog_provider import ApiCatalogProvider
from sap_odata_agent.infrastructure.indexing.api_skill_provider import ApiSkillProvider
from sap_odata_agent.infrastructure.indexing.function_imports import function_imports_from_snapshot
from sap_odata_agent.infrastructure.indexing.index_loader import LocalIndexLoader, LocalIndexSnapshot
from sap_odata_agent.infrastructure.indexing.schema_context_provider import SchemaContextProvider
from sap_odata_agent.infrastructure.knowledge_graph import KnowledgeGraphProvider
from sap_odata_agent.infrastructure.repositories.file_case_repository import JsonlCaseRepository
from sap_odata_agent.infrastructure.sap.date_formatting import format_sap_json_date_for_display
from sap_odata_agent.infrastructure.sap.odata_client import (
    BasicODataCompiler,
    BasicPlanValidator,
    SapODataExecutor,
)
from sap_odata_agent.infrastructure.sap.live_schema import LiveSchemaOverlay, LiveSchemaProvider


SCHEMA_VERSION = "1.0"
ALLOWED_QUERY_OPTIONS = frozenset(
    {
        "$select",
        "$filter",
        "$orderby",
        "$top",
        "$skip",
        "$expand",
        "$inlinecount",
        "$format",
        "$skiptoken",
    }
)
FILTER_OPERATORS = frozenset({"eq", "ne", "gt", "ge", "lt", "le", "contains", "in"})
SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "password",
        "sap_password",
        "sap_username",
        "secret",
        "token",
    }
)


class SapClawRuntimeService:
    """LLM-free, read-only runtime used by the Codex-first MCP surface."""

    def __init__(
        self,
        *,
        settings: Settings,
        catalog_provider: ApiCatalogProvider,
        skill_provider: ApiSkillProvider,
        knowledge_graph_provider: KnowledgeGraphProvider,
        schema_context_provider: SchemaContextProvider,
        schema_validator: SchemaFeasibilityValidator,
        plan_validator: BasicPlanValidator,
        compiler: BasicODataCompiler,
        executor: SapODataExecutor,
        case_repository: JsonlCaseRepository,
        result_transformer: ResultTransformer | None = None,
        live_schema_provider: LiveSchemaProvider | None = None,
    ) -> None:
        self.settings = settings
        self.catalog_provider = catalog_provider
        self.skill_provider = skill_provider
        self.knowledge_graph_provider = knowledge_graph_provider
        self.schema_context_provider = schema_context_provider
        self.schema_validator = schema_validator
        self.plan_validator = plan_validator
        self.compiler = compiler
        self.executor = executor
        self.case_repository = case_repository
        self.result_transformer = result_transformer or ResultTransformer()
        self.live_schema_provider = live_schema_provider
        self.index_loader = LocalIndexLoader(settings.index_root)
        self.page_size = max(1, settings.runtime_page_size)
        self.max_binding_rows = max(1, settings.runtime_max_binding_rows)

    def health(self) -> dict[str, Any]:
        indexed_count, executable_count = self._index_health_counts()
        readiness_issues = self._readiness_issues(indexed_count, executable_count)
        ready = not readiness_issues
        return self._envelope(
            ok=ready,
            status="success" if ready else "not_ready",
            data={
                "backend": "ok",
                "runtime_ready": ready,
                "read_only": True,
                "indexed_service_count": indexed_count,
                "executable_service_count": executable_count,
                "index_root_exists": self.index_loader.index_root.exists(),
                "sap_base_url_configured": bool(self.settings.sap_base_url),
                "sap_credentials_configured": bool(self.settings.sap_username and self.settings.sap_password),
                "live_schema_enabled": self.settings.runtime_live_schema_enabled,
                "live_schema_provider_ready": self.live_schema_provider is not None,
                "viewer_enabled": bool(self._viewer_base_url()),
                "readiness_issues": readiness_issues,
            },
            error=None if ready else {
                "code": "runtime_not_ready",
                "message": "SAPClaw Runtime is running but required SAP or index configuration is not ready.",
                "details": readiness_issues,
            },
        )

    def catalog(self, request: RuntimeCatalogRequest) -> dict[str, Any]:
        catalog = self.catalog_provider.load()
        kg_evidence = (
            self.knowledge_graph_provider.recommend_apis(request.query)
            if request.query.strip()
            else []
        )
        skill_evidence = (
            self.skill_provider.recommend_services(
                request.query,
                [str(item.get("service_name") or "") for item in catalog],
                limit=self.settings.local_kg_max_evidence,
            )
            if request.query.strip()
            else []
        )
        page = catalog[request.skip : request.skip + request.limit]
        next_skip = request.skip + len(page) if request.skip + len(page) < len(catalog) else None
        return self._envelope(
            ok=True,
            data={
                "items": page,
                "kg_api_evidence": kg_evidence,
                "skill_api_evidence": skill_evidence,
                "evidence_policy": "advisory_only",
            },
            pagination={
                "page_size": request.limit,
                "skip": request.skip,
                "total_count": len(catalog),
                "has_next": next_skip is not None,
                "next_skip": next_skip,
            },
        )

    def schema(self, request: RuntimeSchemaRequest) -> dict[str, Any]:
        try:
            snapshot = self.index_loader.load(request.service_name)
        except FileNotFoundError:
            return self._validation_error(
                "service_not_indexed",
                f"Service `{request.service_name}` is not present in the local index.",
                "service_name",
            )

        entity_map = {
            str(entity.get("entity_set") or ""): entity
            for entity in snapshot.entities
            if entity.get("entity_set")
        }
        requested_entities = list(dict.fromkeys(request.entity_sets))
        missing_entities = [name for name in requested_entities if name not in entity_map]
        if missing_entities:
            return self._validation_error(
                "entity_not_indexed",
                "Unknown entity set(s): " + ", ".join(missing_entities),
                "entity_sets",
            )

        field_scope = set(requested_entities)
        candidate_field_refs: set[tuple[str, str]] = set()
        if request.query.strip() and not field_scope:
            context = self.schema_context_provider.build(request.service_name, request.query)
            candidate_field_refs = {
                (str(item.get("entity_set") or ""), str(item.get("field_name") or ""))
                for item in context.get("candidate_fields", [])
                if item.get("entity_set") and item.get("field_name")
            }
            field_scope.update(entity for entity, _field in candidate_field_refs)

        live_overlay = self._live_schema_overlay(request.service_name)
        live_entities = live_overlay.snapshot.entities if live_overlay and live_overlay.snapshot else {}
        selected_fields: list[dict[str, Any]] = []
        if request.include_fields:
            for field in snapshot.fields:
                entity_set = str(field.get("entity_set") or "")
                field_name = str(field.get("field_name") or "")
                if field_scope and entity_set not in field_scope:
                    continue
                if candidate_field_refs and (entity_set, field_name) not in candidate_field_refs:
                    continue
                field_payload = self._schema_field_payload(field)
                if live_overlay is not None:
                    runtime_available = field_name in live_entities.get(entity_set, set())
                    field_payload.update({"runtime_available": runtime_available, "executable": runtime_available})
                selected_fields.append(field_payload)
                if len(selected_fields) >= request.max_fields:
                    break

        relation_scope = field_scope or set(entity_map)
        relations = [
            dict(item)
            for item in snapshot.relations
            if str(item.get("from_entity_set") or "") in relation_scope
        ]
        service = self._service_record(snapshot)
        entity_payloads = []
        for name in (requested_entities or list(entity_map)):
            payload = self._schema_entity_payload(entity_map[name])
            if live_overlay is not None:
                runtime_available = name in live_entities
                payload.update({"runtime_available": runtime_available, "executable": runtime_available})
            entity_payloads.append(payload)
        compatibility_status = None
        if live_overlay is not None:
            if live_overlay.snapshot is None:
                compatibility_status = "unavailable"
            elif live_overlay.stale:
                compatibility_status = "stale"
            else:
                drifted = any(not item.get("runtime_available", False) for item in [*entity_payloads, *selected_fields])
                compatibility_status = "drifted" if drifted else "compatible"
        overlay_payload = {}
        if live_overlay is not None:
            overlay_payload = {
                "compatibility_status": compatibility_status,
                "runtime_schema_source": live_overlay.runtime_schema_source,
                "metadata_fingerprint": (
                    live_overlay.snapshot.metadata_fingerprint if live_overlay.snapshot else None
                ),
                "checked_at": live_overlay.snapshot.checked_at if live_overlay.snapshot else None,
            }
        return self._envelope(
            ok=True,
            data={
                "service": service,
                "entities": entity_payloads,
                "fields": selected_fields,
                "relations": relations,
                "function_imports": function_imports_from_snapshot(snapshot),
                "fields_truncated": request.include_fields
                and len(selected_fields) >= request.max_fields
                and self._matching_field_count(snapshot, field_scope, candidate_field_refs) > len(selected_fields),
                "schema_authority": True,
                **overlay_payload,
            },
        )

    def guidance(self, request: RuntimeGuidanceRequest) -> dict[str, Any]:
        indexed_services = {item.get("service_name") for item in self.catalog_provider.load()}
        unknown = [name for name in request.service_names if name not in indexed_services]
        if unknown:
            return self._validation_error(
                "service_not_indexed",
                "Unknown service(s): " + ", ".join(unknown),
                "service_names",
            )

        skills = []
        for service_name in request.service_names:
            skill = self.skill_provider.load(service_name)
            if skill is not None:
                skills.append(skill.as_prompt_payload())

        kg_fields: list[dict[str, Any]] = []
        for service_name in request.service_names:
            kg_fields.extend(self.knowledge_graph_provider.recommend_fields(request.user_input, service_name))
        feedback = (
            self.case_repository.search_feedback_memory(
                request.user_input,
                limit=request.max_feedback_memories,
            )
            if request.max_feedback_memories > 0
            else []
        )
        return self._envelope(
            ok=True,
            data={
                "api_skills": skills,
                "kg_api_evidence": self.knowledge_graph_provider.recommend_apis(request.user_input),
                "kg_field_evidence": kg_fields[: self.settings.local_kg_max_evidence],
                "kg_path_evidence": self.knowledge_graph_provider.recommend_paths(
                    request.user_input,
                    request.service_names,
                ),
                "kg_business_terms": [
                    item
                    for service_name in (request.service_names or [""])
                    for item in self.knowledge_graph_provider.business_terms(request.user_input, service_name)
                ][: self.settings.local_kg_max_evidence],
                "feedback_memories": feedback,
                "evidence_policy": {
                    "skill_kg_feedback_are_advisory": True,
                    "schema_is_execution_authority": True,
                    "evidence_never_modifies_plan": True,
                },
            },
        )

    def validate_plan(self, plan_model: RuntimeQueryPlan, user_input: str = "") -> dict[str, Any]:
        plan = plan_model.to_domain()
        issues = self._validate_domain_plan(plan, user_input)
        return self._envelope(
            ok=not issues,
            status="success" if not issues else "validation_failed",
            data={"plan": plan_model.model_dump(mode="json"), "executable": not issues},
            validation_issues=issues,
            error=None
            if not issues
            else {
                "code": "plan_validation_failed",
                "message": "The QueryPlan is not executable. Fix validation_issues before execution.",
            },
        )

    def execute_plan(
        self,
        plan_model: RuntimeQueryPlan,
        *,
        user_input: str = "",
        conversation_id: str | None = None,
        resume_case_id: str | None = None,
    ) -> dict[str, Any]:
        not_ready = self._not_ready_response()
        if not_ready:
            return not_ready
        plan = plan_model.to_domain()
        issues = self._validate_domain_plan(plan, user_input)
        if issues:
            return self._envelope(
                ok=False,
                status="validation_failed",
                data={"plan": plan_model.model_dump(mode="json")},
                validation_issues=issues,
                error=self._preflight_error(issues, "plan_validation_failed"),
            )

        resume_state: dict[str, Any] | None = None
        if resume_case_id:
            resume_state, resume_error = self._load_aggregate_resume(resume_case_id, plan_model)
            if resume_error:
                return self._envelope(
                    ok=False,
                    status="validation_failed",
                    error=resume_error,
                )

        case_id = str(uuid.uuid4())
        started = time.perf_counter()
        attempts, data, execution_error = self._execute_domain_plan(plan, resume_state=resume_state)
        if execution_error is not None:
            execution_error = self._reclassify_plan_schema_error(plan, execution_error)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        success = execution_error is None and data is not None
        presentation = self._build_presentation(plan, data, user_input) if success else None
        executed_requests = [self._attempt_payload(item) for item in attempts]
        final_query_url = attempts[-1]["attempt"].request.url if attempts else None
        runtime_request = {
            "kind": "structured_plan",
            "plan": plan_model.model_dump(mode="json"),
            "resume_case_id": resume_case_id,
            "pagination": {
                "page_size": self.page_size,
                "business_top": plan.top,
                "initial_skip": 0,
            },
        }
        self._save_runtime_case(
            case_id=case_id,
            user_input=user_input,
            conversation_id=conversation_id,
            plan=plan,
            attempts=attempts,
            data=data,
            presentation=presentation,
            success=success,
            final_query_url=final_query_url,
            duration_ms=duration_ms,
            request_kind="structured_plan",
            runtime_request=runtime_request,
            error=execution_error,
        )
        return self._execution_envelope(
            ok=success,
            case_id=case_id,
            data=data,
            presentation=presentation,
            executed_requests=executed_requests,
            duration_ms=duration_ms,
            error=execution_error,
        )

    def execute_get(self, request: RuntimeGetRequest) -> dict[str, Any]:
        not_ready = self._not_ready_response()
        if not_ready:
            return not_ready
        request = self._controlled_get_with_output_contract(request)
        issues, snapshot, root_name, is_function, resource_kind = self._validate_controlled_get(request)
        if issues or snapshot is None:
            return self._envelope(
                ok=False,
                status="validation_failed",
                validation_issues=issues,
                error=self._preflight_error(issues, "controlled_get_validation_failed"),
            )

        case_id = str(uuid.uuid4())
        started = time.perf_counter()
        query_options = dict(request.query_options)
        initial_skip = 0
        business_top = None
        if resource_kind == "collection":
            initial_skip = self._safe_int(query_options.get("$skip"), 0)
            business_top = self._optional_positive_int(query_options.get("$top"))
            transport_top = min(business_top or self.page_size, self.page_size)
            query_options["$top"] = str(transport_top)
            query_options["$skip"] = str(initial_skip)
        url = self._controlled_get_url(
            request=request,
            snapshot=snapshot,
            root_name=root_name,
            is_function=is_function,
            query_options=query_options,
        )
        attempt_record = self._execute_compiled(CompiledRequest(method="GET", url=url), attempt_number=1)
        attempt = attempt_record["attempt"]
        data = attempt.response_preview if attempt.success else None
        if data is not None:
            if resource_kind == "singleton":
                data = self._apply_singleton_completeness(data)
            elif resource_kind == "collection":
                data = self._apply_business_pagination(data, business_top=business_top, initial_skip=initial_skip)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        error = None if attempt.success else self._sap_error(attempt)
        if error is not None:
            error = self._reclassify_controlled_schema_error(request, root_name, error)
        plan = QueryPlan(
            service_name=request.service_name,
            entity_set=request.resource_path,
            http_method="GET",
            select_fields=self._split_option_fields(request.query_options.get("$select", "")),
            response_summary_fields=(
                list(request.output_contract.display_fields)
                if request.output_contract is not None
                else self._split_option_fields(request.query_options.get("$select", ""))
            ),
            top=business_top,
            plan_kind="function_import" if is_function else "direct",
            output_contract=request.output_contract.to_domain() if request.output_contract else None,
        )
        presentation = self._build_presentation(plan, data, request.user_input) if attempt.success else None
        runtime_request = {
            "kind": "controlled_get",
            "service_name": request.service_name,
            "resource_path": request.resource_path,
            "query_options": dict(request.query_options),
            "function_parameters": dict(request.function_parameters),
            "output_contract": request.output_contract.model_dump(mode="json") if request.output_contract else None,
            "resource_kind": resource_kind,
            "pagination": {
                "page_size": 1 if resource_kind == "singleton" else self.page_size,
                "business_top": business_top,
                "initial_skip": initial_skip,
            },
        }
        self._save_runtime_case(
            case_id=case_id,
            user_input=request.user_input,
            conversation_id=request.conversation_id,
            plan=plan,
            attempts=[attempt_record],
            data=data,
            presentation=presentation,
            success=attempt.success,
            final_query_url=attempt.request.url,
            duration_ms=duration_ms,
            request_kind="controlled_get",
            runtime_request=runtime_request,
            error=error,
        )
        return self._execution_envelope(
            ok=attempt.success,
            case_id=case_id,
            data=data,
            presentation=presentation,
            executed_requests=[self._attempt_payload(attempt_record)],
            duration_ms=duration_ms,
            error=error,
        )

    def _controlled_get_with_output_contract(self, request: RuntimeGetRequest) -> RuntimeGetRequest:
        if request.output_contract is None:
            return request
        query_options = dict(request.query_options)
        selected = self._split_option_fields(query_options.get("$select", ""))
        selected = list(
            dict.fromkeys(
                [
                    *selected,
                    *request.output_contract.display_fields,
                    *request.output_contract.support_fields,
                ]
            )
        )
        query_options["$select"] = ",".join(selected)
        return request.model_copy(update={"query_options": query_options})

    def case_snapshot(self, case_id: str) -> dict[str, Any]:
        entry = self.case_repository.get_by_case_id(case_id)
        if entry is None or entry.get("execution_origin") != "sapclaw_mcp":
            return self._envelope(
                ok=False,
                status="not_found",
                case_id=case_id,
                error={"code": "case_not_found", "message": "SAPClaw Runtime case not found."},
            )
        data = entry.get("response_preview") if isinstance(entry.get("response_preview"), dict) else {}
        plan_payload = entry.get("final_plan") or entry.get("initial_plan") or {}
        presentation = entry.get("presentation") if isinstance(entry.get("presentation"), dict) else None
        if presentation is None and data:
            plan = self._domain_plan_from_stored(plan_payload)
            presentation = self._build_presentation(
                plan,
                data,
                str((entry.get("request") or {}).get("user_input") or ""),
            )
        success = str(entry.get("final_status") or "") == "success"
        clean_data = self._sanitize(data)
        raw_pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
        snapshot = {
            "case_id": case_id,
            "success": success,
            "needs_clarification": False,
            "final_message": (presentation or {}).get("text") if success else str(entry.get("error_summary") or "Query failed."),
            "plan": plan_payload,
            "validation_issues": [],
            "data": clean_data,
            "pagination": self._public_pagination(clean_data, raw_pagination),
            "presentation": presentation,
            "execution_origin": "sapclaw_mcp",
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "status": "success",
            "case_id": case_id,
            "result_snapshot": snapshot,
            "metadata": {"origin": "sapclaw_mcp", "read_only": True},
        }

    def page(self, request: RuntimePageRequest) -> dict[str, Any]:
        entry = self.case_repository.get_by_case_id(request.case_id)
        if entry is None or entry.get("execution_origin") != "sapclaw_mcp":
            return self._envelope(
                ok=False,
                status="not_found",
                case_id=request.case_id,
                error={"code": "case_not_found", "message": "SAPClaw Runtime case not found."},
            )

        runtime_request = entry.get("runtime_request") or {}
        pagination_config = runtime_request.get("pagination") or {}
        page_size = max(1, self._safe_int(pagination_config.get("page_size"), self.page_size))
        business_top = self._optional_positive_int(pagination_config.get("business_top"))
        initial_skip = max(0, self._safe_int(pagination_config.get("initial_skip"), 0))
        effective_end = initial_skip + business_top if business_top is not None else None
        if effective_end is not None and request.skip >= effective_end:
            return self._envelope(
                ok=False,
                status="page_out_of_range",
                case_id=request.case_id,
                error={"code": "page_out_of_range", "message": "Requested page exceeds the plan's top limit."},
            )

        stored_data = entry.get("response_preview") if isinstance(entry.get("response_preview"), dict) else {}
        stored_pagination = stored_data.get("pagination") if isinstance(stored_data.get("pagination"), dict) else {}
        total_count_known = stored_pagination.get("total_count_known") is True
        known_total = self._safe_int(stored_data.get("result_count"), -1)
        if total_count_known and request.skip > 0 and known_total >= 0 and request.skip >= known_total:
            return self._envelope(
                ok=False,
                status="page_out_of_range",
                case_id=request.case_id,
                error={"code": "page_out_of_range", "message": "Requested page exceeds the result count."},
            )

        resource_kind = str(runtime_request.get("resource_kind") or "collection")
        local_page = stored_data if resource_kind == "singleton" and request.skip == 0 else self._stored_page(
            stored_data, request.skip, page_size
        )
        attempts: list[dict[str, Any]] = []
        if local_page is not None:
            data = local_page
        else:
            base_url = str(entry.get("final_query_url") or "")
            if not base_url:
                return self._validation_error(
                    "page_url_unavailable",
                    "The case does not contain a pageable SAP request URL.",
                    case_id=request.case_id,
                )
            remaining = page_size
            if effective_end is not None:
                remaining = min(remaining, effective_end - request.skip)
            page_url = self._replace_query_params(
                base_url,
                {"$top": str(remaining), "$skip": str(request.skip)},
                remove={"$skiptoken"},
            )
            attempt_record = self._execute_compiled(CompiledRequest(method="GET", url=page_url), attempt_number=1)
            attempts.append(attempt_record)
            attempt = attempt_record["attempt"]
            if not attempt.success:
                return self._execution_envelope(
                    ok=False,
                    case_id=request.case_id,
                    data=None,
                    presentation=None,
                    executed_requests=[self._attempt_payload(attempt_record)],
                    duration_ms=attempt_record["duration_ms"],
                    error=self._sap_error(attempt),
                )
            data = self._apply_business_pagination(
                attempt.response_preview or {},
                business_top=business_top,
                initial_skip=initial_skip,
            )

        plan_payload = entry.get("final_plan") or entry.get("initial_plan") or {}
        plan = self._domain_plan_from_stored(plan_payload)
        presentation = self._build_presentation(plan, data, (entry.get("request") or {}).get("user_input") or "")
        return self._execution_envelope(
            ok=True,
            case_id=request.case_id,
            data=data,
            presentation=presentation,
            executed_requests=[self._attempt_payload(item) for item in attempts],
            duration_ms=sum(float(item.get("duration_ms") or 0) for item in attempts),
            error=None,
        )

    def feedback(self, case_id: str, status: str, comment: str = "", expected_result: str = "") -> dict[str, Any]:
        entry = self.case_repository.get_by_case_id(case_id)
        if entry is None or entry.get("execution_origin") != "sapclaw_mcp":
            return self._envelope(
                ok=False,
                status="not_found",
                case_id=case_id,
                error={"code": "case_not_found", "message": "SAPClaw Runtime case not found."},
            )
        updated = self.case_repository.update_feedback(
            case_id=case_id,
            status=status,
            comment=comment,
            expected_result=expected_result,
        )
        return self._envelope(
            ok=updated is not None,
            case_id=case_id,
            data={"feedback": (updated or {}).get("feedback")},
            error=None if updated is not None else {"code": "feedback_not_saved", "message": "Feedback was not saved."},
        )

    def _validate_domain_plan(self, plan: QueryPlan, user_input: str) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        if plan.http_method != "GET":
            issues.append(validation_issue_payload("non_get_not_allowed", "SAPClaw Runtime allows GET only.", "http_method"))
        if plan.payload is not None or plan.requires_confirmation:
            issues.append(
                validation_issue_payload(
                    "write_semantics_not_allowed",
                    "Payloads and confirmation-gated write semantics are not allowed.",
                )
            )

        services = [plan.service_name, *[step.service_name or plan.service_name for step in plan.steps]]
        snapshots: dict[str, LocalIndexSnapshot] = {}
        for service_name in dict.fromkeys(services):
            try:
                snapshot = self.index_loader.load(service_name)
            except FileNotFoundError:
                issues.append(
                    validation_issue_payload(
                        "service_not_indexed",
                        f"Service `{service_name}` is not present in the local index.",
                        "service_name",
                    )
                )
                continue
            snapshots[service_name] = snapshot
            runtime_issue = self._runtime_availability_issue(snapshot)
            if runtime_issue:
                issues.append(runtime_issue)

        if issues:
            return self._dedupe_issues(issues)

        issues.extend(self._live_plan_schema_issues(plan, snapshots))
        issues.extend(self._runtime_rule_plan_issues(plan))
        if issues:
            return self._dedupe_issues(issues)

        for item in self.plan_validator.validate(plan):
            issues.append(
                validation_issue_payload(
                    "basic_plan_validation",
                    item.message,
                    item.field,
                )
            )

        schema_result = self.schema_validator.validate(RuntimeValidationContext(user_input=user_input), plan)
        for violation in schema_result.violations:
            issues.append(
                validation_issue_payload(
                    f"schema_{violation.code}",
                    violation.message,
                    violation.field,
                )
            )

        if plan.steps:
            for step in plan.steps:
                snapshot = snapshots[step.service_name or plan.service_name]
                self._validate_order_fields(step.entity_set, step.order_by, snapshot, issues, step.step_id)
                if step.http_method != "GET":
                    issues.append(
                        validation_issue_payload(
                            "step_non_get_not_allowed",
                            f"Step `{step.step_id}` must use GET.",
                            "steps",
                        )
                    )
                for condition in step.filters:
                    if condition.operator not in FILTER_OPERATORS:
                        issues.append(
                            validation_issue_payload(
                                "unsupported_filter_operator",
                                f"Unsupported filter operator `{condition.operator}` in step `{step.step_id}`.",
                                condition.field,
                            )
                        )
        elif plan.plan_kind != "function_import":
            self._validate_order_fields(plan.entity_set, plan.order_by, snapshots[plan.service_name], issues)
            for condition in plan.filters:
                if condition.operator not in FILTER_OPERATORS:
                    issues.append(
                        validation_issue_payload(
                            "unsupported_filter_operator",
                            f"Unsupported filter operator `{condition.operator}`.",
                            condition.field,
                        )
                    )
        return self._dedupe_issues(issues)

    def _validate_controlled_get(
        self,
        request: RuntimeGetRequest,
    ) -> tuple[list[dict[str, Any]], LocalIndexSnapshot | None, str, bool, str]:
        issues: list[dict[str, Any]] = []
        try:
            snapshot = self.index_loader.load(request.service_name)
        except FileNotFoundError:
            return (
                [
                    validation_issue_payload(
                        "service_not_indexed",
                        f"Service `{request.service_name}` is not present in the local index.",
                        "service_name",
                    )
                ],
                None,
                "",
                False,
                "unknown",
            )
        runtime_issue = self._runtime_availability_issue(snapshot)
        if runtime_issue:
            issues.append(runtime_issue)

        raw_path = str(request.resource_path or "")
        decoded_path = urllib.parse.unquote(raw_path)
        if (
            raw_path.startswith(("/", "\\"))
            or "://" in raw_path
            or "?" in raw_path
            or "#" in raw_path
            or "\\" in raw_path
            or any(part == ".." for part in decoded_path.replace("\\", "/").split("/"))
        ):
            issues.append(
                validation_issue_payload(
                    "unsafe_resource_path",
                    "resource_path must be a relative indexed OData path without a URL, query string, or traversal.",
                    "resource_path",
                )
            )

        root_segment = raw_path.split("/", 1)[0]
        root_name = re.sub(r"\(.*\)$", "", root_segment)
        entity_names = {str(item.get("entity_set") or "") for item in snapshot.entities}
        function_map = {
            str(item.get("name") or item.get("entity_set") or ""): item
            for item in function_imports_from_snapshot(snapshot)
        }
        is_function = root_name in function_map
        resource_kind = self._controlled_get_resource_kind(raw_path, is_function=is_function)
        if root_name not in entity_names and not is_function:
            issues.append(
                validation_issue_payload(
                    "resource_root_not_indexed",
                    f"Resource root `{root_name}` is not an indexed entity set or function import.",
                    "resource_path",
                )
            )

        unknown_options = sorted(set(request.query_options) - ALLOWED_QUERY_OPTIONS)
        if unknown_options:
            issues.append(
                validation_issue_payload(
                    "query_option_not_allowed",
                    "Unsupported query option(s): " + ", ".join(unknown_options),
                    "query_options",
                )
            )
        for key, value in request.query_options.items():
            if "\r" in value or "\n" in value:
                issues.append(validation_issue_payload("unsafe_query_value", f"Query option `{key}` contains a newline.", key))
        for key in ("$top", "$skip"):
            if key in request.query_options:
                value = request.query_options[key]
                if not re.fullmatch(r"\d+", str(value)) or (key == "$top" and int(value) <= 0):
                    issues.append(validation_issue_payload("invalid_paging_value", f"`{key}` must be a valid integer.", key))
        if "$format" in request.query_options and request.query_options["$format"].lower() != "json":
            issues.append(validation_issue_payload("format_not_allowed", "Only JSON OData responses are allowed.", "$format"))
        if "$inlinecount" in request.query_options and request.query_options["$inlinecount"] not in {"allpages", "none"}:
            issues.append(validation_issue_payload("invalid_inlinecount", "$inlinecount must be allpages or none.", "$inlinecount"))
        singleton_paging_options = sorted(
            set(request.query_options).intersection({"$top", "$skip", "$skiptoken", "$inlinecount"})
        )
        if resource_kind == "singleton" and singleton_paging_options:
            issues.append(
                validation_issue_payload(
                    "singleton_paging_not_allowed",
                    "Singleton resources do not accept collection paging options: "
                    + ", ".join(singleton_paging_options),
                    "query_options",
                )
            )

        if root_name in entity_names:
            field_map = self._field_map(snapshot, root_name)
            for field_name in self._controlled_get_field_refs(request.query_options):
                if field_name not in field_map:
                    issues.append(
                        validation_issue_payload(
                            "query_field_not_in_entity",
                            f"Field `{field_name}` is not present on `{root_name}`.",
                            field_name,
                        )
                    )
            issues.extend(
                self._live_reference_issues(
                    request.service_name,
                    root_name,
                    self._controlled_get_field_refs(request.query_options),
                )
            )
            issues.extend(
                self._required_runtime_filter_issues(
                    request.service_name,
                    root_name,
                    self._controlled_get_filter_refs(request.query_options.get("$filter", "")),
                )
            )
        if request.function_parameters and not is_function:
            issues.append(
                validation_issue_payload(
                    "function_parameters_without_function",
                    "function_parameters are allowed only when resource_path targets a function import.",
                    "function_parameters",
                )
            )
        if is_function:
            function = function_map[root_name]
            parameter_map = {str(item.get("name") or ""): item for item in function.get("parameters", [])}
            unknown_parameters = sorted(set(request.function_parameters) - set(parameter_map))
            if unknown_parameters:
                issues.append(
                    validation_issue_payload(
                        "unknown_function_parameter",
                        "Unknown function parameter(s): " + ", ".join(unknown_parameters),
                        "function_parameters",
                    )
                )
            missing = [
                name
                for name, metadata in parameter_map.items()
                if metadata.get("required", True) and not str(request.function_parameters.get(name) or "").strip()
            ]
            if missing:
                issues.append(
                    validation_issue_payload(
                        "missing_function_parameter",
                        "Missing required function parameter(s): " + ", ".join(missing),
                        "function_parameters",
                    )
                )
        return self._dedupe_issues(issues), snapshot, root_name, is_function, resource_kind

    def _live_schema_overlay(self, service_name: str, *, force_refresh: bool = False) -> LiveSchemaOverlay | None:
        if not self.settings.runtime_live_schema_enabled:
            return None
        if self.live_schema_provider is None:
            return LiveSchemaOverlay(service_name, "none", False, None, "Live schema provider is not configured.")
        return self.live_schema_provider.get(service_name, force_refresh=force_refresh)

    @staticmethod
    def _preflight_error(issues: list[dict[str, Any]], fallback_code: str) -> dict[str, Any]:
        priority_codes = {
            "live_schema_unavailable",
            "schema_drift_entity_unavailable",
            "schema_drift_field_unavailable",
            "missing_required_runtime_filter",
        }
        code = next((str(item.get("code")) for item in issues if item.get("code") in priority_codes), fallback_code)
        return {"code": code, "message": "No SAP request was executed."}

    def _runtime_rule_plan_issues(self, plan: QueryPlan) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        if plan.steps:
            for step in plan.steps:
                issues.extend(
                    self._required_runtime_filter_issues(
                        step.service_name or plan.service_name,
                        re.sub(r"\(.*\)$", "", step.entity_set.split("/", 1)[0]),
                        {condition.field for condition in step.filters},
                        step_id=step.step_id,
                    )
                )
        elif plan.plan_kind != "function_import":
            issues.extend(
                self._required_runtime_filter_issues(
                    plan.service_name,
                    re.sub(r"\(.*\)$", "", plan.entity_set.split("/", 1)[0]),
                    {condition.field for condition in plan.filters},
                )
            )
        return issues

    def _required_runtime_filter_issues(
        self,
        service_name: str,
        entity_set: str,
        explicit_filter_fields: set[str],
        *,
        step_id: str | None = None,
    ) -> list[dict[str, Any]]:
        skill = self.skill_provider.load(service_name)
        entities = (skill.runtime_rules.get("entities") if skill else None) or {}
        entity_rules = entities.get(entity_set) if isinstance(entities, dict) else None
        required = entity_rules.get("required_filters", []) if isinstance(entity_rules, dict) else []
        missing = [str(field) for field in required if str(field) not in explicit_filter_fields]
        if not missing:
            return []
        suffix = f" in step `{step_id}`" if step_id else ""
        return [
            validation_issue_payload(
                "missing_required_runtime_filter",
                f"`{entity_set}` requires explicit runtime filter `{field}`{suffix}; suggested values are never injected.",
                field,
            )
            for field in missing
        ]

    def _live_reference_issues(
        self,
        service_name: str,
        entity_set: str,
        field_names: set[str] | list[str],
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        overlay = self._live_schema_overlay(service_name, force_refresh=force_refresh)
        if overlay is None:
            return []
        if overlay.snapshot is None:
            return [
                validation_issue_payload(
                    "live_schema_unavailable",
                    f"Live schema for `{service_name}` is unavailable and no cache is valid.",
                    "service_name",
                )
            ]
        if entity_set not in overlay.snapshot.entities:
            return [
                validation_issue_payload(
                    "schema_drift_entity_unavailable",
                    f"Entity set `{entity_set}` is documented locally but unavailable in the SAP runtime schema.",
                    entity_set,
                )
            ]
        runtime_fields = overlay.snapshot.entities[entity_set]
        return [
            validation_issue_payload(
                "schema_drift_field_unavailable",
                f"Field `{field_name}` on `{entity_set}` is documented locally but unavailable in the SAP runtime schema.",
                field_name,
            )
            for field_name in sorted(set(field_names) - runtime_fields)
        ]

    def _live_plan_schema_issues(
        self,
        plan: QueryPlan,
        snapshots: dict[str, LocalIndexSnapshot],
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        if plan.plan_kind == "function_import":
            return []
        references: list[tuple[str, str, set[str]]] = []
        if plan.steps:
            for step in plan.steps:
                service_name = step.service_name or plan.service_name
                entity_set = self._metadata_entity_set(snapshots[service_name], step.entity_set)
                fields = set(step.select_fields)
                fields.update(condition.field for condition in step.filters)
                fields.update(str(item).strip().split()[0] for item in step.order_by)
                fields.update(binding.field for binding in step.filter_from_previous)
                references.append((service_name, entity_set, fields))
        else:
            entity_set = self._metadata_entity_set(snapshots[plan.service_name], plan.entity_set)
            fields = set(plan.select_fields)
            fields.update(condition.field for condition in plan.filters)
            fields.update(str(item).strip().split()[0] for item in plan.order_by)
            references.append((plan.service_name, entity_set, fields))
        issues: list[dict[str, Any]] = []
        for service_name, entity_set, fields in references:
            issues.extend(
                self._live_reference_issues(
                    service_name,
                    entity_set,
                    fields,
                    force_refresh=force_refresh,
                )
            )
        return issues

    @staticmethod
    def _controlled_get_resource_kind(resource_path: str, *, is_function: bool) -> str:
        if is_function:
            return "function"
        terminal_segment = str(resource_path or "").rsplit("/", 1)[-1]
        if re.fullmatch(r"[^()]+\(.+\)", terminal_segment):
            return "singleton"
        return "collection"

    def _execute_domain_plan(
        self,
        plan: QueryPlan,
        *,
        resume_state: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
        if not plan.steps:
            fetch_all = plan.result_transform is not None
            attempts, data, error = self._execute_query_window(
                plan,
                fetch_all=fetch_all,
                row_limit=self.max_binding_rows if fetch_all else None,
                initial_rows=list((resume_state or {}).get("rows") or []),
                initial_skip=self._safe_int((resume_state or {}).get("next_source_skip"), 0),
                initial_total_count=self._safe_int((resume_state or {}).get("source_result_count"), 0),
            )
            if error or data is None:
                return attempts, data, error
            try:
                return attempts, self.result_transformer.apply(plan, data), None
            except ResultTransformError as exc:
                return attempts, None, {
                    "code": exc.code,
                    "message": str(exc),
                    "diagnostics": exc.diagnostics,
                }

        if resume_state is not None:
            return [], None, {
                "code": "aggregate_resume_not_supported_for_multistep",
                "message": "Aggregate resume currently supports direct plans only.",
            }

        attempts: list[dict[str, Any]] = []
        step_results: dict[str, dict[str, Any]] = {}
        business_evidence_gaps: list[dict[str, Any]] = []
        fetch_all_sources = {
            binding.source_step_id
            for step in plan.steps
            for binding in step.filter_from_previous
            if binding.fetch_all_for_binding
        }

        for step in plan.steps:
            runtime_filters = list(step.filters)
            fanout_values: list[tuple[str, list[Any]]] = []
            for binding in step.filter_from_previous:
                source_data = step_results.get(binding.source_step_id)
                values = self._extract_values(source_data, binding.source_field)
                if not values:
                    if self._has_zero_rows(source_data):
                        empty = self._empty_data(step.top)
                        step_results[step.step_id] = empty
                        business_evidence_gaps.append(
                            {
                                "kind": "missing_downstream_business_document",
                                "source_step_id": binding.source_step_id,
                                "target_step_id": step.step_id,
                                "binding_field": binding.field,
                                "message": (
                                    f"No downstream business document was found because step "
                                    f"`{binding.source_step_id}` returned zero rows."
                                ),
                            }
                        )
                        break
                    return (
                        attempts,
                        None,
                        {
                            "code": "binding_value_unavailable",
                            "message": (
                                f"Step `{step.step_id}` could not resolve `{binding.field}` from "
                                f"`{binding.source_step_id}.{binding.source_field}`."
                            ),
                        },
                    )
                if len(values) > self.max_binding_rows:
                    return (
                        attempts,
                        None,
                        {
                            "code": "binding_row_limit_exceeded",
                            "message": f"Binding produced more than {self.max_binding_rows} values.",
                        },
                    )
                if binding.fanout and len(values) > 1:
                    fanout_values.append((binding.field, values))
                elif len(values) == 1:
                    runtime_filters.append(FilterCondition(field=binding.field, operator="eq", value=str(values[0])))
                else:
                    runtime_filters.append(
                        FilterCondition(
                            field=binding.field,
                            operator="in",
                            value=json.dumps([str(value) for value in values], ensure_ascii=False),
                        )
                    )
            else:
                step_plan = QueryPlan(
                    service_name=step.service_name or plan.service_name,
                    entity_set=step.entity_set,
                    http_method="GET",
                    select_fields=list(step.select_fields),
                    response_summary_fields=list(step.response_summary_fields),
                    filters=runtime_filters,
                    order_by=list(step.order_by),
                    top=step.top,
                    plan_kind="direct",
                )
                fetch_all = step.step_id in fetch_all_sources or (
                    step.step_id == plan.steps[-1].step_id and plan.result_transform is not None
                ) or (
                    step.step_id == plan.steps[-1].step_id and bool(fanout_values)
                )
                if fanout_values:
                    combinations = list(product(*[values for _field, values in fanout_values]))
                    if len(combinations) > self.max_binding_rows:
                        return attempts, None, {
                            "code": "binding_fanout_limit_exceeded",
                            "message": f"Binding fanout exceeds {self.max_binding_rows} executions.",
                        }
                    fanout_attempts: list[dict[str, Any]] = []
                    fanout_rows: list[dict[str, Any]] = []
                    raw_total = 0
                    for values in combinations:
                        filters = list(step_plan.filters)
                        for (field_name, _candidates), value in zip(fanout_values, values, strict=True):
                            filters.append(FilterCondition(field=field_name, operator="eq", value=str(value)))
                        current_plan = replace(step_plan, filters=filters)
                        current_attempts, current_data, error = self._execute_query_window(
                            current_plan,
                            fetch_all=fetch_all,
                            row_limit=self.max_binding_rows if fetch_all else None,
                            attempt_start=len(attempts) + len(fanout_attempts) + 1,
                        )
                        for record in current_attempts:
                            record["attempt"].step_id = step.step_id
                        fanout_attempts.extend(current_attempts)
                        if error or current_data is None:
                            attempts.extend(fanout_attempts)
                            return attempts, None, error
                        rows = self._all_rows(current_data)
                        fanout_rows.extend(rows)
                        raw_total += self._safe_int(current_data.get("result_count"), len(rows))
                        if fetch_all and len(fanout_rows) > self.max_binding_rows:
                            attempts.extend(fanout_attempts)
                            return attempts, None, {
                                "code": "fanout_result_limit_exceeded",
                                "message": (
                                    "Complete fanout pagination requires more than "
                                    f"{self.max_binding_rows} rows."
                                ),
                            }
                    data = self._data_from_rows(fanout_rows, raw_total, step.top)
                    step_attempts = fanout_attempts
                    error = None
                else:
                    step_attempts, data, error = self._execute_query_window(
                        step_plan,
                        fetch_all=fetch_all,
                        row_limit=self.max_binding_rows if fetch_all else None,
                        attempt_start=len(attempts) + 1,
                    )
                    for record in step_attempts:
                        record["attempt"].step_id = step.step_id
                attempts.extend(step_attempts)
                if error or data is None:
                    return attempts, None, error
                step_results[step.step_id] = data
                continue
            continue

        final_step = plan.steps[-1]
        final_data = step_results.get(final_step.step_id, self._empty_data(final_step.top))
        if plan.result_transform is not None:
            try:
                final_data = self.result_transformer.apply(plan, final_data) or final_data
            except ResultTransformError as exc:
                return attempts, None, {
                    "code": exc.code,
                    "message": str(exc),
                    "diagnostics": exc.diagnostics,
                }
        merged = dict(final_data)
        merged["primary_step_id"] = self._primary_step_id(plan, step_results)
        merged["final_step_id"] = final_step.step_id
        merged["business_evidence_gaps"] = business_evidence_gaps
        merged["step_results"] = {
            step_id: {
                "step_id": step_id,
                "service_name": next(
                    (step.service_name or plan.service_name for step in plan.steps if step.step_id == step_id),
                    plan.service_name,
                ),
                "entity_set": next((step.entity_set for step in plan.steps if step.step_id == step_id), ""),
                "result_count": data.get("result_count"),
                "returned_count": data.get("returned_count"),
                "displayed_count": data.get("displayed_count"),
                "source_complete": data.get("source_complete"),
                "source_truncated": data.get("source_truncated"),
                "results": data.get("results", []),
                "pagination": data.get("pagination", {}),
            }
            for step_id, data in step_results.items()
        }
        return attempts, merged, None

    def _execute_query_window(
        self,
        plan: QueryPlan,
        *,
        fetch_all: bool,
        row_limit: int | None,
        attempt_start: int = 1,
        initial_rows: list[dict[str, Any]] | None = None,
        initial_skip: int = 0,
        initial_total_count: int = 0,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
        business_top = plan.top
        if plan.plan_kind == "function_import":
            try:
                compiled = self.compiler.compile(plan)
            except ValueError as exc:
                return [], None, {"code": "compile_failed", "message": str(exc)}
            attempt_record = self._execute_compiled(compiled, attempt_number=attempt_start)
            attempt = attempt_record["attempt"]
            if not attempt.success:
                return [attempt_record], None, self._sap_error(attempt)
            return [attempt_record], attempt.response_preview or {}, None

        transport_top = min(business_top or self.page_size, self.page_size)
        stable_order_fields = self._stable_paging_fields(plan) if fetch_all else []
        if fetch_all and not stable_order_fields:
            return [], None, {
                "code": "stable_paging_key_unavailable",
                "message": "Fetch-all requires indexed key fields or an explicit order_by for deterministic paging.",
            }
        execution_plan = replace(
            plan,
            top=transport_top,
            select_fields=list(dict.fromkeys([*plan.select_fields, *stable_order_fields])),
            order_by=list(dict.fromkeys([*plan.order_by, *stable_order_fields])),
        )
        try:
            compiled = self.compiler.compile(execution_plan)
        except ValueError as exc:
            return [], None, {"code": "compile_failed", "message": str(exc)}

        attempts: list[dict[str, Any]] = []
        all_rows: list[dict[str, Any]] = [row for row in (initial_rows or []) if isinstance(row, dict)]
        total_count = max(initial_total_count, len(all_rows))
        skip = max(0, initial_skip)
        while True:
            request_url = self._replace_query_params(
                compiled.url,
                {"$top": str(transport_top), "$skip": str(skip)},
            )
            attempt_record = self._execute_compiled(
                CompiledRequest(method="GET", url=request_url),
                attempt_number=attempt_start + len(attempts),
            )
            attempts.append(attempt_record)
            attempt = attempt_record["attempt"]
            if not attempt.success:
                if fetch_all and all_rows:
                    partial = self._data_from_rows(all_rows, max(total_count, len(all_rows) + 1), None)
                    partial.update(
                        {
                            "source_complete": False,
                            "source_truncated": True,
                            "source_stable_order_fields": stable_order_fields,
                            "next_source_skip": skip,
                        }
                    )
                    failure = self._sap_error(attempt)
                    diagnostics = {
                        "fetched_row_count": len(all_rows),
                        "next_source_skip": skip,
                        "stable_order_fields": stable_order_fields,
                        "resume_available": True,
                    }
                    if failure.get("code") == "sap_request_timeout":
                        return attempts, partial, {**failure, "diagnostics": diagnostics}
                    return attempts, partial, {
                        "code": "aggregate_source_interrupted",
                        "message": "Aggregate source pagination was interrupted and can be resumed.",
                        "diagnostics": diagnostics,
                    }
                return attempts, None, self._sap_error(attempt)
            preview = attempt.response_preview or {}
            if not fetch_all:
                return attempts, self._apply_business_pagination(preview, business_top=business_top), None
            rows = self._all_rows(preview)
            if not rows and "result" in preview:
                return attempts, preview, None
            all_rows.extend(rows)
            total_count = max(total_count, self._safe_int(preview.get("result_count"), len(all_rows)))
            if business_top is not None and len(all_rows) >= business_top:
                all_rows = all_rows[:business_top]
                break
            if row_limit is not None and len(all_rows) > row_limit:
                partial = self._data_from_rows(all_rows[:row_limit], max(total_count, len(all_rows)), None)
                partial.update(
                    {
                        "source_complete": False,
                        "source_truncated": True,
                        "source_stable_order_fields": stable_order_fields,
                        "next_source_skip": skip + len(rows),
                    }
                )
                return attempts, partial, {
                    "code": "aggregate_source_limit_exceeded" if plan.result_transform else "binding_row_limit_exceeded",
                    "message": f"Fetch-all exceeded the configured {row_limit} row limit.",
                    "diagnostics": {
                        "fetched_row_count": len(all_rows),
                        "retained_row_count": row_limit,
                        "next_source_skip": skip + len(rows),
                        "stable_order_fields": stable_order_fields,
                    },
                }
            pagination = preview.get("pagination") if isinstance(preview.get("pagination"), dict) else {}
            sap_has_next = bool(pagination.get("sap_has_next", pagination.get("has_next", False)))
            if not sap_has_next:
                break
            if row_limit is not None and len(all_rows) >= row_limit:
                partial = self._data_from_rows(all_rows, max(total_count, len(all_rows) + 1), None)
                partial.update(
                    {
                        "source_complete": False,
                        "source_truncated": True,
                        "source_stable_order_fields": stable_order_fields,
                        "next_source_skip": skip + len(rows),
                    }
                )
                return attempts, partial, {
                    "code": "aggregate_source_limit_exceeded" if plan.result_transform else "binding_row_limit_exceeded",
                    "message": f"More than {row_limit} rows are required for a complete binding.",
                    "diagnostics": {
                        "fetched_row_count": len(all_rows),
                        "next_source_skip": skip + len(rows),
                        "stable_order_fields": stable_order_fields,
                    },
                }
            next_skip = self._safe_int(pagination.get("sap_next_skip"), skip + len(rows))
            if next_skip <= skip:
                return attempts, None, {
                    "code": "non_progressing_pagination",
                    "message": "SAP pagination did not advance; aggregation stopped to avoid an infinite loop.",
                }
            skip = next_skip
        complete_total = min(max(total_count, len(all_rows)), business_top or max(total_count, len(all_rows)))
        result = self._data_from_rows(all_rows, complete_total, business_top)
        result["source_stable_order_fields"] = stable_order_fields
        return attempts, result, None

    def _load_aggregate_resume(
        self, case_id: str, plan_model: RuntimeQueryPlan
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        entry = self.case_repository.get_by_case_id(case_id)
        if entry is None or entry.get("execution_origin") != "sapclaw_mcp":
            return None, {
                "code": "aggregate_resume_case_not_found",
                "message": "The aggregate resume case was not found.",
            }
        stored_plan = entry.get("final_plan") or {}
        current_plan = plan_model.to_domain()
        if current_plan.result_transform is None:
            return None, {
                "code": "aggregate_resume_not_available",
                "message": "Only aggregate plans can resume source pagination.",
            }
        stored_fingerprint = self._source_plan_fingerprint(stored_plan)
        current_fingerprint = self._source_plan_fingerprint(asdict(current_plan))
        if stored_fingerprint != current_fingerprint:
            return None, {
                "code": "aggregate_resume_plan_mismatch",
                "message": "The resume case was created by a different aggregate plan.",
                "diagnostics": {
                    "stored_source_plan_fingerprint": stored_fingerprint,
                    "current_source_plan_fingerprint": current_fingerprint,
                },
            }
        data = entry.get("response_preview") if isinstance(entry.get("response_preview"), dict) else {}
        rows = self._all_rows(data)
        next_source_skip = self._safe_int(data.get("next_source_skip"), -1)
        if not rows or next_source_skip < 0 or not bool(data.get("source_truncated")):
            return None, {
                "code": "aggregate_resume_not_available",
                "message": "The case does not contain an interrupted resumable aggregate source.",
            }
        return {
            "rows": rows,
            "next_source_skip": next_source_skip,
            "source_result_count": self._safe_int(data.get("result_count"), len(rows)),
        }, None

    @staticmethod
    def _source_plan_fingerprint(plan: dict[str, Any]) -> str:
        """Fingerprint only fields that can change SAP requests or aggregate semantics."""

        execution_keys = (
            "service_name",
            "entity_set",
            "http_method",
            "select_fields",
            "filters",
            "order_by",
            "top",
            "plan_kind",
            "target_entity_set",
            "anchor_object",
            "anchor_value",
            "target_field",
            "path_id",
            "function_parameters",
            "result_transform",
        )
        step_keys = (
            "step_id",
            "service_name",
            "entity_set",
            "http_method",
            "select_fields",
            "filters",
            "filter_from_previous",
            "order_by",
            "top",
        )
        normalized = {key: plan.get(key) for key in execution_keys}
        normalized["steps"] = [
            {key: step.get(key) for key in step_keys}
            for step in (plan.get("steps") or [])
            if isinstance(step, dict)
        ]
        encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _stable_paging_fields(self, plan: QueryPlan) -> list[str]:
        explicit = [str(field) for field in plan.order_by if str(field).strip()]
        try:
            snapshot = self.index_loader.load(plan.service_name)
        except FileNotFoundError:
            return explicit
        root_name = re.sub(r"\(.*\)$", "", str(plan.entity_set or "").split("/", 1)[0])
        entity = next(
            (item for item in snapshot.entities if str(item.get("entity_set") or "") == root_name),
            None,
        )
        indexed_keys = [str(field) for field in (entity or {}).get("key_fields", []) if str(field).strip()]
        return list(dict.fromkeys([*explicit, *indexed_keys]))

    def _controlled_get_url(
        self,
        *,
        request: RuntimeGetRequest,
        snapshot: LocalIndexSnapshot,
        root_name: str,
        is_function: bool,
        query_options: dict[str, str],
    ) -> str:
        runtime_service = self.compiler.runtime_service_name(request.service_name)
        base = self.settings.sap_base_url.rstrip("/")
        path = f"/sap/opu/odata/sap/{runtime_service}/{request.resource_path}"
        params: dict[str, str] = {}
        if is_function:
            function = next(
                item
                for item in function_imports_from_snapshot(snapshot)
                if str(item.get("name") or item.get("entity_set") or "") == root_name
            )
            metadata = {str(item.get("name") or ""): item for item in function.get("parameters", [])}
            for name, value in request.function_parameters.items():
                value_type = str(metadata.get(name, {}).get("value_type") or "string")
                params[name] = BasicODataCompiler.compile_literal(value, value_type)
        params.update(query_options)
        query = urllib.parse.urlencode(params, safe="$(),'/:")
        return f"{base}{path}?{query}" if query else f"{base}{path}"

    def _execute_compiled(self, request: CompiledRequest, attempt_number: int) -> dict[str, Any]:
        started = time.perf_counter()
        attempt = self.executor.execute(request, attempt_number=attempt_number)
        return {
            "attempt": attempt,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    def _save_runtime_case(
        self,
        *,
        case_id: str,
        user_input: str,
        conversation_id: str | None,
        plan: QueryPlan,
        attempts: list[dict[str, Any]],
        data: dict[str, Any] | None,
        presentation: dict[str, Any] | None,
        success: bool,
        final_query_url: str | None,
        duration_ms: float,
        request_kind: str,
        runtime_request: dict[str, Any],
        error: dict[str, Any] | None,
    ) -> None:
        self.case_repository.save_entry(
            {
                "case_id": case_id,
                "created_at": datetime.now().astimezone().isoformat(),
                "request": {
                    "user_input": user_input,
                    "conversation_id": conversation_id,
                    "mode": "read_only",
                },
                "context": {"documents": [], "examples": []},
                "initial_plan": asdict(plan),
                "final_plan": asdict(plan),
                "attempts": [self._stored_attempt_payload(item) for item in attempts],
                "final_status": "success" if success else "failed",
                "final_query_url": final_query_url,
                "response_preview": data,
                "presentation": presentation,
                "timings": [
                    {
                        "key": f"runtime.sap_request.{index + 1}",
                        "label": "SAP OData GET",
                        "duration_ms": item.get("duration_ms", 0),
                    }
                    for index, item in enumerate(attempts)
                ],
                "timing_summary": {"sap_execution_ms": sum(float(item.get("duration_ms") or 0) for item in attempts)},
                "total_duration_ms": duration_ms,
                "execution_origin": "sapclaw_mcp",
                "request_kind": request_kind,
                "runtime_request": runtime_request,
                "error_summary": (error or {}).get("message") if error else None,
            }
        )

    def _execution_envelope(
        self,
        *,
        ok: bool,
        case_id: str,
        data: dict[str, Any] | None,
        presentation: dict[str, Any] | None,
        executed_requests: list[dict[str, Any]],
        duration_ms: float,
        error: dict[str, Any] | None,
    ) -> dict[str, Any]:
        clean_data = self._sanitize(data or {})
        if presentation is not None:
            clean_data["presentation"] = self._sanitize(presentation)
        pagination = clean_data.get("pagination") if isinstance(clean_data.get("pagination"), dict) else {}
        return self._envelope(
            ok=ok,
            status="success" if ok else "execution_failed",
            case_id=case_id,
            data=clean_data,
            pagination=self._public_pagination(clean_data, pagination),
            viewer_url=self._viewer_url(case_id) if ok else None,
            executed_requests=executed_requests,
            error=error,
            metadata={"duration_ms": duration_ms},
        )

    def _envelope(
        self,
        *,
        ok: bool,
        status: str = "success",
        case_id: str | None = None,
        data: dict[str, Any] | None = None,
        pagination: dict[str, Any] | None = None,
        viewer_url: str | None = None,
        validation_issues: list[dict[str, Any]] | None = None,
        executed_requests: list[dict[str, Any]] | None = None,
        error: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": ok,
            "status": status,
            "case_id": case_id,
            "data": data or {},
            "pagination": pagination or {
                "page_size": self.page_size,
                "skip": 0,
                "total_count": 0,
                "has_next": False,
                "next_skip": None,
            },
            "viewer_url": viewer_url,
            "validation_issues": validation_issues or [],
            "executed_requests": executed_requests or [],
            "error": error,
            "metadata": {
                "origin": "sapclaw_mcp",
                "read_only": True,
                "runtime_ready": not self._readiness_issues(),
                **(metadata or {}),
            },
        }

    def _readiness_issues(
        self,
        indexed_count: int | None = None,
        executable_count: int | None = None,
    ) -> list[dict[str, str]]:
        if indexed_count is None or executable_count is None:
            indexed_count, executable_count = self._index_health_counts()
        issues: list[dict[str, str]] = []
        if not self.index_loader.index_root.exists() or indexed_count <= 0:
            issues.append({"code": "index_not_ready", "message": "No SAP OData index is available."})
        elif executable_count <= 0:
            issues.append({"code": "no_executable_services", "message": "The index contains no executable SAP services."})
        if not self.settings.sap_base_url:
            issues.append({"code": "sap_base_url_missing", "message": "SAP_ODATA_BASE_URL is not configured."})
        if self.settings.sap_auth_type.lower() != "basic":
            issues.append({"code": "sap_auth_type_unsupported", "message": "SAP_AUTH_TYPE must be basic."})
        elif not self.settings.sap_username or not self.settings.sap_password:
            issues.append({"code": "sap_credentials_missing", "message": "SAP_USERNAME and SAP_PASSWORD are required."})
        if self.settings.runtime_live_schema_enabled and self.live_schema_provider is None:
            issues.append({"code": "live_schema_not_ready", "message": "Live schema validation is enabled but unavailable."})
        return issues

    def _not_ready_response(self) -> dict[str, Any] | None:
        issues = self._readiness_issues()
        if not issues:
            return None
        return self._envelope(
            ok=False,
            status="not_ready",
            error={
                "code": "runtime_not_ready",
                "message": "SAPClaw Runtime cannot execute until SAP and index configuration are ready.",
                "details": issues,
            },
        )

    def _validation_error(
        self,
        code: str,
        message: str,
        field: str | None = None,
        *,
        case_id: str | None = None,
    ) -> dict[str, Any]:
        return self._envelope(
            ok=False,
            status="validation_failed",
            case_id=case_id,
            validation_issues=[validation_issue_payload(code, message, field)],
            error={"code": code, "message": message},
        )

    @staticmethod
    def _service_record(snapshot: LocalIndexSnapshot) -> dict[str, Any]:
        service = dict(snapshot.services[0]) if snapshot.services else {"service_name": snapshot.service_name}
        service.pop("source", None)
        return service

    def _index_health_counts(self) -> tuple[int, int]:
        root = self.index_loader.index_root
        if not root.exists():
            return 0, 0
        indexed = 0
        executable = 0
        for service_dir in root.iterdir():
            if not service_dir.is_dir() or not (service_dir / "entities.json").exists():
                continue
            indexed += 1
            service_path = service_dir / "services.json"
            service: dict[str, Any] = {}
            try:
                payload = json.loads(service_path.read_text(encoding="utf-8"))
                if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                    service = payload[0]
                elif isinstance(payload, dict):
                    service = payload
            except (OSError, json.JSONDecodeError):
                pass
            service_kind = str(service.get("service_kind") or "ODATA")
            available = service.get(
                "odata_runtime_available",
                service.get("runtime_available", True) is not False and service_kind != "CDS_VIEW_ONLY",
            )
            if available is not False and service_kind != "CDS_VIEW_ONLY":
                executable += 1
        return indexed, executable

    @staticmethod
    def _schema_entity_payload(entity: dict[str, Any]) -> dict[str, Any]:
        return {
            key: entity.get(key)
            for key in (
                "service_name",
                "entity_set",
                "entity_type",
                "key_fields",
                "default_select_fields",
                "supports_filter",
                "supports_orderby",
                "supports_top",
                "navigations",
                "description",
                "supported_methods",
            )
            if key in entity
        }

    @staticmethod
    def _schema_field_payload(field: dict[str, Any]) -> dict[str, Any]:
        return {
            key: field.get(key)
            for key in (
                "service_name",
                "entity_set",
                "field_name",
                "data_type",
                "nullable",
                "is_key",
                "selectable",
                "filterable",
                "sortable",
                "label",
                "description",
                "business_aliases",
            )
            if key in field
        }

    @staticmethod
    def _matching_field_count(
        snapshot: LocalIndexSnapshot,
        field_scope: set[str],
        refs: set[tuple[str, str]],
    ) -> int:
        return sum(
            1
            for field in snapshot.fields
            if (not field_scope or str(field.get("entity_set") or "") in field_scope)
            and (
                not refs
                or (str(field.get("entity_set") or ""), str(field.get("field_name") or "")) in refs
            )
        )

    @staticmethod
    def _runtime_availability_issue(snapshot: LocalIndexSnapshot) -> dict[str, Any] | None:
        service = snapshot.services[0] if snapshot.services else {}
        service_kind = str(service.get("service_kind") or "ODATA")
        available = service.get(
            "odata_runtime_available",
            service.get("runtime_available", True) is not False and service_kind != "CDS_VIEW_ONLY",
        )
        if available is False or service_kind == "CDS_VIEW_ONLY":
            return validation_issue_payload(
                "service_not_odata_executable",
                f"Service `{snapshot.service_name}` is not exposed as an executable OData runtime.",
                "service_name",
            )
        return None

    def _validate_order_fields(
        self,
        entity_path: str,
        order_by: list[str],
        snapshot: LocalIndexSnapshot,
        issues: list[dict[str, Any]],
        step_id: str | None = None,
    ) -> None:
        entity_set = self._metadata_entity_set(snapshot, entity_path)
        fields = self._field_map(snapshot, entity_set)
        for expression in order_by:
            field_name = str(expression).strip().split()[0]
            if field_name not in fields:
                suffix = f" in step `{step_id}`" if step_id else ""
                issues.append(
                    validation_issue_payload(
                        "orderby_field_not_in_entity",
                        f"Order-by field `{field_name}` is not present on `{entity_set}`{suffix}.",
                        field_name,
                    )
                )
            elif fields[field_name].get("sortable") is False:
                issues.append(
                    validation_issue_payload(
                        "orderby_field_not_sortable",
                        f"Order-by field `{field_name}` is not sortable on `{entity_set}`.",
                        field_name,
                    )
                )

    @staticmethod
    def _field_map(snapshot: LocalIndexSnapshot, entity_set: str) -> dict[str, dict[str, Any]]:
        return {
            str(field.get("field_name") or ""): field
            for field in snapshot.fields
            if str(field.get("entity_set") or "") == entity_set and field.get("field_name")
        }

    @staticmethod
    def _metadata_entity_set(snapshot: LocalIndexSnapshot, entity_path: str) -> str:
        entity_sets = {str(item.get("entity_set") or "") for item in snapshot.entities}
        if entity_path in entity_sets:
            return entity_path
        segments = [segment for segment in str(entity_path).split("?", 1)[0].strip("/").split("/") if segment]
        candidates = [re.sub(r"\(.*\)$", "", segment) for segment in reversed(segments)]
        for candidate in candidates:
            if candidate in entity_sets:
                return candidate
        base = candidates[-1] if candidates else entity_path
        navigation = candidates[0] if candidates else ""
        joined = f"{base}{navigation}" if base != navigation else base
        return joined if joined in entity_sets else entity_path

    @classmethod
    def _controlled_get_field_refs(cls, query_options: dict[str, str]) -> set[str]:
        refs = set(cls._split_option_fields(query_options.get("$select", "")))
        refs.update(item.split()[0] for item in cls._split_option_fields(query_options.get("$orderby", "")))
        filter_text = query_options.get("$filter", "")
        refs.update(
            match.group(1).split("/")[-1]
            for match in re.finditer(
                r"\b([A-Za-z_][A-Za-z0-9_/]*)\s+(?:eq|ne|gt|ge|lt|le)\b",
                filter_text,
                flags=re.IGNORECASE,
            )
        )
        refs.update(
            match.group(1).split("/")[-1]
            for match in re.finditer(
                r"substringof\s*\([^,]+,\s*([A-Za-z_][A-Za-z0-9_/]*)\s*\)",
                filter_text,
                flags=re.IGNORECASE,
            )
        )
        return {ref for ref in refs if ref}

    @classmethod
    def _controlled_get_filter_refs(cls, filter_text: str) -> set[str]:
        return cls._controlled_get_field_refs({"$filter": filter_text})

    @staticmethod
    def _split_option_fields(value: str) -> list[str]:
        return [item.strip().split("/")[-1] for item in str(value or "").split(",") if item.strip()]

    @staticmethod
    def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for issue in issues:
            key = (str(issue.get("code") or ""), str(issue.get("message") or ""), str(issue.get("field") or ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(issue)
        return deduped

    @staticmethod
    def _replace_query_params(url: str, replacements: dict[str, str], remove: set[str] | None = None) -> str:
        split = urllib.parse.urlsplit(url)
        params = dict(urllib.parse.parse_qsl(split.query, keep_blank_values=True))
        for key in remove or set():
            params.pop(key, None)
        params.update(replacements)
        query = urllib.parse.urlencode(params, safe="$(),'/:")
        return urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, query, ""))

    def _apply_business_pagination(
        self,
        data: dict[str, Any],
        *,
        business_top: int | None,
        initial_skip: int = 0,
    ) -> dict[str, Any]:
        normalized = dict(data)
        rows = self._all_rows(data)
        pagination = dict(data.get("pagination") or {})
        total_count_known = pagination.get("total_count_known") is True
        skip = self._safe_int(pagination.get("skip"), initial_skip)
        raw_total = self._safe_int(data.get("result_count"), skip + len(rows))
        effective_total = min(raw_total, initial_skip + business_top) if business_top is not None else raw_total
        remaining = max(0, effective_total - skip)
        display_rows = rows[: min(self.page_size, remaining)]
        has_next = (
            skip + len(display_rows) < effective_total
            if total_count_known
            else bool(pagination.get("sap_has_next", pagination.get("has_next", False)))
        )
        normalized.update(
            {
                "result_count": effective_total,
                "returned_count": len(rows),
                "displayed_count": len(display_rows),
                "results": display_rows,
                "_all_results": rows,
                "_result_window_start": skip,
                "pagination": {
                    **pagination,
                    "page_size": self.page_size,
                    "display_limit": self.page_size,
                    "skip": skip,
                    "page_number": (skip // self.page_size) + 1,
                    "has_next": has_next,
                    "next_skip": skip + len(display_rows) if has_next else None,
                },
            }
        )
        return normalized

    @staticmethod
    def _apply_singleton_completeness(data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(data)
        result = data.get("result")
        count = 1 if isinstance(result, dict) else 0
        normalized.update(
            {
                "result_count": count,
                "returned_count": count,
                "displayed_count": count,
                "source_complete": True,
                "source_truncated": False,
                "resource_kind": "singleton",
                "pagination": {
                    "page_size": 1,
                    "display_limit": 1,
                    "skip": 0,
                    "page_number": 1,
                    "has_next": False,
                    "next_skip": None,
                    "local_has_next": False,
                    "sap_has_next": False,
                    "total_count_known": True,
                },
            }
        )
        return normalized

    def _data_from_rows(self, rows: list[dict[str, Any]], total_count: int, business_top: int | None) -> dict[str, Any]:
        capped_rows = rows[:business_top] if business_top is not None else rows
        display = capped_rows[: self.page_size]
        effective_total = min(total_count, business_top) if business_top is not None else total_count
        has_next = len(display) < effective_total
        return {
            "result_count": effective_total,
            "returned_count": len(capped_rows),
            "displayed_count": len(display),
            "results": display,
            "_all_results": capped_rows,
            "_result_window_start": 0,
            "source_complete": len(capped_rows) >= effective_total,
            "source_truncated": len(capped_rows) < effective_total,
            "pagination": {
                "page_size": self.page_size,
                "display_limit": self.page_size,
                "skip": 0,
                "page_number": 1,
                "has_next": has_next,
                "next_skip": len(display) if has_next else None,
                "local_has_next": len(display) < len(capped_rows),
                "sap_has_next": len(capped_rows) < effective_total,
                "total_count_known": True,
            },
        }

    def _stored_page(self, data: Any, skip: int, page_size: int) -> dict[str, Any] | None:
        if not isinstance(data, dict):
            return None
        rows = data.get("_all_results")
        if not isinstance(rows, list):
            return None
        window_start = self._safe_int(data.get("_result_window_start"), 0)
        offset = skip - window_start
        if offset < 0 or offset >= len(rows):
            return None
        page_rows = [item for item in rows[offset : offset + page_size] if isinstance(item, dict)]
        total = self._safe_int(data.get("result_count"), window_start + len(rows))
        has_next = skip + len(page_rows) < total
        result = dict(data)
        result.update(
            {
                "results": page_rows,
                "displayed_count": len(page_rows),
                "pagination": {
                    **(data.get("pagination") or {}),
                    "page_size": page_size,
                    "display_limit": page_size,
                    "skip": skip,
                    "page_number": (skip // page_size) + 1,
                    "has_next": has_next,
                    "next_skip": skip + len(page_rows) if has_next else None,
                },
            }
        )
        return result

    def _build_presentation(self, plan: QueryPlan, data: dict[str, Any] | None, user_input: str) -> dict[str, Any]:
        rows = [self._clean_display_row(row) for row in self._visible_rows(data)]
        if plan.output_contract is not None:
            preferred = list(plan.output_contract.display_fields)
        else:
            preferred = list(dict.fromkeys([*plan.response_summary_fields, *plan.select_fields]))
        columns = [field for field in preferred if any(field in row for row in rows)]
        if not columns and rows:
            columns = list(rows[0].keys())
        projected_rows = [{column: row.get(column, "") for column in columns} for row in rows]
        total = self._safe_int((data or {}).get("result_count"), len(rows))
        pagination = (data or {}).get("pagination") or {}
        skip = self._safe_int(pagination.get("skip"), 0)
        if self._contains_chinese(user_input):
            text = (
                f"查询结果总共{total}条，当前显示第{skip + 1}-{skip + len(rows)}条"
                if rows
                else "未查询到满足条件的数据。"
            )
            title = "查询结果"
        else:
            text = f"{total} total rows; showing {skip + 1}-{skip + len(rows)}." if rows else "No matching rows."
            title = "Query results"
        return {"kind": "table", "title": title, "text": text, "columns": columns, "rows": projected_rows}

    @staticmethod
    def _visible_rows(data: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        results = data.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
        result = data.get("result")
        return [result] if isinstance(result, dict) else []

    @staticmethod
    def _clean_display_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: format_sap_json_date_for_display(value)
            for key, value in row.items()
            if key != "__metadata"
        }

    @staticmethod
    def _all_rows(data: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        rows = data.get("_all_results")
        if not isinstance(rows, list):
            rows = data.get("results")
        return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []

    @staticmethod
    def _extract_values(data: dict[str, Any] | None, field_name: str) -> list[Any]:
        values = [row.get(field_name) for row in SapClawRuntimeService._all_rows(data) if row.get(field_name) is not None]
        return list(dict.fromkeys(values))

    @staticmethod
    def _has_zero_rows(data: dict[str, Any] | None) -> bool:
        if not isinstance(data, dict):
            return False
        return SapClawRuntimeService._safe_int(data.get("result_count"), -1) == 0

    def _empty_data(self, top: int | None) -> dict[str, Any]:
        return self._data_from_rows([], 0, top)

    @staticmethod
    def _primary_step_id(plan: QueryPlan, step_results: dict[str, dict[str, Any]]) -> str:
        target = plan.target_entity_set or plan.entity_set
        for step in plan.steps:
            if step.entity_set == target and step.step_id in step_results:
                return step.step_id
        return plan.steps[-1].step_id if plan.steps else ""

    @staticmethod
    def _attempt_payload(record: dict[str, Any]) -> dict[str, Any]:
        attempt: ExecutionAttempt = record["attempt"]
        return {
            "attempt_number": attempt.attempt_number,
            "step_id": attempt.step_id,
            "method": attempt.request.method,
            "url": attempt.request.url,
            "status_code": attempt.status_code,
            "success": attempt.success,
            "duration_ms": record.get("duration_ms", 0),
            "error": attempt.error_message,
        }

    @staticmethod
    def _stored_attempt_payload(record: dict[str, Any]) -> dict[str, Any]:
        attempt: ExecutionAttempt = record["attempt"]
        payload = asdict(attempt)
        payload["duration_ms"] = record.get("duration_ms", 0)
        return payload

    @staticmethod
    def _sap_error(attempt: ExecutionAttempt) -> dict[str, Any]:
        message = attempt.error_message or "SAP OData request failed."
        normalized = message.lower()
        if attempt.status_code in {408, 504} or any(
            marker in normalized for marker in ("timed out", "timeout", "time out")
        ):
            return {
                "code": "sap_request_timeout",
                "message": message,
                "status_code": attempt.status_code,
                "conclusion_state": "INCONCLUSIVE",
                "retryable": True,
            }
        return {
            "code": "sap_request_failed",
            "message": message,
            "status_code": attempt.status_code,
        }

    def _reclassify_plan_schema_error(
        self,
        plan: QueryPlan,
        error: dict[str, Any],
    ) -> dict[str, Any]:
        if error.get("status_code") not in {400, 404} or self.live_schema_provider is None:
            return error
        services = {plan.service_name, *(step.service_name or plan.service_name for step in plan.steps)}
        for service_name in services:
            self.live_schema_provider.invalidate(service_name)
        snapshots = {
            service_name: self.index_loader.load(service_name)
            for service_name in services
        }
        issues = self._live_plan_schema_issues(plan, snapshots, force_refresh=True)
        drift = [item for item in issues if str(item.get("code", "")).startswith("schema_drift_")]
        if not drift:
            return error
        return {
            "code": "schema_drift",
            "message": "SAP rejected the resource and refreshed metadata confirmed schema drift; the business query was not replayed.",
            "status_code": error.get("status_code"),
            "validation_issues": drift,
        }

    def _reclassify_controlled_schema_error(
        self,
        request: RuntimeGetRequest,
        root_name: str,
        error: dict[str, Any],
    ) -> dict[str, Any]:
        if error.get("status_code") not in {400, 404} or self.live_schema_provider is None:
            return error
        self.live_schema_provider.invalidate(request.service_name)
        issues = self._live_reference_issues(
            request.service_name,
            root_name,
            self._controlled_get_field_refs(request.query_options),
            force_refresh=True,
        )
        drift = [item for item in issues if str(item.get("code", "")).startswith("schema_drift_")]
        if not drift:
            return error
        return {
            "code": "schema_drift",
            "message": "SAP rejected the resource and refreshed metadata confirmed schema drift; the business query was not replayed.",
            "status_code": error.get("status_code"),
            "validation_issues": drift,
        }

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._sanitize(item)
                for key, item in value.items()
                if key != "__metadata"
                and not str(key).startswith("_")
                and str(key).lower() not in SENSITIVE_KEYS
            }
        if isinstance(value, list):
            return [cls._sanitize(item) for item in value]
        return value

    def _public_pagination(self, data: dict[str, Any], pagination: dict[str, Any]) -> dict[str, Any]:
        total = self._safe_int(data.get("result_count"), 0)
        skip = self._safe_int(pagination.get("skip"), 0)
        page_size = self._safe_int(pagination.get("display_limit") or pagination.get("page_size"), self.page_size)
        displayed = self._safe_int(data.get("displayed_count"), len(data.get("results") or []))
        has_next = bool(pagination.get("has_next", skip + displayed < total))
        return {
            "page_size": page_size,
            "skip": skip,
            "total_count": total,
            "total_count_known": pagination.get("total_count_known") is True,
            "has_next": has_next,
            "next_skip": pagination.get("next_skip") if has_next else None,
        }

    def _viewer_base_url(self) -> str:
        if not self.settings.runtime_viewer_enabled:
            return ""
        raw = self.settings.runtime_viewer_base_url.rstrip("/")
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme not in {"http", "https"}:
            return ""
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return ""
        return raw

    def _viewer_url(self, case_id: str) -> str | None:
        base = self._viewer_base_url()
        if not base:
            return None
        return f"{base}/?case_id={urllib.parse.quote(case_id)}&page=1"

    @staticmethod
    def _domain_plan_from_stored(payload: dict[str, Any]) -> QueryPlan:
        output_payload = payload.get("output_contract") or {}
        output_contract = None
        if isinstance(output_payload, dict) and output_payload.get("display_fields"):
            output_contract = OutputContract(
                mode=str(output_payload.get("mode") or "inferred"),
                display_grain=str(output_payload.get("display_grain") or ""),
                requested_fields=[str(item) for item in output_payload.get("requested_fields") or []],
                display_fields=[str(item) for item in output_payload.get("display_fields") or []],
                support_fields=[str(item) for item in output_payload.get("support_fields") or []],
                reason=str(output_payload.get("reason") or ""),
            )
        return QueryPlan(
            service_name=str(payload.get("service_name") or ""),
            entity_set=str(payload.get("entity_set") or ""),
            http_method="GET",
            select_fields=[str(item) for item in payload.get("select_fields") or []],
            response_summary_fields=[str(item) for item in payload.get("response_summary_fields") or []],
            top=SapClawRuntimeService._optional_positive_int(payload.get("top")),
            plan_kind=str(payload.get("plan_kind") or "direct"),
            target_entity_set=payload.get("target_entity_set"),
            output_contract=output_contract,
        )

    @staticmethod
    def _safe_int(value: Any, fallback: int) -> int:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _optional_positive_int(value: Any) -> int | None:
        try:
            parsed = int(str(value))
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _contains_chinese(value: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in str(value or ""))
