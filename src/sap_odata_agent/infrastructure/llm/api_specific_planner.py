from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from sap_odata_agent.domain.models import AgentRequest, ApiRouteDecision, QueryPlan
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
        if not self.enabled or self.llm_client is None:
            return self._unavailable_plan_for_service(service_name, "llm_unavailable")
        try:
            snapshot = self.loader.load(service_name)
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
        return replace(
            materialized,
            service_name=service_name,
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
            "plan_kind": "direct | multi_step | clarification | no_feasible_plan",
            "service_name": schema_context.get("service_name", ""),
            "entity_set": "",
            "http_method": "GET",
            "select_fields": [],
            "filters": [{"field": "", "operator": "eq", "value": "", "value_type": "string | boolean | number | date"}],
            "steps": [
                {
                    "step_id": "step_1",
                    "entity_set": "SourceEntitySet",
                    "select_fields": ["JoinField", "FilterField"],
                    "filters": [{"field": "FilterField", "operator": "eq", "value": "literal", "value_type": "string"}],
                    "filter_from_previous": [],
                    "top": 50,
                },
                {
                    "step_id": "step_2",
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
            "response_directive": "",
            "rationale": "",
        }
        payload = {
            "original_user_input": request.user_input,
            "resolved_user_input": route_decision.resolved_user_input or request.resolved_user_input or request.user_input,
            "route_decision": {
                "selected_apis": [
                    {"service_name": item.service_name, "confidence": item.confidence, "reason": item.reason}
                    for item in route_decision.selected_apis
                ],
                "intent_summary": route_decision.intent_summary,
                "business_domain": route_decision.business_domain,
                "business_object": route_decision.business_object,
            },
            "schema_context": schema_context,
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
            "Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _selected_service(route_decision: ApiRouteDecision) -> str:
        return route_decision.selected_apis[0].service_name if route_decision.selected_apis else ""

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
