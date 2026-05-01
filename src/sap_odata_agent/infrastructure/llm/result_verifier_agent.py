from __future__ import annotations

import json
from typing import Any

from sap_odata_agent.domain.models import AgentRequest, QueryPlan
from sap_odata_agent.infrastructure.llm.planner import AnthropicCompatibleMessagesClient, LlmStructuredIntentPlanner
from sap_odata_agent.infrastructure.llm.prompts import GLOBAL_SAP_ODATA_PROMPT


class LlmResultVerifierAgent:
    """LLM-first verifier that checks whether executed data supports the answer."""

    def __init__(
        self,
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
    ) -> None:
        self.llm_client = llm_client
        self.enabled = enabled

    def verify(
        self,
        request: AgentRequest,
        plan: QueryPlan,
        data: dict[str, Any] | None,
        schema_research: dict[str, Any] | None = None,
        schema_context_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fallback = {"passed": True, "issues": [], "repair_hints": {}, "source": "result_verifier_unavailable"}
        static_result = self._skill_grounded_static_checks(
            request,
            plan,
            data or {},
            schema_context_summary or {},
        )
        if static_result is not None:
            return static_result
        if not self.enabled or self.llm_client is None or not data:
            return fallback
        try:
            raw = self.llm_client.complete_json(
                self._system_prompt(),
                self._user_prompt(request, plan, data, schema_research or {}, schema_context_summary or {}),
                max_tokens=1100,
            )
            parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
        except Exception as exc:
            return {
                **fallback,
                "source": "result_verifier_failed",
                "error": str(exc),
            }
        return self._materialize(parsed, schema_context_summary or {})

    @staticmethod
    def _system_prompt() -> str:
        return (
            f"{GLOBAL_SAP_ODATA_PROMPT}\n\n"
            "You are a result verifier agent. Check whether the executed SAP data and plan actually support "
            "the user's business answer. You do not present the answer. Return JSON only."
        )

    @staticmethod
    def _user_prompt(
        request: AgentRequest,
        plan: QueryPlan,
        data: dict[str, Any],
        schema_research: dict[str, Any],
        schema_context_summary: dict[str, Any],
    ) -> str:
        example = {
            "passed": False,
            "issues": [
                {
                    "code": "unsupported_business_conclusion",
                    "message": "The returned field proves a different business concept than the user's question.",
                    "blocking": True,
                }
            ],
            "repair_hints": {
                "reason": "What the next plan should change.",
                "preferred_filters": [
                    {"entity_set": "EntitySet", "field": "FieldName", "operator": "eq", "value": "literal"}
                ],
            },
        }
        payload = {
            "user_input": request.resolved_user_input or request.user_input,
            "plan": {
                "plan_kind": plan.plan_kind,
                "entity_set": plan.entity_set,
                "select_fields": plan.select_fields,
                "response_summary_fields": plan.response_summary_fields,
                "filters": [{"field": item.field, "operator": item.operator, "value": item.value} for item in plan.filters],
                "function_parameters": [
                    {"name": item.name, "value": item.value, "value_type": item.value_type}
                    for item in getattr(plan, "function_parameters", [])
                ],
                "steps": [
                    {
                        "step_id": step.step_id,
                        "entity_set": step.entity_set,
                        "select_fields": step.select_fields,
                        "filters": [{"field": item.field, "operator": item.operator, "value": item.value} for item in step.filters],
                        "filter_from_previous": [
                            {"field": item.field, "source_step_id": item.source_step_id, "source_field": item.source_field}
                            for item in step.filter_from_previous
                        ],
                    }
                    for step in plan.steps
                ],
            },
            "schema_research": schema_research,
            "schema_context_summary": {
                "service_name": schema_context_summary.get("service_name", ""),
                "api_skill": schema_context_summary.get("api_skill", {}),
                "top_entities": schema_context_summary.get("top_entities", []),
                "available_fields": schema_context_summary.get("available_fields", [])[:120],
            },
            "data_summary": {
                "result_count": data.get("result_count"),
                "results": data.get("results", [])[:20] if isinstance(data.get("results"), list) else [],
                "lookup_context": data.get("lookup_context"),
                "execution_trace": data.get("execution_trace"),
                "step_results": LlmResultVerifierAgent._summarize_step_results(data.get("step_results")),
            },
        }
        return (
            f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n\n"
            "Verification rules:\n"
            "1. Pass only if the returned fields and filters can support the user's business question.\n"
            "2. Do not infer status from fields whose meaning only says expected/required/configured.\n"
            "3. For list questions, verify the result set is filtered by the requested business condition, not merely by a related control flag.\n"
            "4. If schema_research flagged semantic risks, verify the final plan addressed them.\n"
            "5. Use schema_context_summary.api_skill as API-specific guidance for whether a field combination supports the user's business conclusion.\n"
            "6. If api_skill defines a field combination for the user's intent and the executed plan uses that combination, do not reject it unless returned data contradicts it.\n"
            "7. If the result is semantically unreliable, set passed=false and give repair_hints.\n"
            "8. Do not block for presentation wording; only block data/plan support issues.\n"
            "9. repair_hints must only recommend fields listed in schema_context_summary.available_fields; do not invent field names.\n"
            "10. For unreceived/undelivered/open receipt questions, prefer actual completion/status or received/open quantity fields over expected/required/configuration flags. If the user explicitly asks for orders that need goods receipt but are not yet received, the API skill may define expected=true plus completion=false as the correct combination.\n\n"
            "11. A successful SAP response with result_count=0 can be a correct answer for a list query. Do not reject only because there are no rows or because a repair might find related rows. Block an empty result only when the plan clearly used the wrong entity, omitted a required user filter, or omitted required answer fields.\n"
            "12. Do not require enrichment identifiers that the user did not explicitly ask for. For address communication list questions, address-level keys plus the requested email, phone, or fax fields are sufficient unless the user explicitly asks to include business partner details.\n\n"
            "13. A business object name in the question can identify the domain or entity type. Do not treat words like business partner, supplier, customer, material, or purchase order as mandatory output fields unless the user explicitly asks for the ID/number/code or those fields are required to distinguish returned rows.\n\n"
            "14. When api_skill says a similarly named field is not sufficient for the user's business level, block a successful response that uses that insufficient field as negative evidence and provide repair_hints for the more specific entity/field combination.\n\n"
            "15. Do not accept pricing elements, notes, account assignments, or other detail child entities as the main answer for a document history request unless the user explicitly asked for that detail type.\n\n"
            "16. For bare field-list wording such as \"with/include/show/display field A and field B\", verify that the fields are selected and returned; do not require filters for those fields unless the user supplied an explicit restriction, comparison, literal value, true/false requirement, nonzero/open/closed condition, or other business condition.\n\n"
            "Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _skill_grounded_static_checks(
        request: AgentRequest,
        plan: QueryPlan,
        data: dict[str, Any],
        schema_context_summary: dict[str, Any],
    ) -> dict[str, Any] | None:
        po_history_result = LlmResultVerifierAgent._purchase_order_history_static_check(request, plan, data)
        if po_history_result is not None:
            return po_history_result
        field_list_result = LlmResultVerifierAgent._field_list_output_static_check(request, plan, data)
        if field_list_result is not None:
            return field_list_result
        if not LlmResultVerifierAgent._looks_like_product_tax_classification_request(request):
            return None
        if plan.service_name != "API_PRODUCT_SRV" or plan.entity_set != "A_ProductSales":
            return None
        selected_fields = set(plan.select_fields or []) | set(plan.response_summary_fields or [])
        if "TaxClassification" not in selected_fields:
            return None
        skill_text = json.dumps(schema_context_summary.get("api_skill", {}), ensure_ascii=False)
        if "A_ProductSalesTax" not in skill_text or "A_ProductSales.TaxClassification" not in skill_text:
            return None
        if not LlmResultVerifierAgent._has_available_fields(
            schema_context_summary,
            "A_ProductSalesTax",
            {"Product", "Country", "TaxCategory", "TaxClassification"},
        ):
            return None
        records = data.get("results") if isinstance(data.get("results"), list) else []
        if not records and isinstance(data.get("result"), dict):
            records = [data["result"]]
        if not records:
            return None
        if any(str(record.get("TaxClassification") or "").strip() for record in records if isinstance(record, dict)):
            return None
        product_value = LlmResultVerifierAgent._plan_filter_value(plan, "Product")
        if not product_value:
            for record in records:
                if isinstance(record, dict) and record.get("Product"):
                    product_value = str(record.get("Product"))
                    break
        preferred_filters = []
        if product_value:
            preferred_filters.append(
                {
                    "entity_set": "A_ProductSalesTax",
                    "field": "Product",
                    "operator": "eq",
                    "value": product_value,
                    "value_type": "string",
                }
            )
        return {
            "passed": False,
            "issues": [
                {
                    "code": "wrong_business_level_for_tax_classification",
                    "message": (
                        "The plan queried blank A_ProductSales.TaxClassification, but the API skill identifies "
                        "A_ProductSalesTax as the specific sales tax classification entity. A blank value on the "
                        "less specific field does not prove that product tax classification is not maintained."
                    ),
                    "blocking": True,
                }
            ],
            "repair_hints": {
                "reason": "Use the more specific product sales tax entity for material tax classification details.",
                "preferred_entity_set": "A_ProductSalesTax",
                "preferred_select_fields": ["Product", "Country", "TaxCategory", "TaxClassification"],
                "preferred_filters": preferred_filters,
                "presentation_kind": "table",
            },
            "source": "skill_grounded_result_verifier",
        }

    @staticmethod
    def _purchase_order_history_static_check(
        request: AgentRequest,
        plan: QueryPlan,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not LlmResultVerifierAgent._looks_like_purchase_order_history_request(request):
            return None
        if plan.service_name != "API_PURCHASEORDER_PROCESS_SRV":
            return None
        if LlmResultVerifierAgent._explicitly_asks_for_pricing(request):
            return None
        step_results = data.get("step_results") if isinstance(data.get("step_results"), dict) else {}
        final_entity = str(data.get("final_step_entity_set") or "")
        primary_entity = str(data.get("primary_entity_set") or plan.entity_set or "")
        if not final_entity:
            execution_trace = data.get("execution_trace") if isinstance(data.get("execution_trace"), list) else []
            if execution_trace and isinstance(execution_trace[-1], dict):
                final_entity = str(execution_trace[-1].get("entity_set") or "")
        records = data.get("results") if isinstance(data.get("results"), list) else []
        pricing_only = (
            primary_entity == "A_PurOrdPricingElement"
            or (final_entity == "A_PurOrdPricingElement" and not step_results)
            or LlmResultVerifierAgent._records_look_like_pricing_elements(records)
        )
        if not pricing_only:
            return None
        return {
            "passed": False,
            "issues": [
                {
                    "code": "wrong_business_level_for_purchase_order_history",
                    "message": (
                        "The user asked for purchase order history, but the executed result is pricing "
                        "condition data from A_PurOrdPricingElement. Pricing elements are not purchase order "
                        "history unless the user explicitly asks for pricing."
                    ),
                    "blocking": True,
                }
            ],
            "repair_hints": {
                "reason": "Do not answer purchase order history with pricing elements.",
                "preferred_plan_kind": "clarification",
                "clarification_question": (
                    "Please clarify whether you want purchase order structure/details, pricing conditions, "
                    "goods receipt history, invoice receipt history, material documents, or change history."
                ),
                "rejected_entity_set": "A_PurOrdPricingElement",
            },
            "source": "skill_grounded_result_verifier",
        }

    @staticmethod
    def _field_list_output_static_check(
        request: AgentRequest,
        plan: QueryPlan,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        text = f" {request.user_input or request.resolved_user_input or ''} ".lower()
        field_list_markers = (
            " with ",
            " include ",
            " includes ",
            " including ",
            " display ",
            " show ",
            " list ",
        )
        if not any(marker in text for marker in field_list_markers):
            return None

        explicit_filter_markers = (
            " only ",
            " where ",
            " equal ",
            " equals ",
            " greater than ",
            " less than ",
            " at least ",
            " at most ",
            " nonzero ",
            " non-zero ",
            " true ",
            " false ",
            " open ",
            " closed ",
            " completed ",
            " incomplete ",
            " unreceived ",
            " undelivered ",
            " pending ",
            " overdue ",
            " not yet ",
            "\u4ec5",
            "\u53ea",
            "\u5927\u4e8e",
            "\u5c0f\u4e8e",
            "\u7b49\u4e8e",
            "\u4e3a",
            "\u662f",
            "\u5426",
            "\u672a",
            "\u5df2",
        )
        if any(marker in text for marker in explicit_filter_markers):
            return None
        if plan.filters or any(step.filters for step in plan.steps or []):
            return None

        constraints = request.constraints
        if constraints is not None and (
            constraints.filter_concepts or constraints.filter_values or constraints.boolean_intent
        ):
            return None
        if not plan.select_fields and not any(step.select_fields for step in plan.steps or []):
            return None
        if data.get("result_count") is None and "results" not in data:
            return None
        return {
            "passed": True,
            "issues": [],
            "repair_hints": {},
            "source": "field_list_static_result_verifier",
        }

    @staticmethod
    def _looks_like_product_tax_classification_request(request: AgentRequest) -> bool:
        text = f"{request.resolved_user_input or ''} {request.user_input or ''}".lower()
        return ("税分类" in text or "税收分类" in text or "tax classification" in text) and (
            "物料" in text or "产品" in text or "material" in text or "product" in text
        )

    @staticmethod
    def _looks_like_purchase_order_history_request(request: AgentRequest) -> bool:
        text = f"{request.resolved_user_input or ''} {request.user_input or ''}".lower()
        purchase_order_terms = (
            "\u91c7\u8d2d\u8ba2\u5355",  # 采购订单
            "purchase order",
            "po ",
        )
        history_terms = (
            "\u5386\u53f2\u8bb0\u5f55",  # 历史记录
            "\u5386\u53f2",  # 历史
            "history",
        )
        return any(term in text for term in purchase_order_terms) and any(term in text for term in history_terms)

    @staticmethod
    def _explicitly_asks_for_pricing(request: AgentRequest) -> bool:
        text = f"{request.resolved_user_input or ''} {request.user_input or ''}".lower()
        pricing_terms = (
            "\u5b9a\u4ef7",  # 定价
            "\u4ef7\u683c\u6761\u4ef6",  # 价格条件
            "pricing",
            "price condition",
            "condition type",
        )
        return any(term in text for term in pricing_terms)

    @staticmethod
    def _records_look_like_pricing_elements(records: Any) -> bool:
        if not isinstance(records, list) or not records:
            return False
        pricing_fields = {
            "ConditionType",
            "ConditionRateValue",
            "ConditionCurrency",
            "PricingProcedureStep",
            "PricingProcedureCounter",
            "PricingDocument",
        }
        dict_records = [record for record in records if isinstance(record, dict)]
        if not dict_records:
            return False
        return all(pricing_fields.intersection(record.keys()) for record in dict_records)

    @staticmethod
    def _summarize_step_results(step_results: Any) -> dict[str, Any]:
        if not isinstance(step_results, dict):
            return {}
        summary: dict[str, Any] = {}
        for step_id, value in step_results.items():
            if not isinstance(value, dict):
                continue
            summary[str(step_id)] = {
                "entity_set": value.get("entity_set"),
                "result_count": value.get("result_count"),
                "displayed_count": value.get("displayed_count"),
                "sample_results": value.get("results", [])[:3] if isinstance(value.get("results"), list) else [],
            }
        return summary

    @staticmethod
    def _has_available_fields(
        schema_context_summary: dict[str, Any],
        entity_set: str,
        required_fields: set[str],
    ) -> bool:
        available = {
            str(item.get("field_name", ""))
            for item in schema_context_summary.get("available_fields", [])
            if isinstance(item, dict) and str(item.get("entity_set", "")) == entity_set
        }
        return required_fields <= available

    @staticmethod
    def _plan_filter_value(plan: QueryPlan, field_name: str) -> str:
        for condition in plan.filters or []:
            if condition.field == field_name and condition.value not in (None, ""):
                return str(condition.value)
        for step in plan.steps or []:
            for condition in step.filters or []:
                if condition.field == field_name and condition.value not in (None, ""):
                    return str(condition.value)
        return ""

    @staticmethod
    def _materialize(parsed: dict[str, Any], schema_context_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        issues = []
        for item in parsed.get("issues", []):
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "") or "").strip()
            message = str(item.get("message", "") or "").strip()
            if not code or not message:
                continue
            issues.append(
                {
                    "code": code,
                    "message": message,
                    "blocking": bool(item.get("blocking", True)),
                }
            )
        passed = bool(parsed.get("passed", False))
        if any(issue.get("blocking") for issue in issues):
            passed = False
        repair_hints = parsed.get("repair_hints", {}) if isinstance(parsed.get("repair_hints"), dict) else {}
        repair_hints = LlmResultVerifierAgent._filter_repair_hints(repair_hints, schema_context_summary or {})
        return {
            "passed": passed,
            "issues": issues,
            "repair_hints": repair_hints,
            "source": "llm_result_verifier_agent",
        }

    @staticmethod
    def _filter_repair_hints(repair_hints: dict[str, Any], schema_context_summary: dict[str, Any]) -> dict[str, Any]:
        available_fields = schema_context_summary.get("available_fields", [])
        if not available_fields:
            return repair_hints
        available_keys = {
            (str(item.get("entity_set", "")), str(item.get("field_name", "")))
            for item in available_fields
            if isinstance(item, dict)
        }
        filtered_filters = []
        for item in repair_hints.get("preferred_filters", []):
            if not isinstance(item, dict):
                continue
            key = (str(item.get("entity_set", "")), str(item.get("field", "")))
            if key in available_keys:
                filtered_filters.append(item)
        return {
            **repair_hints,
            "preferred_filters": filtered_filters,
        }
