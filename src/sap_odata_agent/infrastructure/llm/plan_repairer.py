from __future__ import annotations

import json
from dataclasses import asdict, replace
from typing import Any

from sap_odata_agent.domain.models import AgentRequest, ApiRouteDecision, ExecutionAttempt, QueryPlan
from sap_odata_agent.infrastructure.llm.api_specific_planner import LlmApiSpecificPlanner
from sap_odata_agent.infrastructure.llm.planner import AnthropicCompatibleMessagesClient, LlmStructuredIntentPlanner
from sap_odata_agent.infrastructure.llm.prompts import GLOBAL_SAP_ODATA_PROMPT, REPAIR_TASK_PROMPT


class LlmPlanRepairer(LlmApiSpecificPlanner):
    def __init__(
        self,
        index_root: str = "data/index",
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(index_root=index_root, llm_client=llm_client, enabled=enabled)

    def repair(
        self,
        request: AgentRequest,
        route_decision: ApiRouteDecision,
        schema_context: dict[str, Any],
        previous_plan: QueryPlan,
        attempt_number: int,
        max_attempts: int,
        failure_context: dict[str, Any],
    ) -> QueryPlan:
        service_name = str(schema_context.get("service_name") or previous_plan.service_name)
        if not self.enabled or self.llm_client is None:
            return self._unavailable_plan_for_service(service_name, "repair_llm_unavailable")
        try:
            snapshot = self.loader.load(service_name)
        except FileNotFoundError:
            return self._unavailable_plan_for_service(service_name, "index_unavailable")
        try:
            raw = self.llm_client.complete_json(
                self._repair_system_prompt(),
                self._repair_user_prompt(
                    request,
                    route_decision,
                    schema_context,
                    previous_plan,
                    attempt_number,
                    max_attempts,
                    failure_context,
                ),
                max_tokens=2600,
            )
            parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
        except Exception as exc:
            return self._invalid_plan_for_service(service_name, f"repair_llm_error:{exc}", schema_context)

        if str(parsed.get("plan_kind", "")).lower() == "reroute_required":
            return self._invalid_plan_for_service(service_name, "repair_requested_reroute", schema_context, parsed)

        materialized = self._materialize_plan(parsed, snapshot, schema_context)
        if materialized is None:
            return self._invalid_plan_for_service(service_name, "repair_plan_not_materializable", schema_context, parsed)
        return replace(
            materialized,
            service_name=service_name,
            rationale=str(parsed.get("repair_reason") or materialized.rationale),
            planner_diagnostics={
                **(materialized.planner_diagnostics or {}),
                "planner_type": "llm_plan_repairer",
                "repair_attempt": attempt_number,
                "repair_reason": parsed.get("repair_reason", ""),
                "changed_from_previous": parsed.get("changed_from_previous", []),
                "previous_plan_snapshot": LlmStructuredIntentPlanner._plan_to_dict(previous_plan),
            },
        )

    @staticmethod
    def _repair_system_prompt() -> str:
        return f"{GLOBAL_SAP_ODATA_PROMPT}\n\n{REPAIR_TASK_PROMPT}"

    @staticmethod
    def _repair_user_prompt(
        request: AgentRequest,
        route_decision: ApiRouteDecision,
        schema_context: dict[str, Any],
        previous_plan: QueryPlan,
        attempt_number: int,
        max_attempts: int,
        failure_context: dict[str, Any],
    ) -> str:
        example = {
            "plan_kind": "direct | multi_step | no_feasible_plan | reroute_required",
            "repair_reason": "",
            "changed_from_previous": [],
            "service_name": schema_context.get("service_name", previous_plan.service_name),
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
            "presentation": {"kind": "text | table", "reason": ""},
            "rationale": "",
        }
        payload = {
            "original_user_input": request.user_input,
            "resolved_user_input": route_decision.resolved_user_input or request.resolved_user_input or request.user_input,
            "selected_service": schema_context.get("service_name", previous_plan.service_name),
            "previous_plan": LlmStructuredIntentPlanner._plan_to_dict(previous_plan),
            "failure_context": failure_context,
            "schema_context": schema_context,
            "attempt_number": attempt_number,
            "max_attempts": max_attempts,
        }
        return (
            f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n\n"
            "Repair rules:\n"
            "1. If failure_context reports step_missing_filter_or_binding, add explicit filter_from_previous to each unbounded downstream step.\n"
            "2. Use filter_from_previous objects exactly as {\"field\": target_field_on_current_step, \"source_step_id\": previous_step_id, \"source_field\": field_selected_by_previous_step}.\n"
            "3. Select every source_field in its source step and every binding field in its target step.\n"
            "4. Set filter.value_type from the schema field data_type; use boolean for Edm.Boolean filters.\n"
            "5. Use schema_context.schema_research when present as the primary business-semantic analysis.\n"
            "6. Distinguish requirement/expected flags from completion/open status fields; do not treat similarly named fields as equivalent.\n"
            "7. Do not keep top-level filters that belong to a different entity; put each filter on the step whose entity owns that field.\n\n"
            "8. If failure_context.semantic_repair_required is present, treat its blocking_findings and repair_hints as mandatory repair requirements.\n"
            "9. Do not repeat a plan rejected by result_verification; choose fields, filters, or steps that prove the verifier's business condition.\n"
            "10. For unreceived, undelivered, pending receipt, open goods receipt, or not fully received questions, prefer actual completion/status or received/open quantity fields over expected/required/configuration flags.\n"
            "11. For API_PURCHASEORDER_PROCESS_SRV, if A_PurchaseOrderItem.IsCompletelyDelivered is available, prefer IsCompletelyDelivered eq false over GoodsReceiptIsExpected eq true for not-complete delivery/receipt semantics.\n"
            "12. If failure_context reports step_binding_target_not_in_entity, do not reuse that invalid target field. Insert an intermediate bridge entity that contains both the previous join field and the final target key, then bind from that bridge to the final entity.\n"
            "13. For example, do not bind a previous BusinessPartner value directly onto an entity that only has Supplier or Customer; first read the entity that exposes BusinessPartner plus the final role key, then bind the role key to the final entity.\n\n"
            "Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )


def execution_attempt_to_debug(attempt: ExecutionAttempt | None) -> dict[str, Any]:
    if attempt is None:
        return {}
    return {
        "attempt_number": attempt.attempt_number,
        "step_id": attempt.step_id,
        "url": attempt.request.url,
        "status_code": attempt.status_code,
        "success": attempt.success,
        "error_message": attempt.error_message,
        "response_preview": attempt.response_preview,
        "extracted_values": attempt.extracted_values,
    }


def dataclass_list_to_dicts(items: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        try:
            rows.append(asdict(item))
        except TypeError:
            rows.append(dict(item) if isinstance(item, dict) else {"value": str(item)})
    return rows
