from __future__ import annotations

import json
from datetime import date
from dataclasses import replace
from pathlib import Path
from typing import Any

from sap_odata_agent.domain.models import AgentRequest, ApiRouteDecision, QueryPlan
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
            "12. Treat document history requests as ambiguous unless schema_context exposes a true history, movement, receipt, invoice, or change-history entity. Do not answer a history request by returning only pricing, notes, account assignments, or other detail child entities.\n\n"
            "13. Treat bare \"with/include/show/display\" field-list wording as requested output fields, not filters. Add filters only for explicit restrictions, comparisons, literal values, true/false requirements, nonzero/open/closed conditions, or schema-verified business conditions.\n\n"
            "14. If schema_context.service_names contains multiple services, every multi_step step must include service_name. Use cross-service join_hints or shared key fields to bridge between services, and only use entity sets and fields from that step's service.\n\n"
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
                "summary": LlmApiSpecificPlanner._truncate_prompt_value(str(skill.get("summary") or ""), 2200),
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
