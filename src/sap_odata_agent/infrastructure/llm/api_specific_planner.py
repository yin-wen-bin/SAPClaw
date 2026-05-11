from __future__ import annotations

import json
import re
from datetime import date
from dataclasses import replace
from pathlib import Path
from typing import Any

from sap_odata_agent.domain.models import (
    AgentRequest,
    ApiRouteDecision,
    ExecutionStep,
    FilterCondition,
    QueryPlan,
    ResultTransform,
    StepBinding,
)
from sap_odata_agent.infrastructure.indexing.index_loader import LocalIndexSnapshot
from sap_odata_agent.infrastructure.llm.dynamic_path_planner import LlmDynamicPathPlanner
from sap_odata_agent.infrastructure.llm.planner import AnthropicCompatibleMessagesClient, LlmStructuredIntentPlanner
from sap_odata_agent.infrastructure.llm.prompts import (
    GLOBAL_SAP_ODATA_PROMPT,
    METADATA_MATCHING_TASK_PROMPT,
    QUERY_PLANNER_TASK_PROMPT,
)


class LlmApiSpecificPlanner(LlmDynamicPathPlanner):
    """API-specific LLM planner using pre-routed schema context."""

    def __init__(
        self,
        index_root: str = "data/index",
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(index_root=index_root, service_name="", llm_client=llm_client, enabled=enabled)

    def plan_for_api(
        self,
        request: AgentRequest,
        route_decision: ApiRouteDecision,
        schema_context: dict[str, Any],
    ) -> QueryPlan:
        service_name = str(schema_context.get("service_name") or self._selected_service(route_decision))
        if self._requires_purchase_order_history_clarification(request, service_name):
            return self._purchase_order_history_clarification_plan(service_name)
        if not self.enabled or self.llm_client is None:
            return self._unavailable_plan_for_service(service_name, "llm_unavailable")
        try:
            snapshot = self._load_schema_snapshot(service_name, schema_context)
        except FileNotFoundError:
            return self._unavailable_plan_for_service(service_name, "index_unavailable")
        try:
            raw = self.llm_client.complete_json(
                self._system_prompt(),
                self._user_prompt(request, route_decision, schema_context),
                max_tokens=2600,
            )
            parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
        except Exception as exc:
            return self._invalid_plan_for_service(service_name, f"llm_error:{exc}", schema_context)
        materialized = self._materialize_plan(parsed, snapshot, schema_context)
        if materialized is None:
            return self._invalid_plan_for_service(service_name, "llm_plan_not_materializable", schema_context, parsed)
        materialized = self._apply_skill_filter_patterns(materialized, request, schema_context)
        materialized = self._apply_skill_preferred_filter_fields(materialized, request, schema_context)
        materialized = self._apply_skill_select_only_patterns(materialized, request, schema_context)
        materialized = self._apply_skill_result_transform_patterns(materialized, request, schema_context)
        materialized = self._clear_skill_resolved_clarification(materialized)
        materialized = self._remove_unrequested_temporal_filters(materialized, request)
        materialized = self._apply_company_code_chart_of_accounts_bridge(materialized, request, schema_context)
        materialized = self._apply_profit_center_company_assignment_bridge(materialized, request, schema_context)
        materialized = self._normalize_profit_center_assignment_bindings(materialized)
        return replace(
            materialized,
            service_name=materialized.service_name or service_name,
            planner_diagnostics={
                **(materialized.planner_diagnostics or {}),
                "route_decision": route_decision.raw_response,
                "planner_type": "llm_api_specific_planner",
            },
        )

    @staticmethod
    def _system_prompt() -> str:
        return f"{GLOBAL_SAP_ODATA_PROMPT}\n\n{METADATA_MATCHING_TASK_PROMPT}\n\n{QUERY_PLANNER_TASK_PROMPT}"

    @staticmethod
    def _user_prompt(
        request: AgentRequest,
        route_decision: ApiRouteDecision,
        schema_context: dict[str, Any],
    ) -> str:
        example = {
            "plan_kind": "direct | multi_step | function_import | clarification | no_feasible_plan",
            "service_name": schema_context.get("service_name", ""),
            "entity_set": "",
            "http_method": "GET",
            "select_fields": [],
            "filters": [{"field": "", "operator": "eq", "value": "", "value_type": "string | boolean | number | date"}],
            "function_parameters": [
                {"name": "", "value": "", "value_type": "string | boolean | number | decimal | date | datetimeoffset"}
            ],
            "steps": [
                {
                    "step_id": "step_1",
                    "service_name": schema_context.get("service_name", ""),
                    "entity_set": "SourceEntitySet",
                    "select_fields": ["JoinField", "FilterField"],
                    "filters": [{"field": "FilterField", "operator": "eq", "value": "literal", "value_type": "string"}],
                    "filter_from_previous": [],
                    "top": 50,
                },
                {
                    "step_id": "step_2",
                    "service_name": schema_context.get("service_name", ""),
                    "entity_set": "TargetEntitySet",
                    "select_fields": ["JoinField", "AnswerField"],
                    "filters": [],
                    "filter_from_previous": [
                        {"field": "JoinField", "source_step_id": "step_1", "source_field": "JoinField"}
                    ],
                    "top": 50,
                },
            ],
            "target_entity_set": "",
            "target_fields": [],
            "business_level": "header | item | schedule_line | partner | address | account_assignment | status | history | unknown",
            "presentation": {"kind": "text | table", "reason": ""},
            "result_transform": {
                "type": "none | aggregate",
                "group_by": ["FieldName"],
                "sum_fields": ["NumericFieldName"],
            },
            "response_directive": "",
            "rationale": "",
        }
        payload = {
            "original_user_input": request.user_input,
            "resolved_user_input": route_decision.resolved_user_input or request.resolved_user_input or request.user_input,
            "current_date": date.today().isoformat(),
            "route_decision": {
                "selected_apis": [
                    {"service_name": item.service_name, "confidence": item.confidence, "reason": item.reason}
                    for item in route_decision.selected_apis
                ],
                "intent_summary": route_decision.intent_summary,
                "business_domain": route_decision.business_domain,
                "business_object": route_decision.business_object,
            },
            "schema_context": LlmApiSpecificPlanner._schema_context_prompt_payload(schema_context, request),
            "feedback_hints": request.feedback_hints,
            "feedback_memories": request.feedback_memories,
        }
        return (
            f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Planning rules:\n"
            "1. For multi_step plans, every step after the first must have either filters or filter_from_previous.\n"
            "2. Use filter_from_previous objects exactly as {\"field\": target_field_on_current_step, \"source_step_id\": previous_step_id, \"source_field\": field_selected_by_previous_step}.\n"
            "3. Select every source_field in its source step and every binding field in its target step.\n"
            "4. Set filter.value_type from the schema field data_type; use boolean for Edm.Boolean filters.\n\n"
            "5. Use schema_context.schema_research when present as the primary business-semantic analysis.\n"
            "6. Distinguish requirement/expected flags from completion/open status fields; do not treat similarly named fields as equivalent.\n\n"
            "7. If the intended target entity does not contain the binding target field, insert an intermediate bridge entity that contains both the previous join field and the final target key.\n"
            "8. For example, do not bind BusinessPartner directly onto an entity that only has Supplier or Customer; first use an entity that contains BusinessPartner and Supplier/Customer, then bind the final key.\n\n"
            "9. For function imports listed in schema_context.function_imports, set plan_kind=function_import and put inputs in function_parameters using the exact parameter names and value_type from schema_context.\n"
            "10. Do not put function import inputs in filters and do not set top/select/order_by for function_import plans.\n\n"
            "11. If schema_context.api_skill or schema_context.api_skills identify a more specific entity for the user's business meaning, prefer that entity over a less specific similarly named field. Do not conclude 'not maintained' from a blank less specific field until the skill-preferred entity has been checked.\n\n"
            "12. If schema_context.api_skill or schema_context.api_skills contains a Common Planning Pattern that matches the user's wording, treat that pattern as schema-verified business guidance: use its entity, select fields, and filters when those fields exist in schema_context.\n\n"
            "13. Treat document history requests as ambiguous unless schema_context exposes a true history, movement, receipt, invoice, or change-history entity. Do not answer a history request by returning only pricing, notes, account assignments, or other detail child entities.\n\n"
            "14. Treat bare \"with/include/show/display\" field-list wording as requested output fields, not filters. Add filters only for explicit restrictions, comparisons, literal values, true/false requirements, nonzero/open/closed conditions, schema-verified business conditions, or a matching api_skill Common Planning Pattern.\n\n"
            "15. If schema_context.service_names contains multiple services, every multi_step step must include service_name. Use cross-service join_hints or shared key fields to bridge between services, and only use entity sets and fields from that step's service.\n\n"
            "16. If the user provides a company code and asks for G/L account records in a chart-of-accounts-scoped API, first query API_COMPANYCODE_SRV.A_CompanyCode.ChartOfAccounts and bind that value to the G/L account step. Do not use the company code literal as A_GLAccountInChartOfAccounts.ChartOfAccounts.\n\n"
            "17. If the user asks for an output level such as material level, plant level, storage-location level, batch level, or another summarized level, choose fields for the raw SAP query and set result_transform.type=aggregate with schema-valid group_by and sum_fields. The program will execute the aggregation; do not calculate totals in text.\n\n"
            "Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _schema_context_prompt_payload(
        schema_context: dict[str, Any],
        request: AgentRequest,
    ) -> dict[str, Any]:
        query = request.resolved_user_input or request.user_input or str(schema_context.get("query") or "")

        def compact_field(field: dict[str, Any]) -> dict[str, Any]:
            payload = {
                "service_name": field.get("service_name", ""),
                "entity_set": field.get("entity_set", ""),
                "field_name": field.get("field_name", ""),
                "label": field.get("label", ""),
                "data_type": field.get("data_type", ""),
                "filterable": field.get("filterable", False),
            }
            description = str(field.get("description") or "").strip()
            if description:
                payload["description"] = LlmApiSpecificPlanner._truncate_prompt_value(description, 80)
            return {key: value for key, value in payload.items() if value not in ("", [], {})}

        def compact_entity(entity: dict[str, Any]) -> dict[str, Any]:
            fields = [
                compact_field({**field, "entity_set": field.get("entity_set") or entity.get("entity_set", "")})
                for field in entity.get("fields", [])[:24]
                if isinstance(field, dict)
            ]
            return {
                "service_name": entity.get("service_name", ""),
                "entity_set": entity.get("entity_set", ""),
                "kind": entity.get("kind", "entity_set"),
                "description": LlmApiSpecificPlanner._truncate_prompt_value(str(entity.get("description") or ""), 120),
                "key_fields": entity.get("key_fields", []),
                "default_select_fields": entity.get("default_select_fields", [])[:12],
                "supports_filter": entity.get("supports_filter", True),
                "supports_top": entity.get("supports_top", True),
                "fields": fields,
            }

        def compact_skill(skill: dict[str, Any]) -> dict[str, Any]:
            return {
                "service_name": skill.get("service_name", ""),
                "path": skill.get("path", ""),
                "summary": LlmApiSpecificPlanner._truncate_prompt_value(str(skill.get("summary") or ""), 3600),
            }

        selected_entities = LlmApiSpecificPlanner._select_prompt_entities(schema_context)
        payload: dict[str, Any] = {
            "service_name": schema_context.get("service_name", ""),
            "service_names": schema_context.get("service_names", [schema_context.get("service_name", "")]),
            "services": schema_context.get("services", []),
            "service": schema_context.get("service", {}),
            "multi_api": schema_context.get("multi_api", False),
            "route_decision": schema_context.get("route_decision", {}),
            "entities": [
                compact_entity(entity)
                for entity in selected_entities
                if isinstance(entity, dict)
            ],
            "candidate_fields": [
                compact_field(field)
                for field in schema_context.get("candidate_fields", [])[:80]
                if isinstance(field, dict)
            ],
            "join_hints": schema_context.get("join_hints", [])[:30],
            "relations": schema_context.get("relations", [])[:24],
            "retrieved_documents": schema_context.get("retrieved_documents", [])[:8],
            "feedback_memories": schema_context.get("feedback_memories", [])[:5],
            "feedback_field_matches": schema_context.get("feedback_field_matches", []),
            "skill_field_matches": schema_context.get("skill_field_matches", []),
            "schema_research": schema_context.get("schema_research", {}),
        }
        api_skill = schema_context.get("api_skill") or {}
        api_skills = [
            compact_skill(skill)
            for skill in schema_context.get("api_skills", [])
            if isinstance(skill, dict)
        ]
        if api_skills:
            payload["api_skills"] = api_skills[:6]
        elif isinstance(api_skill, dict) and api_skill:
            payload["api_skill"] = compact_skill(api_skill)
        if LlmApiSpecificPlanner._should_include_function_imports(query, schema_context):
            payload["function_imports"] = [
                LlmApiSpecificPlanner._compact_function_import(item)
                for item in schema_context.get("function_imports", [])[:12]
                if isinstance(item, dict)
            ]
        return payload

    @staticmethod
    def _apply_skill_filter_patterns(
        plan: QueryPlan,
        request: AgentRequest,
        schema_context: dict[str, Any],
    ) -> QueryPlan:
        requirements = LlmApiSpecificPlanner._matching_skill_filter_requirements(request, schema_context)
        if not requirements:
            return plan

        steps = list(plan.steps or [])
        plan_filters = list(plan.filters or [])
        plan_select_fields = list(plan.select_fields or [])
        plan_summary_fields = list(plan.response_summary_fields or [])
        applied: list[dict[str, str]] = []

        def add_filter_to_fields(
            filters: list[FilterCondition],
            select_fields: list[str],
            summary_fields: list[str],
            requirement: dict[str, str],
            entity_set: str,
        ) -> bool:
            field = requirement["field"]
            operator = requirement["operator"]
            value = requirement["value"]
            value_type = requirement["value_type"]
            changed = False
            if any(
                item.field == field
                and item.operator.lower() == operator
                and LlmApiSpecificPlanner._normalise_filter_literal(item.value) == LlmApiSpecificPlanner._normalise_filter_literal(value)
                for item in filters
            ):
                pass
            else:
                filters.append(FilterCondition(field=field, operator=operator, value=value, value_type=value_type))
                changed = True
            select_only_fields = LlmApiSpecificPlanner._skill_line_select_only_fields(
                requirement.get("skill_line", ""),
                entity_set,
            )
            if select_only_fields:
                select_fields[:] = select_only_fields
                summary_fields[:] = select_only_fields
                changed = True
            else:
                if field not in select_fields:
                    select_fields.append(field)
                    changed = True
                if field not in summary_fields:
                    summary_fields.append(field)
                    changed = True
            return changed

        if steps:
            updated_steps: list[ExecutionStep] = []
            for step in steps:
                step_filters = list(step.filters or [])
                step_select_fields = list(step.select_fields or [])
                step_summary_fields = list(step.response_summary_fields or [])
                for requirement in requirements:
                    entity_set = requirement.get("entity_set") or ""
                    if entity_set and step.entity_set != entity_set:
                        continue
                    if not entity_set and not LlmApiSpecificPlanner._schema_entity_has_filterable_field(
                        schema_context,
                        step.entity_set,
                        requirement["field"],
                    ):
                        continue
                    if add_filter_to_fields(
                        step_filters,
                        step_select_fields,
                        step_summary_fields,
                        requirement,
                        step.entity_set,
                    ):
                        applied.append({**requirement, "entity_set": step.entity_set})
                updated_steps.append(
                    replace(
                        step,
                        filters=step_filters,
                        select_fields=step_select_fields,
                        response_summary_fields=step_summary_fields,
                    )
                )
            steps = updated_steps
        else:
            for requirement in requirements:
                entity_set = requirement.get("entity_set") or ""
                if entity_set and plan.entity_set != entity_set:
                    continue
                if not entity_set and not LlmApiSpecificPlanner._schema_entity_has_filterable_field(
                    schema_context,
                    plan.entity_set,
                    requirement["field"],
                ):
                    continue
                if add_filter_to_fields(
                    plan_filters,
                    plan_select_fields,
                    plan_summary_fields,
                    requirement,
                    plan.entity_set,
                ):
                    applied.append({**requirement, "entity_set": plan.entity_set})

        if not applied:
            return plan
        return replace(
            plan,
            filters=plan_filters,
            select_fields=plan_select_fields,
            response_summary_fields=plan_summary_fields,
            steps=steps,
            planner_diagnostics={
                **(plan.planner_diagnostics or {}),
                "api_skill_applied_filters": applied,
            },
        )

    @staticmethod
    def _apply_skill_preferred_filter_fields(
        plan: QueryPlan,
        request: AgentRequest,
        schema_context: dict[str, Any],
    ) -> QueryPlan:
        requirements = LlmApiSpecificPlanner._matching_skill_preferred_filter_fields(request, schema_context)
        if not requirements:
            return plan

        applied: list[dict[str, Any]] = []

        def replace_filter_fields(filters: list[FilterCondition], entity_set: str) -> list[FilterCondition]:
            updated: list[FilterCondition] = []
            for item in filters:
                replacement = item
                for requirement in requirements:
                    if requirement["entity_set"] != entity_set:
                        continue
                    if item.field not in requirement["discouraged_fields"]:
                        continue
                    preferred_field = requirement["field"]
                    if not LlmApiSpecificPlanner._schema_entity_has_filterable_field(
                        schema_context,
                        entity_set,
                        preferred_field,
                    ):
                        continue
                    replacement = replace(item, field=preferred_field)
                    applied.append(
                        {
                            **requirement,
                            "entity_set": entity_set,
                            "from_field": item.field,
                            "to_field": preferred_field,
                        }
                    )
                    break
                updated.append(replacement)
            return updated

        if plan.steps:
            steps = [
                replace(step, filters=replace_filter_fields(list(step.filters or []), step.entity_set))
                for step in plan.steps
            ]
            plan = replace(plan, steps=steps)
        else:
            plan = replace(plan, filters=replace_filter_fields(list(plan.filters or []), plan.entity_set))

        if not applied:
            return plan
        return replace(
            plan,
            planner_diagnostics={
                **(plan.planner_diagnostics or {}),
                "api_skill_preferred_filter_fields": applied,
            },
        )

    @staticmethod
    def _apply_skill_select_only_patterns(
        plan: QueryPlan,
        request: AgentRequest,
        schema_context: dict[str, Any],
    ) -> QueryPlan:
        requirements = LlmApiSpecificPlanner._matching_skill_select_only_requirements(request, schema_context)
        if not requirements:
            return plan

        steps = list(plan.steps or [])
        applied: list[dict[str, Any]] = []

        def valid_fields(entity_set: str, fields: list[str]) -> list[str]:
            return list(fields)

        if steps:
            updated_steps: list[ExecutionStep] = []
            for step_index, step in enumerate(steps):
                step_select_fields = list(step.select_fields or [])
                step_summary_fields = list(step.response_summary_fields or [])
                for requirement in requirements:
                    entity_set = requirement.get("entity_set") or ""
                    if entity_set and step.entity_set != entity_set:
                        continue
                    selected = valid_fields(step.entity_set, requirement["fields"])
                    if not selected:
                        continue
                    step_select_fields = selected
                    step_summary_fields = selected
                    applied.append(
                        {
                            **requirement,
                            "entity_set": step.entity_set,
                            "step_id": step.step_id,
                            "step_index": step_index,
                        }
                    )
                    break
                updated_steps.append(
                    replace(
                        step,
                        select_fields=step_select_fields,
                        response_summary_fields=step_summary_fields,
                    )
                )
            steps = updated_steps
            promoted = LlmApiSpecificPlanner._promotable_skill_select_only_step(steps, applied)
            if promoted is not None:
                target_step, target_index, applied_entry = promoted
                steps = steps[: target_index + 1]
                diagnostics = {
                    **(plan.planner_diagnostics or {}),
                    "api_skill_applied_select_only": applied,
                    "api_skill_promoted_target_step": {
                        "step_id": target_step.step_id,
                        "entity_set": target_step.entity_set,
                        "skill_line": applied_entry.get("skill_line", ""),
                    },
                }
                return replace(
                    plan,
                    service_name=target_step.service_name or plan.service_name,
                    entity_set=target_step.entity_set,
                    filters=list(target_step.filters or []),
                    select_fields=list(target_step.select_fields or []),
                    response_summary_fields=list(target_step.response_summary_fields or []),
                    order_by=list(target_step.order_by or []),
                    top=target_step.top,
                    steps=steps,
                    target_entity_set=target_step.entity_set,
                    response_directive="",
                    planner_diagnostics=diagnostics,
                )
        else:
            plan_select_fields = list(plan.select_fields or [])
            plan_summary_fields = list(plan.response_summary_fields or [])
            for requirement in requirements:
                entity_set = requirement.get("entity_set") or ""
                if entity_set and plan.entity_set != entity_set:
                    continue
                selected = valid_fields(plan.entity_set, requirement["fields"])
                if not selected:
                    continue
                plan_select_fields = selected
                plan_summary_fields = selected
                applied.append({**requirement, "entity_set": plan.entity_set})
                break
            if applied:
                return replace(
                    plan,
                    select_fields=plan_select_fields,
                    response_summary_fields=plan_summary_fields,
                    planner_diagnostics={
                        **(plan.planner_diagnostics or {}),
                        "api_skill_applied_select_only": applied,
                    },
                )

        if not applied:
            return plan
        return replace(
            plan,
            select_fields=steps[-1].select_fields if steps else plan.select_fields,
            response_summary_fields=steps[-1].response_summary_fields if steps else plan.response_summary_fields,
            steps=steps,
            planner_diagnostics={
                **(plan.planner_diagnostics or {}),
                "api_skill_applied_select_only": applied,
            },
        )

    @staticmethod
    def _apply_skill_result_transform_patterns(
        plan: QueryPlan,
        request: AgentRequest,
        schema_context: dict[str, Any],
    ) -> QueryPlan:
        requirements = LlmApiSpecificPlanner._matching_skill_result_transform_requirements(request, schema_context)
        if not requirements:
            return plan

        def applicable_requirement(entity_set: str) -> dict[str, Any] | None:
            for requirement in requirements:
                if requirement.get("entity_set") != entity_set:
                    continue
                fields = [*requirement.get("group_by", []), *requirement.get("sum_fields", [])]
                if all(LlmApiSpecificPlanner._schema_entity_has_field(schema_context, entity_set, field) for field in fields):
                    return requirement
            return None

        applied: dict[str, Any] | None = None
        if plan.steps:
            updated_steps: list[ExecutionStep] = []
            for step in plan.steps:
                requirement = applicable_requirement(step.entity_set)
                if requirement is None:
                    updated_steps.append(step)
                    continue
                fields = [*requirement["group_by"], *requirement["sum_fields"]]
                selected = LlmDynamicPathPlanner._dedupe_fields([*list(step.select_fields or []), *fields])
                updated_steps.append(
                    replace(
                        step,
                        select_fields=selected,
                        response_summary_fields=fields,
                    )
                )
                if applied is None:
                    applied = {**requirement, "step_id": step.step_id}
            if applied is None:
                return plan
            transform = ResultTransform(
                type="aggregate",
                group_by=list(applied["group_by"]),
                sum_fields=list(applied["sum_fields"]),
            )
            target_step = next(
                (step for step in updated_steps if step.step_id == applied.get("step_id")),
                updated_steps[-1],
            )
            return replace(
                plan,
                select_fields=list(target_step.select_fields or []),
                response_summary_fields=[*transform.group_by, *transform.sum_fields],
                target_entity_set=target_step.entity_set,
                steps=updated_steps,
                result_transform=transform,
                planner_diagnostics={
                    **(plan.planner_diagnostics or {}),
                    "api_skill_applied_result_transform": applied,
                },
            )

        requirement = applicable_requirement(plan.entity_set)
        if requirement is None:
            return plan
        fields = [*requirement["group_by"], *requirement["sum_fields"]]
        transform = ResultTransform(
            type="aggregate",
            group_by=list(requirement["group_by"]),
            sum_fields=list(requirement["sum_fields"]),
        )
        return replace(
            plan,
            select_fields=LlmDynamicPathPlanner._dedupe_fields([*list(plan.select_fields or []), *fields]),
            response_summary_fields=fields,
            result_transform=transform,
            planner_diagnostics={
                **(plan.planner_diagnostics or {}),
                "api_skill_applied_result_transform": requirement,
            },
        )

    @staticmethod
    def _promotable_skill_select_only_step(
        steps: list[ExecutionStep],
        applied: list[dict[str, Any]],
    ) -> tuple[ExecutionStep, int, dict[str, Any]] | None:
        if len(steps) < 2 or not applied:
            return None
        final_index = len(steps) - 1
        if any(LlmApiSpecificPlanner._safe_step_index(item) == final_index for item in applied):
            return None
        candidates: list[dict[str, Any]] = []
        for item in applied:
            line = str(item.get("skill_line") or "").lower()
            if not any(marker in line for marker in ("answer from", "do not add", "do not query", "do not continue")):
                continue
            step_index = LlmApiSpecificPlanner._safe_step_index(item)
            if 0 <= step_index < len(steps):
                candidates.append(item)
        if not candidates:
            return None
        selected = sorted(
            candidates,
            key=lambda item: (int(item.get("match_score") or 0), LlmApiSpecificPlanner._safe_step_index(item)),
            reverse=True,
        )[0]
        step_index = LlmApiSpecificPlanner._safe_step_index(selected)
        return steps[step_index], step_index, selected

    @staticmethod
    def _safe_step_index(item: dict[str, Any]) -> int:
        raw_index = item.get("step_index")
        if raw_index is None:
            return -1
        try:
            return int(raw_index)
        except (TypeError, ValueError):
            return -1

    @staticmethod
    def _clear_skill_resolved_clarification(plan: QueryPlan) -> QueryPlan:
        if not plan.needs_clarification:
            return plan
        diagnostics = plan.planner_diagnostics or {}
        has_skill_resolution = bool(diagnostics.get("api_skill_applied_filters")) or bool(
            diagnostics.get("api_skill_applied_select_only")
        )
        if not has_skill_resolution or not plan.entity_set or not plan.select_fields:
            return plan
        return replace(
            plan,
            needs_clarification=False,
            clarification_question=None,
            clarification_options=[],
            response_directive="",
            planner_diagnostics={
                **diagnostics,
                "api_skill_cleared_clarification": True,
            },
        )

    @staticmethod
    def _apply_company_code_chart_of_accounts_bridge(
        plan: QueryPlan,
        request: AgentRequest,
        schema_context: dict[str, Any],
    ) -> QueryPlan:
        gl_service = "API_GLACCOUNTINCHARTOFACCOUNTS_SRV"
        company_service = "API_COMPANYCODE_SRV"
        gl_entity = "A_GLAccountInChartOfAccounts"
        company_entity = "A_CompanyCode"
        company_code = LlmApiSpecificPlanner._company_code_literal_from_request(request)
        if not company_code:
            return plan
        if not LlmApiSpecificPlanner._schema_context_has_service(schema_context, company_service):
            return plan
        if not LlmApiSpecificPlanner._schema_context_has_service(schema_context, gl_service):
            return plan

        source_step: ExecutionStep | None = None
        if plan.steps:
            if len(plan.steps) != 1:
                return plan
            source_step = plan.steps[0]
            step_service = source_step.service_name or plan.service_name
            entity_set = source_step.entity_set
            select_fields = list(source_step.select_fields or [])
            summary_fields = list(source_step.response_summary_fields or [])
            filters = list(source_step.filters or [])
            top = source_step.top
        else:
            step_service = plan.service_name
            entity_set = plan.entity_set
            select_fields = list(plan.select_fields or [])
            summary_fields = list(plan.response_summary_fields or [])
            filters = list(plan.filters or [])
            top = plan.top

        if step_service != gl_service or entity_set != gl_entity:
            return plan

        remaining_filters: list[FilterCondition] = []
        removed_wrong_chart_filter = False
        for condition in filters:
            if condition.field == "ChartOfAccounts" and condition.operator.lower() == "eq":
                removed_wrong_chart_filter = True
                continue
            remaining_filters.append(condition)

        has_chart_binding = any(
            binding.field == "ChartOfAccounts"
            for binding in (source_step.filter_from_previous if source_step else [])
        )
        if has_chart_binding:
            return plan

        if "ChartOfAccounts" not in select_fields:
            select_fields.insert(0, "ChartOfAccounts")
        if "GLAccount" not in select_fields:
            select_fields.append("GLAccount")
        if not summary_fields:
            summary_fields = select_fields[:6]

        company_step = ExecutionStep(
            step_id="step_1",
            service_name=company_service,
            entity_set=company_entity,
            select_fields=["CompanyCode", "ChartOfAccounts"],
            response_summary_fields=["CompanyCode", "ChartOfAccounts"],
            filters=[
                FilterCondition(
                    field="CompanyCode",
                    operator="eq",
                    value=company_code,
                    value_type="string",
                )
            ],
            top=5,
            rationale="Resolve the company code's assigned chart of accounts before querying G/L accounts.",
        )
        gl_step = ExecutionStep(
            step_id="step_2",
            service_name=gl_service,
            entity_set=gl_entity,
            select_fields=select_fields,
            response_summary_fields=summary_fields,
            filters=remaining_filters,
            filter_from_previous=[
                StepBinding(
                    field="ChartOfAccounts",
                    source_step_id="step_1",
                    source_field="ChartOfAccounts",
                )
            ],
            order_by=list(source_step.order_by if source_step else plan.order_by or []),
            top=top,
            rationale="Use ChartOfAccounts resolved from the company code rather than the company code literal.",
        )
        diagnostics = {
            **(plan.planner_diagnostics or {}),
            "api_skill_company_code_chart_bridge": {
                "source": "company_code_chart_of_accounts_bridge",
                "company_code": company_code,
                "removed_wrong_chart_filter": removed_wrong_chart_filter,
            },
        }
        return replace(
            plan,
            service_name=gl_service,
            entity_set=gl_entity,
            plan_kind="multi_step",
            filters=company_step.filters,
            select_fields=gl_step.select_fields,
            response_summary_fields=gl_step.response_summary_fields,
            steps=[company_step, gl_step],
            top=gl_step.top,
            target_entity_set=gl_entity,
            planner_diagnostics=diagnostics,
        )

    @staticmethod
    def _remove_unrequested_temporal_filters(plan: QueryPlan, request: AgentRequest) -> QueryPlan:
        request_text = f"{request.resolved_user_input or ''} {request.user_input or ''}".strip()
        if LlmApiSpecificPlanner._has_temporal_intent(request_text):
            return plan

        removed: list[dict[str, Any]] = []

        def keep_filter(condition: FilterCondition) -> bool:
            if not LlmApiSpecificPlanner._is_temporal_field(condition.field):
                return True
            value = str(condition.value if condition.value is not None else "").strip("'\"")
            if value and value in request_text:
                return True
            removed.append(
                {
                    "field": condition.field,
                    "operator": condition.operator,
                    "value": condition.value,
                    "reason": "temporal_filter_not_requested_by_user",
                }
            )
            return False

        changed = False
        steps = list(plan.steps or [])
        if steps:
            updated_steps: list[ExecutionStep] = []
            for step in steps:
                original_filters = list(step.filters or [])
                filtered = [condition for condition in original_filters if keep_filter(condition)]
                if len(filtered) != len(original_filters):
                    changed = True
                updated_steps.append(replace(step, filters=filtered))
            steps = updated_steps
        else:
            original_filters = list(plan.filters or [])
            filtered = [condition for condition in original_filters if keep_filter(condition)]
            if len(filtered) != len(original_filters):
                changed = True
        if not changed:
            return plan
        diagnostics = {
            **(plan.planner_diagnostics or {}),
            "removed_unrequested_temporal_filters": removed,
        }
        if steps:
            return replace(plan, steps=steps, planner_diagnostics=diagnostics)
        return replace(plan, filters=filtered, planner_diagnostics=diagnostics)

    @staticmethod
    def _has_temporal_intent(request_text: str) -> bool:
        text = str(request_text or "").lower()
        markers = (
            "日期",
            "期间",
            "年度",
            "年份",
            "财年",
            "会计年度",
            "会计期间",
            "月份",
            "月度",
            "今年",
            "本年",
            "去年",
            "明年",
            "今天",
            "昨日",
            "昨天",
            "明天",
            "date",
            "year",
            "period",
            "month",
            "today",
            "yesterday",
            "tomorrow",
            "current year",
            "fiscal",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _is_temporal_field(field_name: str) -> bool:
        field = str(field_name or "")
        exact = {
            "FiscalYear",
            "FiscalYearPeriod",
            "LedgerFiscalYear",
            "FiscalPeriod",
            "PostingDate",
            "DocumentDate",
            "CreationDate",
            "CreatedOn",
            "LastChangeDate",
        }
        if field in exact:
            return True
        lowered = field.lower()
        return lowered.endswith("date") or lowered.endswith("datetime")

    @staticmethod
    def _apply_profit_center_company_assignment_bridge(
        plan: QueryPlan,
        request: AgentRequest,
        schema_context: dict[str, Any],
    ) -> QueryPlan:
        service_name = "API_PROFITCENTER_SRV"
        assignment_entity = "A_PrftCtrCompanyCodeAssignment"
        profit_center_entity = "A_ProfitCenter"
        company_code = LlmApiSpecificPlanner._company_code_literal_from_request(request)
        if not company_code or plan.steps:
            return plan
        if plan.service_name != service_name or plan.entity_set != profit_center_entity:
            return plan
        if not LlmApiSpecificPlanner._schema_context_has_entity(schema_context, service_name, assignment_entity):
            return plan
        has_company_filter = any(
            condition.field == "CompanyCode"
            and condition.operator.lower() == "eq"
            and LlmApiSpecificPlanner._normalise_filter_literal(condition.value)
            == LlmApiSpecificPlanner._normalise_filter_literal(company_code)
            for condition in plan.filters
        )
        if not has_company_filter:
            return plan

        remaining_filters = [
            condition
            for condition in plan.filters
            if not (condition.field == "CompanyCode" and condition.operator.lower() == "eq")
        ]
        if remaining_filters:
            return plan
        select_fields = list(plan.select_fields or [])
        for field in ("ControllingArea", "ProfitCenter"):
            if field not in select_fields:
                select_fields.insert(0, field)
        summary_fields = list(plan.response_summary_fields or select_fields[:6])
        for field in ("ControllingArea", "ProfitCenter"):
            if field not in summary_fields:
                summary_fields.insert(0, field)

        assignment_step = ExecutionStep(
            step_id="step_1",
            service_name=service_name,
            entity_set=assignment_entity,
            select_fields=["ControllingArea", "ProfitCenter", "CompanyCode"],
            response_summary_fields=["ControllingArea", "ProfitCenter", "CompanyCode"],
            filters=[
                FilterCondition(
                    field="CompanyCode",
                    operator="eq",
                    value=company_code,
                    value_type="string",
                )
            ],
            top=50,
            rationale="Resolve profit centers assigned to the company code before reading profit center master attributes.",
        )
        profit_center_step = ExecutionStep(
            step_id="step_2",
            service_name=service_name,
            entity_set=profit_center_entity,
            select_fields=select_fields,
            response_summary_fields=summary_fields,
            filters=remaining_filters,
            filter_from_previous=[
                StepBinding(
                    field="ProfitCenter",
                    source_step_id="step_1",
                    source_field="ProfitCenter",
                )
            ],
            top=plan.top,
            rationale="Read profit center attributes for the company-assigned profit centers.",
        )
        return replace(
            plan,
            plan_kind="multi_step",
            filters=assignment_step.filters,
            select_fields=profit_center_step.select_fields,
            response_summary_fields=profit_center_step.response_summary_fields,
            steps=[assignment_step, profit_center_step],
            target_entity_set=profit_center_entity,
            planner_diagnostics={
                **(plan.planner_diagnostics or {}),
                "api_skill_profit_center_company_assignment_bridge": {
                    "company_code": company_code,
                    "source": "profit_center_company_assignment_bridge",
                },
            },
        )

    @staticmethod
    def _normalize_profit_center_assignment_bindings(plan: QueryPlan) -> QueryPlan:
        if plan.service_name != "API_PROFITCENTER_SRV" or not plan.steps:
            return plan
        changed = False
        updated_steps: list[ExecutionStep] = []
        for step in plan.steps:
            bindings = list(step.filter_from_previous or [])
            if step.entity_set == "A_ProfitCenter" and any(
                binding.source_step_id
                and binding.field == "ControllingArea"
                for binding in bindings
            ):
                filtered_bindings = [
                    binding
                    for binding in bindings
                    if binding.field != "ControllingArea"
                ]
                if len(filtered_bindings) != len(bindings):
                    bindings = filtered_bindings
                    changed = True
            updated_steps.append(replace(step, filter_from_previous=bindings))
        if not changed:
            return plan
        return replace(
            plan,
            steps=updated_steps,
            planner_diagnostics={
                **(plan.planner_diagnostics or {}),
                "normalized_profit_center_assignment_bindings": {
                    "removed_target_fields": ["ControllingArea"],
                    "reason": "Company-code profit-center assignment lookups bind A_ProfitCenter by ProfitCenter only.",
                },
            },
        )

    @staticmethod
    def _schema_context_has_entity(schema_context: dict[str, Any], service_name: str, entity_set: str) -> bool:
        for entity in schema_context.get("entities", []):
            if not isinstance(entity, dict):
                continue
            if str(entity.get("service_name") or service_name) == service_name and str(entity.get("entity_set") or "") == entity_set:
                return True
        return False

    @staticmethod
    def _company_code_literal_from_request(request: AgentRequest) -> str:
        text = f"{request.resolved_user_input or ''} {request.user_input or ''}"
        patterns = (
            r"(?:公司代码|公司|company\s*code|company)\s*[:：#-]?\s*([A-Za-z0-9]{3,8})",
            r"([A-Za-z0-9]{3,8})\s*(?:公司代码|公司|company\s*code|company)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _schema_context_has_service(schema_context: dict[str, Any], service_name: str) -> bool:
        service_names = {
            str(item).strip()
            for item in schema_context.get("service_names", [])
            if str(item).strip()
        }
        service_names.add(str(schema_context.get("service_name") or ""))
        for service in schema_context.get("services", []):
            if isinstance(service, dict):
                service_names.add(str(service.get("service_name") or ""))
        for entity in schema_context.get("entities", []):
            if isinstance(entity, dict):
                service_names.add(str(entity.get("service_name") or ""))
        return service_name in service_names

    @staticmethod
    def _matching_skill_filter_requirements(
        request: AgentRequest,
        schema_context: dict[str, Any],
    ) -> list[dict[str, str]]:
        request_text = f"{request.resolved_user_input or ''} {request.user_input or ''}".strip()
        if not request_text:
            return []
        requirements: list[dict[str, str]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for line in LlmApiSpecificPlanner._iter_skill_lines(schema_context):
            if not re.search(r"\s(?:eq|ne)\s", line, flags=re.IGNORECASE):
                continue
            if not LlmApiSpecificPlanner._skill_line_matches_request(line, request_text):
                continue
            for match in re.finditer(
                r"`?(?:(?P<entity>[A-Za-z_][A-Za-z0-9_]*)\.)?(?P<field>[A-Za-z_][A-Za-z0-9_]*)\s+"
                r"(?P<operator>eq|ne)\s+(?P<literal>true|false|''|\"\"|'[^']{1,40}'|\"[^\"]{1,40}\")`?",
                line,
                flags=re.IGNORECASE,
            ):
                prefix = line[max(0, match.start() - 40) : match.start()].lower()
                if any(marker in prefix for marker in ("do not", "don't", "不要", "不应", "不能")):
                    continue
                entity_set = match.group("entity") or ""
                field = match.group("field") or ""
                operator = match.group("operator").lower()
                raw_literal = match.group("literal")
                if not field:
                    continue
                if "<" in raw_literal or ">" in raw_literal:
                    continue
                value, value_type = LlmApiSpecificPlanner._skill_filter_literal(raw_literal)
                key = (entity_set, field, operator, LlmApiSpecificPlanner._normalise_filter_literal(value))
                if key in seen:
                    continue
                seen.add(key)
                source = "api_skill_nonblank_filter" if operator == "ne" and value == "" else "api_skill_filter"
                requirements.append(
                    {
                        "entity_set": entity_set,
                        "field": field,
                        "operator": operator,
                        "value": value,
                        "value_type": value_type,
                        "source": source,
                        "skill_line": line,
                    }
                )
        return requirements

    @staticmethod
    def _matching_skill_preferred_filter_fields(
        request: AgentRequest,
        schema_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        request_text = f"{request.resolved_user_input or ''} {request.user_input or ''}".strip()
        if not request_text:
            return []
        requirements: list[dict[str, Any]] = []
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        for line in LlmApiSpecificPlanner._iter_skill_lines(schema_context):
            lowered = line.lower()
            if "use filter field" not in lowered:
                continue
            if not any(marker in lowered for marker in ("do not use", "instead of", "rather than")):
                continue
            score = LlmApiSpecificPlanner._skill_line_match_score(line, request_text)
            if score <= 0:
                continue
            preferred = re.search(
                r"use filter field\s+`(?P<entity>[A-Za-z_][A-Za-z0-9_]*)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)`",
                line,
                flags=re.IGNORECASE,
            )
            if not preferred:
                continue
            entity_set = preferred.group("entity")
            field = preferred.group("field")
            preferred_end = preferred.end()
            discouraged_fields: list[str] = []
            for match in re.finditer(
                r"`(?P<entity>[A-Za-z_][A-Za-z0-9_]*)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)`",
                line[preferred_end:],
            ):
                if match.group("entity") != entity_set:
                    continue
                discouraged = match.group("field")
                if discouraged != field and discouraged not in discouraged_fields:
                    discouraged_fields.append(discouraged)
            if not discouraged_fields:
                continue
            key = (entity_set, field, tuple(sorted(discouraged_fields)))
            if key in seen:
                continue
            seen.add(key)
            requirements.append(
                {
                    "entity_set": entity_set,
                    "field": field,
                    "discouraged_fields": discouraged_fields,
                    "skill_line": line,
                    "match_score": score,
                }
            )
        return sorted(requirements, key=lambda item: int(item.get("match_score") or 0), reverse=True)

    @staticmethod
    def _skill_filter_literal(raw_literal: str) -> tuple[str, str]:
        literal = str(raw_literal or "").strip()
        if literal.lower() in {"true", "false"}:
            return literal.lower(), "boolean"
        return literal.strip("'\""), "string"

    @staticmethod
    def _normalise_filter_literal(value: Any) -> str:
        return str(value if value is not None else "").strip("'\"").lower()

    @staticmethod
    def _skill_line_select_only_fields(line: str, entity_set: str) -> list[str]:
        if "select only" not in line.lower() and "only select" not in line.lower():
            return []
        fields: list[str] = []
        for match in re.finditer(r"`(?:(?P<entity>[A-Za-z_][A-Za-z0-9_]*)\.)?(?P<field>[A-Za-z_][A-Za-z0-9_]*)", line):
            match_entity = match.group("entity") or ""
            field = match.group("field") or ""
            if not field:
                continue
            if match_entity and match_entity != entity_set:
                continue
            if field not in fields:
                fields.append(field)
        return fields

    @staticmethod
    def _matching_skill_select_only_requirements(
        request: AgentRequest,
        schema_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        request_text = f"{request.resolved_user_input or ''} {request.user_input or ''}".strip()
        if not request_text:
            return []
        by_entity: dict[str, dict[str, Any]] = {}
        for line in LlmApiSpecificPlanner._iter_skill_lines(schema_context):
            if "select only" not in line.lower() and "only select" not in line.lower():
                continue
            score = LlmApiSpecificPlanner._skill_line_match_score(line, request_text)
            if score <= 0:
                continue
            fields_by_entity: dict[str, list[str]] = {}
            for match in re.finditer(
                r"`(?:(?P<entity>[A-Za-z_][A-Za-z0-9_]*)\.)?(?P<field>[A-Za-z_][A-Za-z0-9_]*)",
                line,
            ):
                entity_set = match.group("entity") or ""
                field = match.group("field") or ""
                if not entity_set or not field:
                    continue
                fields = fields_by_entity.setdefault(entity_set, [])
                if field not in fields:
                    fields.append(field)
            for entity_set, fields in fields_by_entity.items():
                if not fields:
                    continue
                existing = by_entity.get(entity_set)
                if existing is not None:
                    existing_score = int(existing.get("match_score") or 0)
                    existing_fields = existing.get("fields") if isinstance(existing.get("fields"), list) else []
                    existing_line = str(existing.get("skill_line") or "")
                    existing_field_chars = sum(len(str(item)) for item in existing_fields)
                    field_chars = sum(len(str(item)) for item in fields)
                    if existing_score > score:
                        continue
                    if (
                        existing_score == score
                        and len(existing_fields) >= len(fields)
                        and existing_field_chars >= field_chars
                        and not existing_line.rstrip().endswith("...")
                    ):
                        continue
                by_entity[entity_set] = {
                    "entity_set": entity_set,
                    "fields": fields,
                    "source": "api_skill_select_only",
                    "skill_line": line,
                    "match_score": score,
                }
        return sorted(by_entity.values(), key=lambda item: int(item.get("match_score") or 0), reverse=True)

    @staticmethod
    def _matching_skill_result_transform_requirements(
        request: AgentRequest,
        schema_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        request_text = f"{request.resolved_user_input or ''} {request.user_input or ''}".strip()
        if not request_text:
            return []
        requirements: list[dict[str, Any]] = []
        seen: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
        for line in LlmApiSpecificPlanner._iter_skill_lines(schema_context):
            lowered = line.lower()
            if "result_transform" not in lowered or "aggregate" not in lowered:
                continue
            score = LlmApiSpecificPlanner._skill_line_match_score(line, request_text)
            if score <= 0:
                continue
            group_refs = LlmApiSpecificPlanner._extract_skill_field_refs_after_marker(line, "group_by")
            sum_refs = LlmApiSpecificPlanner._extract_skill_field_refs_after_marker(line, "sum_fields")
            if not group_refs or not sum_refs:
                continue
            entity_sets = {entity for entity, _ in [*group_refs, *sum_refs] if entity}
            if len(entity_sets) != 1:
                continue
            entity_set = next(iter(entity_sets))
            group_by = [field for entity, field in group_refs if entity == entity_set]
            sum_fields = [field for entity, field in sum_refs if entity == entity_set]
            if not group_by or not sum_fields:
                continue
            key = (entity_set, tuple(group_by), tuple(sum_fields))
            if key in seen:
                continue
            seen.add(key)
            requirements.append(
                {
                    "entity_set": entity_set,
                    "group_by": group_by,
                    "sum_fields": sum_fields,
                    "source": "api_skill_result_transform",
                    "skill_line": line,
                    "match_score": score,
                }
            )
        return sorted(requirements, key=lambda item: int(item.get("match_score") or 0), reverse=True)

    @staticmethod
    def _extract_skill_field_refs_after_marker(line: str, marker: str) -> list[tuple[str, str]]:
        pattern = re.compile(
            rf"{re.escape(marker)}\s*[:=]\s*(?P<body>.*?)(?:;\s*[A-Za-z_]+\s*[:=]|$)",
            flags=re.IGNORECASE,
        )
        match = pattern.search(line)
        if not match:
            return []
        body = match.group("body")
        refs: list[tuple[str, str]] = []
        for field_match in re.finditer(
            r"`(?P<entity>[A-Za-z_][A-Za-z0-9_]*)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)`",
            body,
        ):
            ref = (field_match.group("entity"), field_match.group("field"))
            if ref not in refs:
                refs.append(ref)
        return refs

    @staticmethod
    def _iter_skill_lines(schema_context: dict[str, Any]) -> list[str]:
        skills: list[dict[str, Any]] = []
        api_skill = schema_context.get("api_skill")
        if isinstance(api_skill, dict):
            skills.append(api_skill)
        skills.extend(item for item in schema_context.get("api_skills", []) if isinstance(item, dict))
        lines: list[str] = []
        for skill in skills:
            text = "\n".join(
                str(skill.get(key) or "")
                for key in ("summary", "content")
                if str(skill.get(key) or "").strip()
            )
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if line and not line.startswith("#"):
                    lines.append(line)
        return lines

    @staticmethod
    def _skill_line_matches_request(line: str, request_text: str) -> bool:
        return LlmApiSpecificPlanner._skill_line_match_score(line, request_text) > 0

    @staticmethod
    def _skill_line_match_score(line: str, request_text: str) -> int:
        normalized_request = LlmApiSpecificPlanner._normalize_match_text(request_text)
        normalized_line = LlmApiSpecificPlanner._normalize_match_text(line)
        score = 0
        if normalized_request and (normalized_request in normalized_line or normalized_line in normalized_request):
            score += min(len(normalized_request), len(normalized_line))
        for phrase in re.findall(r"[\u4e00-\u9fff]{4,}", line):
            if phrase in request_text:
                score += len(phrase) * len(phrase)
        stopwords = {
            "query",
            "show",
            "list",
            "with",
            "when",
            "user",
            "asks",
            "field",
            "fields",
            "filter",
            "items",
            "line",
            "lines",
            "records",
            "documents",
        }
        request_tokens = set(re.findall(r"[A-Za-z0-9]{4,}", request_text.lower())) - stopwords
        line_tokens = set(re.findall(r"[A-Za-z0-9]{4,}", line.lower())) - stopwords
        score += 5 * len(request_tokens.intersection(line_tokens))
        return score

    @staticmethod
    def _normalize_match_text(value: str) -> str:
        return "".join(ch for ch in str(value or "").lower() if ch.isalnum())

    @staticmethod
    def _schema_entity_has_filterable_field(schema_context: dict[str, Any], entity_set: str, field_name: str) -> bool:
        for entity in schema_context.get("entities", []):
            if not isinstance(entity, dict) or str(entity.get("entity_set") or "") != entity_set:
                continue
            for field in entity.get("fields", []):
                if not isinstance(field, dict) or str(field.get("field_name") or "") != field_name:
                    continue
                return field.get("filterable", True) is not False
        for field in schema_context.get("candidate_fields", []):
            if not isinstance(field, dict):
                continue
            if str(field.get("entity_set") or "") == entity_set and str(field.get("field_name") or "") == field_name:
                return field.get("filterable", True) is not False
        return False

    @staticmethod
    def _schema_entity_has_field(schema_context: dict[str, Any], entity_set: str, field_name: str) -> bool:
        for entity in schema_context.get("entities", []):
            if not isinstance(entity, dict) or str(entity.get("entity_set") or "") != entity_set:
                continue
            for field in entity.get("fields", []):
                if isinstance(field, dict) and str(field.get("field_name") or "") == field_name:
                    return True
        for field in schema_context.get("candidate_fields", []):
            if not isinstance(field, dict):
                continue
            if str(field.get("entity_set") or "") == entity_set and str(field.get("field_name") or "") == field_name:
                return True
        return False

    @staticmethod
    def _select_prompt_entities(schema_context: dict[str, Any]) -> list[dict[str, Any]]:
        entities = [
            entity
            for entity in schema_context.get("entities", [])
            if isinstance(entity, dict) and str(entity.get("entity_set") or "")
        ]
        if not entities:
            return []
        service_names = [
            str(item).strip()
            for item in schema_context.get("service_names", [schema_context.get("service_name", "")])
            if str(item).strip()
        ]
        if len(service_names) <= 1:
            return entities[:16]

        selected: list[dict[str, Any]] = []
        emitted: set[tuple[str, str]] = set()
        per_service = max(4, 16 // len(service_names))
        for service_name in service_names:
            count = 0
            for entity in entities:
                key = (str(entity.get("service_name") or ""), str(entity.get("entity_set") or ""))
                if key[0] != service_name or key in emitted:
                    continue
                selected.append(entity)
                emitted.add(key)
                count += 1
                if count >= per_service:
                    break
        for entity in entities:
            if len(selected) >= 20:
                break
            key = (str(entity.get("service_name") or ""), str(entity.get("entity_set") or ""))
            if key not in emitted:
                selected.append(entity)
                emitted.add(key)
        return selected

    @staticmethod
    def _compact_function_import(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "service_name": item.get("service_name", ""),
            "name": item.get("name", "") or item.get("entity_set", ""),
            "entity_set": item.get("entity_set", ""),
            "http_method": item.get("http_method", ""),
            "parameters": [
                {
                    "name": parameter.get("name", ""),
                    "data_type": parameter.get("data_type", ""),
                    "value_type": parameter.get("value_type", ""),
                    "required": parameter.get("required", True),
                    "label": parameter.get("label", ""),
                }
                for parameter in item.get("parameters", [])[:12]
                if isinstance(parameter, dict)
            ],
            "return_type": item.get("return_type", ""),
            "return_fields": [
                {
                    "field_name": field.get("field_name", ""),
                    "data_type": field.get("data_type", ""),
                    "value_type": field.get("value_type", ""),
                    "label": field.get("label", ""),
                }
                for field in item.get("return_fields", [])[:16]
                if isinstance(field, dict)
            ],
        }

    @staticmethod
    def _should_include_function_imports(query: str, schema_context: dict[str, Any]) -> bool:
        if not schema_context.get("function_imports"):
            return False
        service_names = " ".join(str(item) for item in schema_context.get("service_names", []))
        text = f"{query} {service_names}".lower()
        markers = (
            "function import",
            "availability",
            "available",
            "avail",
            "stock availability",
            "can be delivered",
            "can deliver",
            "\u6709\u8d27",
            "\u53ef\u7528",
            "\u53ef\u4ea4\u4ed8",
            "\u5e93\u5b58\u53ef\u7528",
        )
        if any(marker in text for marker in markers):
            return True
        entities = schema_context.get("entities", [])
        return bool(entities) and all(
            isinstance(entity, dict) and entity.get("kind") == "function_import"
            for entity in entities
        )

    @staticmethod
    def _truncate_prompt_value(value: str, max_chars: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def _selected_service(route_decision: ApiRouteDecision) -> str:
        return route_decision.selected_apis[0].service_name if route_decision.selected_apis else ""

    def _load_schema_snapshot(self, service_name: str, schema_context: dict[str, Any]) -> LocalIndexSnapshot:
        service_names = [
            str(item).strip()
            for item in schema_context.get("service_names", [])
            if str(item).strip()
        ]
        if not service_names:
            service_names = [service_name]
        service_names = list(dict.fromkeys(service_names))
        if len(service_names) == 1:
            return self.loader.load(service_names[0])

        snapshots = [self.loader.load(name) for name in service_names]
        root_dir = snapshots[0].root_dir.parent if snapshots else Path("data/index")

        def merge(attr: str) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            for snapshot in snapshots:
                for item in getattr(snapshot, attr):
                    if isinstance(item, dict):
                        rows.append({**item, "service_name": item.get("service_name") or snapshot.service_name})
            return rows

        return LocalIndexSnapshot(
            service_name=service_name or service_names[0],
            root_dir=root_dir,
            services=merge("services"),
            entities=merge("entities"),
            fields=merge("fields"),
            relations=merge("relations"),
            entity_graph=merge("entity_graph"),
            lookup_paths=merge("lookup_paths"),
            business_terms=merge("business_terms"),
            vector_documents=[],
            doc_chunks=[],
        )

    @staticmethod
    def _requires_purchase_order_history_clarification(request: AgentRequest, service_name: str) -> bool:
        if service_name != "API_PURCHASEORDER_PROCESS_SRV":
            return False
        text = f"{request.resolved_user_input or ''} {request.user_input or ''}".lower()
        if not any(term in text for term in ("\u91c7\u8d2d\u8ba2\u5355", "purchase order", "po ")):
            return False
        if not any(term in text for term in ("\u5386\u53f2\u8bb0\u5f55", "\u5386\u53f2", "history")):
            return False
        disambiguating_terms = (
            "\u5b9a\u4ef7",  # 定价
            "\u4ef7\u683c\u6761\u4ef6",  # 价格条件
            "\u6536\u8d27",  # 收货
            "\u53d1\u7968",  # 发票
            "\u7269\u6599\u51ed\u8bc1",  # 物料凭证
            "\u53d8\u66f4",  # 变更
            "pricing",
            "price condition",
            "goods receipt",
            "invoice",
            "material document",
            "change",
        )
        return not any(term in text for term in disambiguating_terms)

    @staticmethod
    def _purchase_order_history_clarification_plan(service_name: str) -> QueryPlan:
        question = (
            "\u8bf7\u786e\u8ba4\u4f60\u8981\u67e5\u7684\u201c\u91c7\u8d2d\u8ba2\u5355\u5386\u53f2\u8bb0\u5f55\u201d\u662f\u54ea\u4e00\u7c7b\uff1a"
            "\u91c7\u8d2d\u8ba2\u5355\u7ed3\u6784\u660e\u7ec6\u3001\u5b9a\u4ef7\u6761\u4ef6\u3001\u6536\u8d27\u5386\u53f2\u3001"
            "\u53d1\u7968\u5386\u53f2\u3001\u7269\u6599\u51ed\u8bc1\u8fd8\u662f\u53d8\u66f4\u5386\u53f2\uff1f"
        )
        return QueryPlan(
            service_name=service_name,
            entity_set="",
            plan_kind="clarification",
            needs_clarification=True,
            clarification_question=question,
            clarification_options=[
                "\u91c7\u8d2d\u8ba2\u5355\u7ed3\u6784\u660e\u7ec6",
                "\u5b9a\u4ef7\u6761\u4ef6",
                "\u6536\u8d27\u5386\u53f2",
                "\u53d1\u7968\u5386\u53f2",
                "\u7269\u6599\u51ed\u8bc1",
                "\u53d8\u66f4\u5386\u53f2",
            ],
            response_directive=question,
            rationale="Purchase order history is ambiguous for API_PURCHASEORDER_PROCESS_SRV.",
            planner_diagnostics={
                "planner_type": "llm_api_specific_planner",
                "clarification_reason": "ambiguous_purchase_order_history",
            },
        )

    def _unavailable_plan_for_service(self, service_name: str, reason: str) -> QueryPlan:
        plan = self._unavailable_plan(reason)
        return replace(plan, service_name=service_name or plan.service_name)

    def _invalid_plan_for_service(
        self,
        service_name: str,
        reason: str,
        schema_context: dict[str, Any],
        parsed: dict[str, Any] | None = None,
    ) -> QueryPlan:
        plan = self._invalid_plan(reason, schema_context, parsed)
        return replace(plan, service_name=service_name or plan.service_name)
