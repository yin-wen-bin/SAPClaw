from __future__ import annotations

import json
from typing import Any

from sap_odata_agent.domain.models import AgentRequest, ApiRouteDecision
from sap_odata_agent.infrastructure.llm.planner import AnthropicCompatibleMessagesClient, LlmStructuredIntentPlanner
from sap_odata_agent.infrastructure.llm.prompts import GLOBAL_SAP_ODATA_PROMPT, METADATA_MATCHING_TASK_PROMPT


class LlmSchemaResearchAgent:
    """LLM-first schema researcher for business-semantic field selection.

    This agent does not execute or compile plans. It produces research notes that
    the planner, critic, and repairer can use when deciding whether a field's
    business meaning fits the user's request.
    """

    def __init__(
        self,
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
    ) -> None:
        self.llm_client = llm_client
        self.enabled = enabled

    def research(
        self,
        request: AgentRequest,
        route_decision: ApiRouteDecision,
        schema_context: dict[str, Any],
        feedback_memories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        fallback = self._fallback_research(request, route_decision)
        if not self.enabled or self.llm_client is None:
            return fallback
        try:
            raw = self.llm_client.complete_json(
                self._system_prompt(),
                self._user_prompt(request, route_decision, schema_context, feedback_memories or []),
                max_tokens=1800,
            )
            parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
        except Exception as exc:
            return {
                **fallback,
                "available": False,
                "error": f"schema_research_failed:{exc}",
            }
        return self._materialize(parsed, schema_context, fallback)

    @staticmethod
    def summarize(research: dict[str, Any]) -> dict[str, Any]:
        return {
            "available": bool(research.get("available")),
            "business_intent": research.get("business_intent", ""),
            "recommended_filters": research.get("recommended_filters", [])[:8],
            "semantic_risks": research.get("semantic_risks", [])[:8],
        }

    @staticmethod
    def _system_prompt() -> str:
        return (
            f"{GLOBAL_SAP_ODATA_PROMPT}\n\n{METADATA_MATCHING_TASK_PROMPT}\n\n"
            "You are a schema research agent. Work like an SAP functional consultant: inspect the provided "
            "schema labels, descriptions, entity levels, relations, and feedback memories before planning. "
            "Your job is to decide what fields can and cannot prove the user's business intent. "
            "Do not generate an OData plan. Return JSON only."
        )

    @staticmethod
    def _user_prompt(
        request: AgentRequest,
        route_decision: ApiRouteDecision,
        schema_context: dict[str, Any],
        feedback_memories: list[dict[str, Any]],
    ) -> str:
        example = {
            "available": True,
            "business_intent": "Concise description of what the user is trying to determine.",
            "field_reviews": [
                {
                    "entity_set": "EntitySet",
                    "field": "FieldName",
                    "meaning": "Business meaning inferred from label/description/schema.",
                    "suitable": True,
                    "reason": "Why this field can or cannot answer the request.",
                    "risk": "Any semantic ambiguity or misuse risk.",
                }
            ],
            "recommended_filters": [
                {
                    "entity_set": "EntitySet",
                    "field": "FilterField",
                    "operator": "eq",
                    "value": "literal",
                    "value_type": "string | boolean | number | date",
                    "reason": "Why this filter represents the user's intent.",
                }
            ],
            "recommended_steps": [
                {
                    "entity_set": "EntitySet",
                    "purpose": "What this step should retrieve.",
                    "join_field": "SharedField",
                }
            ],
            "semantic_risks": [
                "Risk to check before executing, such as confusing expected/required flags with completion/open status."
            ],
            "planner_instructions": "Short actionable instructions for the query planner.",
        }
        payload = {
            "user_input": request.resolved_user_input or request.user_input,
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
            "feedback_memories": feedback_memories,
        }
        return (
            f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n\n"
            "Research rules:\n"
            "1. Compare similarly named fields by meaning, not only by lexical overlap.\n"
            "2. Distinguish requirement/expected indicators from actual status, completion, open quantity, or lifecycle fields.\n"
            "3. Distinguish header, item, schedule line, partner, account assignment, history, and text levels.\n"
            "4. If a field is unsuitable, explain why in field_reviews and semantic_risks.\n"
            "5. Recommend filters only when the field exists in schema_context and the value follows from the user intent.\n"
            "6. Preserve user literals exactly, including leading zeros.\n"
            "7. If metadata is insufficient to prove the answer, say so in semantic_risks and planner_instructions.\n\n"
            "8. Distinguish requested output attributes from filters. Bare field-list wording such as "
            "\"with/include/show/display field A and field B\" means those fields should be returned. "
            "Recommend filters only when the user provides an explicit restriction, comparison, literal value, "
            "only/where phrase, true/false requirement, nonzero/open/closed condition, or schema-verified business condition.\n\n"
            "9. For unreceived, undelivered, pending receipt, open goods receipt, or not fully received questions, "
            "prefer actual completion/status or received/open quantity fields over expected/required/configuration flags.\n"
            "10. If both GoodsReceiptIsExpected and IsCompletelyDelivered are available, treat GoodsReceiptIsExpected "
            "as a configuration/expectation flag and prefer IsCompletelyDelivered eq false for not-complete delivery/receipt semantics.\n\n"
            "Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _materialize(parsed: dict[str, Any], schema_context: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        field_keys = {
            (str(field.get("entity_set", "")), str(field.get("field_name", "")))
            for field in schema_context.get("candidate_fields", [])
            if isinstance(field, dict)
        }
        for entity in schema_context.get("entities", []):
            if not isinstance(entity, dict):
                continue
            entity_set = str(entity.get("entity_set", ""))
            for field in entity.get("fields", []):
                if isinstance(field, dict):
                    field_keys.add((entity_set, str(field.get("field_name", ""))))

        field_reviews = []
        for item in parsed.get("field_reviews", []):
            if not isinstance(item, dict):
                continue
            entity_set = str(item.get("entity_set", "") or "")
            field_name = str(item.get("field", "") or "")
            if entity_set and field_name and (entity_set, field_name) not in field_keys:
                continue
            field_reviews.append(
                {
                    "entity_set": entity_set,
                    "field": field_name,
                    "meaning": str(item.get("meaning", "") or ""),
                    "suitable": bool(item.get("suitable", False)),
                    "reason": str(item.get("reason", "") or ""),
                    "risk": str(item.get("risk", "") or ""),
                }
            )

        recommended_filters = []
        for item in parsed.get("recommended_filters", []):
            if not isinstance(item, dict):
                continue
            entity_set = str(item.get("entity_set", "") or "")
            field_name = str(item.get("field", "") or "")
            value = item.get("value")
            if not entity_set or not field_name or value in (None, ""):
                continue
            if (entity_set, field_name) not in field_keys:
                continue
            recommended_filters.append(
                {
                    "entity_set": entity_set,
                    "field": field_name,
                    "operator": str(item.get("operator", "eq") or "eq"),
                    "value": str(value),
                    "value_type": str(item.get("value_type", "") or ""),
                    "reason": str(item.get("reason", "") or ""),
                }
            )

        return {
            **fallback,
            "available": bool(parsed.get("available", True)),
            "business_intent": str(parsed.get("business_intent", fallback["business_intent"]) or fallback["business_intent"]),
            "field_reviews": field_reviews,
            "recommended_filters": recommended_filters,
            "recommended_steps": [
                item for item in parsed.get("recommended_steps", []) if isinstance(item, dict)
            ][:12],
            "semantic_risks": [str(item) for item in parsed.get("semantic_risks", []) if str(item).strip()][:12],
            "planner_instructions": str(parsed.get("planner_instructions", "") or ""),
            "source": "llm_schema_research_agent",
        }

    @staticmethod
    def _fallback_research(request: AgentRequest, route_decision: ApiRouteDecision) -> dict[str, Any]:
        return {
            "available": False,
            "business_intent": route_decision.intent_summary or request.resolved_user_input or request.user_input,
            "field_reviews": [],
            "recommended_filters": [],
            "recommended_steps": [],
            "semantic_risks": [],
            "planner_instructions": "",
            "source": "schema_research_unavailable",
        }
