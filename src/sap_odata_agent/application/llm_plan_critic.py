from __future__ import annotations

import json
from typing import Any

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
    ) -> list[CriticFinding]:
        if not self.enabled or self.llm_client is None:
            return []
        try:
            raw = self.llm_client.complete_json(
                self._system_prompt(),
                self._user_prompt(request, context, plan, existing_findings or []),
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
            "- Block if a stronger metadata candidate clearly maps to the requested concept and the plan selected a different concept.\n"
            "- Block if an identifier field is used as the answer when the user asked for another attribute.\n"
            "- Block if the plan cannot apply the user's requested filter.\n"
            "- Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )
