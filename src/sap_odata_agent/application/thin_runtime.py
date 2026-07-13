from __future__ import annotations

import json
import re
import time
import urllib.parse
import uuid
from dataclasses import asdict, replace
from datetime import datetime
from itertools import product
from typing import Any

from sap_odata_agent.application.result_transformer import ResultTransformer
from sap_odata_agent.application.schema_feasibility_validator import SchemaFeasibilityValidator
from sap_odata_agent.application.thin_models import (
    RuntimeCatalogRequest,
    RuntimeGetRequest,
    RuntimeGuidanceRequest,
    RuntimePageRequest,
    RuntimeSchemaRequest,
    ThinQueryPlan,
    validation_issue_payload,
)
from sap_odata_agent.domain.models import (
    AgentRequest,
    CompiledRequest,
    ExecutionAttempt,
    FilterCondition,
    FunctionParameter,
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


class ThinRuntimeService:
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
        self.index_loader = LocalIndexLoader(settings.index_root)
        self.page_size = max(1, settings.thin_runtime_page_size)
        self.max_binding_rows = max(1, settings.thin_runtime_max_binding_rows)

    def health(self) -> dict[str, Any]:
        indexed_count, executable_count = self._index_health_counts()
        enabled = bool(self.settings.thin_runtime_enabled)
        return self._envelope(
            ok=enabled,
            status="success" if enabled else "disabled",
            data={
                "backend": "ok",
                "runtime_enabled": enabled,
                "read_only": True,
                "indexed_service_count": indexed_count,
                "executable_service_count": executable_count,
                "index_root_exists": self.index_loader.index_root.exists(),
                "sap_base_url_configured": bool(self.settings.sap_base_url),
                "viewer_enabled": bool(self._viewer_base_url()),
            },
            error=None
            if enabled
            else {
                "code": "thin_runtime_disabled",
                "message": "Thin Runtime is disabled. Set THIN_RUNTIME_ENABLED=true to enable it.",
            },
        )

    def catalog(self, request: RuntimeCatalogRequest) -> dict[str, Any]:
        disabled = self._disabled_response()
        if disabled:
            return disabled
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
        disabled = self._disabled_response()
        if disabled:
            return disabled
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

        selected_fields: list[dict[str, Any]] = []
        if request.include_fields:
            for field in snapshot.fields:
                entity_set = str(field.get("entity_set") or "")
                field_name = str(field.get("field_name") or "")
                if field_scope and entity_set not in field_scope:
                    continue
                if candidate_field_refs and (entity_set, field_name) not in candidate_field_refs:
                    continue
                selected_fields.append(self._schema_field_payload(field))
                if len(selected_fields) >= request.max_fields:
                    break

        relation_scope = field_scope or set(entity_map)
        relations = [
            dict(item)
            for item in snapshot.relations
            if str(item.get("from_entity_set") or "") in relation_scope
        ]
        service = self._service_record(snapshot)
        return self._envelope(
            ok=True,
            data={
                "service": service,
                "entities": [
                    self._schema_entity_payload(entity_map[name])
                    for name in (requested_entities or list(entity_map))
                ],
                "fields": selected_fields,
                "relations": relations,
                "function_imports": function_imports_from_snapshot(snapshot),
                "fields_truncated": request.include_fields
                and len(selected_fields) >= request.max_fields
                and self._matching_field_count(snapshot, field_scope, candidate_field_refs) > len(selected_fields),
                "schema_authority": True,
            },
        )

    def guidance(self, request: RuntimeGuidanceRequest) -> dict[str, Any]:
        disabled = self._disabled_response()
        if disabled:
            return disabled
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

    def validate_plan(self, plan_model: ThinQueryPlan, user_input: str = "") -> dict[str, Any]:
        disabled = self._disabled_response()
        if disabled:
            return disabled
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
        plan_model: ThinQueryPlan,
        *,
        user_input: str = "",
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        disabled = self._disabled_response()
        if disabled:
            return disabled
        plan = plan_model.to_domain()
        issues = self._validate_domain_plan(plan, user_input)
        if issues:
            return self._envelope(
                ok=False,
                status="validation_failed",
                data={"plan": plan_model.model_dump(mode="json")},
                validation_issues=issues,
                error={"code": "plan_validation_failed", "message": "No SAP request was executed."},
            )

        case_id = str(uuid.uuid4())
        started = time.perf_counter()
        attempts, data, execution_error = self._execute_domain_plan(plan)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        success = execution_error is None and data is not None
        presentation = self._build_presentation(plan, data, user_input) if success else None
        executed_requests = [self._attempt_payload(item) for item in attempts]
        final_query_url = attempts[-1]["attempt"].request.url if attempts else None
        runtime_request = {
            "kind": "structured_plan",
            "plan": plan_model.model_dump(mode="json"),
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
        disabled = self._disabled_response()
        if disabled:
            return disabled
        issues, snapshot, root_name, is_function = self._validate_controlled_get(request)
        if issues or snapshot is None:
            return self._envelope(
                ok=False,
                status="validation_failed",
                validation_issues=issues,
                error={"code": "controlled_get_validation_failed", "message": "No SAP request was executed."},
            )

        case_id = str(uuid.uuid4())
        started = time.perf_counter()
        query_options = dict(request.query_options)
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
            data = self._apply_business_pagination(data, business_top=business_top, initial_skip=initial_skip)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        error = None if attempt.success else self._sap_error(attempt)
        plan = QueryPlan(
            service_name=request.service_name,
            entity_set=request.resource_path,
            http_method="GET",
            select_fields=self._split_option_fields(request.query_options.get("$select", "")),
            top=business_top,
            plan_kind="function_import" if is_function else "direct",
        )
        presentation = self._build_presentation(plan, data, request.user_input) if attempt.success else None
        runtime_request = {
            "kind": "controlled_get",
            "service_name": request.service_name,
            "resource_path": request.resource_path,
            "query_options": dict(request.query_options),
            "function_parameters": dict(request.function_parameters),
            "pagination": {
                "page_size": self.page_size,
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

    def page(self, request: RuntimePageRequest) -> dict[str, Any]:
        disabled = self._disabled_response()
        if disabled:
            return disabled
        entry = self.case_repository.get_by_case_id(request.case_id)
        if entry is None or entry.get("execution_origin") != "thin_mcp":
            return self._envelope(
                ok=False,
                status="not_found",
                case_id=request.case_id,
                error={"code": "case_not_found", "message": "Thin Runtime case not found."},
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
        known_total = self._safe_int(stored_data.get("result_count"), -1)
        if request.skip > 0 and known_total >= 0 and request.skip >= known_total:
            return self._envelope(
                ok=False,
                status="page_out_of_range",
                case_id=request.case_id,
                error={"code": "page_out_of_range", "message": "Requested page exceeds the result count."},
            )

        local_page = self._stored_page(stored_data, request.skip, page_size)
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
        disabled = self._disabled_response()
        if disabled:
            return disabled
        entry = self.case_repository.get_by_case_id(case_id)
        if entry is None or entry.get("execution_origin") != "thin_mcp":
            return self._envelope(
                ok=False,
                status="not_found",
                case_id=case_id,
                error={"code": "case_not_found", "message": "Thin Runtime case not found."},
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
            issues.append(validation_issue_payload("non_get_not_allowed", "Thin Runtime allows GET only.", "http_method"))
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

        for item in self.plan_validator.validate(plan):
            issues.append(
                validation_issue_payload(
                    "basic_plan_validation",
                    item.message,
                    item.field,
                )
            )

        schema_result = self.schema_validator.validate(AgentRequest(user_input=user_input), plan)
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
    ) -> tuple[list[dict[str, Any]], LocalIndexSnapshot | None, str, bool]:
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
        return self._dedupe_issues(issues), snapshot, root_name, is_function

    def _execute_domain_plan(
        self,
        plan: QueryPlan,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
        if not plan.steps:
            fetch_all = plan.result_transform is not None
            attempts, data, error = self._execute_query_window(
                plan,
                fetch_all=fetch_all,
                row_limit=self.max_binding_rows if fetch_all else None,
            )
            if error or data is None:
                return attempts, data, error
            return attempts, self.result_transformer.apply(plan, data), None

        attempts: list[dict[str, Any]] = []
        step_results: dict[str, dict[str, Any]] = {}
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
            final_data = self.result_transformer.apply(plan, final_data) or final_data
        merged = dict(final_data)
        merged["primary_step_id"] = self._primary_step_id(plan, step_results)
        merged["final_step_id"] = final_step.step_id
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
        execution_plan = replace(plan, top=transport_top)
        try:
            compiled = self.compiler.compile(execution_plan)
        except ValueError as exc:
            return [], None, {"code": "compile_failed", "message": str(exc)}

        attempts: list[dict[str, Any]] = []
        all_rows: list[dict[str, Any]] = []
        total_count = 0
        skip = 0
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
                return attempts, None, self._sap_error(attempt)
            preview = attempt.response_preview or {}
            if not fetch_all:
                return attempts, self._apply_business_pagination(preview, business_top=business_top), None
            rows = self._all_rows(preview)
            if not rows and "result" in preview:
                return attempts, preview, None
            all_rows.extend(rows)
            total_count = self._safe_int(preview.get("result_count"), len(all_rows))
            if business_top is not None and len(all_rows) >= business_top:
                all_rows = all_rows[:business_top]
                break
            if row_limit is not None and len(all_rows) > row_limit:
                return attempts, None, {
                    "code": "binding_row_limit_exceeded",
                    "message": f"Fetch-all exceeded the configured {row_limit} row limit.",
                }
            if len(rows) < transport_top or skip + len(rows) >= total_count:
                break
            if row_limit is not None and len(all_rows) >= row_limit:
                return attempts, None, {
                    "code": "binding_row_limit_exceeded",
                    "message": f"More than {row_limit} rows are required for a complete binding.",
                }
            skip += len(rows)
        return attempts, self._data_from_rows(all_rows, min(total_count, business_top or total_count), business_top), None

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
                    "llm_profile_id": None,
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
                        "key": f"thin.sap_request.{index + 1}",
                        "label": "SAP OData GET",
                        "duration_ms": item.get("duration_ms", 0),
                    }
                    for index, item in enumerate(attempts)
                ],
                "timing_summary": {"sap_execution_ms": sum(float(item.get("duration_ms") or 0) for item in attempts)},
                "total_duration_ms": duration_ms,
                "execution_origin": "thin_mcp",
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
                "origin": "thin_mcp",
                "read_only": True,
                "runtime_enabled": bool(self.settings.thin_runtime_enabled),
                **(metadata or {}),
            },
        }

    def _disabled_response(self) -> dict[str, Any] | None:
        if self.settings.thin_runtime_enabled:
            return None
        return self._envelope(
            ok=False,
            status="disabled",
            error={
                "code": "thin_runtime_disabled",
                "message": "Thin Runtime is disabled. Set THIN_RUNTIME_ENABLED=true to enable it.",
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
        skip = self._safe_int(pagination.get("skip"), initial_skip)
        raw_total = self._safe_int(data.get("result_count"), skip + len(rows))
        effective_total = min(raw_total, initial_skip + business_top) if business_top is not None else raw_total
        remaining = max(0, effective_total - skip)
        display_rows = rows[: min(self.page_size, remaining)]
        has_next = skip + len(display_rows) < effective_total
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
        values = [row.get(field_name) for row in ThinRuntimeService._all_rows(data) if row.get(field_name) is not None]
        return list(dict.fromkeys(values))

    @staticmethod
    def _has_zero_rows(data: dict[str, Any] | None) -> bool:
        if not isinstance(data, dict):
            return False
        return ThinRuntimeService._safe_int(data.get("result_count"), -1) == 0

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
        return {
            "code": "sap_request_failed",
            "message": attempt.error_message or "SAP OData request failed.",
            "status_code": attempt.status_code,
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
            "has_next": has_next,
            "next_skip": pagination.get("next_skip") if has_next else None,
        }

    def _viewer_base_url(self) -> str:
        if not self.settings.thin_runtime_viewer_enabled:
            return ""
        raw = self.settings.thin_runtime_viewer_base_url.rstrip("/")
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
        return QueryPlan(
            service_name=str(payload.get("service_name") or ""),
            entity_set=str(payload.get("entity_set") or ""),
            http_method="GET",
            select_fields=[str(item) for item in payload.get("select_fields") or []],
            response_summary_fields=[str(item) for item in payload.get("response_summary_fields") or []],
            top=ThinRuntimeService._optional_positive_int(payload.get("top")),
            plan_kind=str(payload.get("plan_kind") or "direct"),
            target_entity_set=payload.get("target_entity_set"),
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
