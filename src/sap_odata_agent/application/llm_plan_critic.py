from __future__ import annotations

import json
from typing import Any

from sap_odata_agent.application.plan_critic import PlanCritic
from sap_odata_agent.domain.models import AgentRequest, CriticFinding, QueryPlan, RetrievedContext
from sap_odata_agent.infrastructure.llm.planner import AnthropicCompatibleMessagesClient, LlmStructuredIntentPlanner


class LlmPlanCritic:
    """Semantic critic that checks whether a plan answers the user's actual question."""

    def __init__(
        self,
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
    ) -> None:
        self.llm_client = llm_client
        self.enabled = enabled

    def review(
        self,
        request: AgentRequest,
        context: RetrievedContext | None,
        plan: QueryPlan,
        existing_findings: list[CriticFinding] | None = None,
        schema_research: dict[str, Any] | None = None,
    ) -> list[CriticFinding]:
        if not self.enabled or self.llm_client is None:
            return []
        try:
            raw = self.llm_client.complete_json(
                self._system_prompt(),
                self._user_prompt(request, context, plan, existing_findings or [], schema_research or {}),
                max_tokens=900,
            )
            parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
        except Exception as exc:
            return [
                CriticFinding(
                    code="llm_critic_unavailable",
                    message=f"LLM plan critic skipped after client error: {exc}",
                    severity="warning",
                    blocking=False,
                )
            ]

        findings: list[CriticFinding] = []
        for item in parsed.get("findings", []):
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "") or "").strip()
            message = str(item.get("message", "") or "").strip()
            if not code or not message:
                continue
            if self._is_spurious_field_list_missing_filter(request, plan, code, message):
                continue
            severity = str(item.get("severity", "warning") or "warning")
            blocking = bool(item.get("blocking", False))
            findings.append(
                CriticFinding(
                    code=f"llm_{code}",
                    message=message,
                    severity="error" if blocking else severity,
                    blocking=blocking,
                )
            )
        return findings

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are a conservative SAP OData plan critic. "
            "Check whether the selected entity, fields, filters, and path can answer the user question. "
            "Return JSON only. Do not require perfection; block only clear semantic mismatches."
        )

    @staticmethod
    def _user_prompt(
        request: AgentRequest,
        context: RetrievedContext | None,
        plan: QueryPlan,
        existing_findings: list[CriticFinding],
        schema_research: dict[str, Any],
    ) -> str:
        example = {
            "pass": False,
            "findings": [
                {
                    "code": "wrong_field_semantics",
                    "message": "The plan selects a field whose metadata meaning does not match the user request.",
                    "severity": "error",
                    "blocking": True,
                    "repair_hints": {"preferred_field": "<field from retrieved metadata>", "preferred_entity_set": "<entity from retrieved metadata>"},
                }
            ],
        }
        payload: dict[str, Any] = {
            "user_input": request.user_input,
            "resolved_user_input": request.resolved_user_input or request.user_input,
            "semantic_frame": request.semantic_frame,
            "schema_rerank": request.schema_rerank,
            "constraints": {
                "target_object": request.constraints.target_object if request.constraints else None,
                "target_field_concepts": request.constraints.target_field_concepts if request.constraints else [],
                "filter_concepts": request.constraints.filter_concepts if request.constraints else [],
                "filter_values": request.constraints.filter_values if request.constraints else [],
                "query_shape": request.constraints.query_shape.value if request.constraints else "",
            },
            "plan": {
                "plan_kind": plan.plan_kind,
                "path_id": plan.path_id,
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
            "existing_findings": [
                {"code": item.code, "message": item.message, "blocking": item.blocking}
                for item in existing_findings
            ],
            "schema_research": schema_research,
            "retrieved_context": [
                {
                    "source": doc.source,
                    "title": doc.title,
                    "score": doc.score,
                    "metadata": {
                        "entity_set": (doc.metadata or {}).get("entity_set", ""),
                        "field_name": (doc.metadata or {}).get("field_name", ""),
                        "label": (doc.metadata or {}).get("label", ""),
                        "description": (doc.metadata or {}).get("description", ""),
                    },
                }
                for doc in (context.documents if context else [])[:12]
            ],
        }
        return (
            f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Critique rules:\n"
            "- Do not block if the selected fields can plausibly answer the request.\n"
            "- Treat constraints.target_field_concepts as the authoritative required answer fields; do not add extra required fields only because similarly named candidates have high scores.\n"
            "- Treat bare field-list wording such as \"with/include/show/display field A and field B\" as requested answer fields, not missing filters.\n"
            "- Report missing_filters only when the user supplied an explicit filter concept plus a value, comparison, only/where phrase, true/false requirement, nonzero condition, or open/closed business condition.\n"
            "- Do not block a plan that selects the mentioned fields solely because those fields could also be filterable status indicators.\n"
            "- Block if a stronger metadata candidate clearly maps to the requested concept and the plan selected a different concept.\n"
            "- Block if an identifier field is used as the answer when the user asked for another attribute.\n"
            "- Block if the plan cannot apply the user's requested filter.\n"
            "- When schema_research is available, use it as the primary semantic evidence for field suitability and risks.\n"
            "- Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _is_spurious_field_list_missing_filter(
        request: AgentRequest,
        plan: QueryPlan,
        code: str,
        message: str,
    ) -> bool:
        normalized = f"{code} {message}".lower()
        if "missing_filter" not in normalized and "missing filters" not in normalized:
            return False
        if not PlanCritic._looks_like_field_list_without_filter_intent(request):
            return False
        selected_fields = set(plan.select_fields or [])
        for step in plan.steps or []:
            selected_fields.update(step.select_fields or [])
        return bool(selected_fields)
