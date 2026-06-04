from __future__ import annotations

import json
import re
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
                    message=self._localize_message(
                        request,
                        f"LLM plan critic skipped after client error: {exc}",
                        "LLM 计划评审因客户端错误跳过，请查看执行详情。",
                    ),
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
            if self._is_spurious_schema_research_intent_override(request, code, message):
                continue
            if self._is_spurious_unrequested_field_requirement(request, code, message):
                continue
            if self._is_spurious_unrequested_name_field_finding(request, code, message):
                continue
            if self._is_spurious_supplier_address_binding_finding(plan, code, message):
                continue
            message = self._localize_message(
                request,
                message,
                "计划评审未通过：当前查询计划无法可靠支持用户提出的业务问题。",
            )
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
            "- Treat user_input, resolved_user_input, and constraints as authoritative for requested output fields. schema_research.business_intent is advisory and may contain candidate-field guesses; never use it to invent extra required fields that the user did not ask for.\n"
            "- Treat bare field-list wording such as \"with/include/show/display field A and field B\" as requested answer fields, not missing filters.\n"
            "- Report missing_filters only when the user supplied an explicit filter concept plus a value, comparison, only/where phrase, true/false requirement, nonzero condition, or open/closed business condition.\n"
            "- Do not block a plan that selects the mentioned fields solely because those fields could also be filterable status indicators.\n"
            "- Block if a stronger metadata candidate clearly maps to the requested concept and the plan selected a different concept.\n"
            "- Block if an identifier field is used as the answer when the user asked for another attribute.\n"
            "- Block if the plan cannot apply the user's requested filter.\n"
            "- When schema_research is available, use it as semantic evidence for field suitability and risks, but not as a replacement for the user's actual requested fields.\n"
            "- Return finding.message in the same natural language as user_input/resolved_user_input. Keep SAP technical field names unchanged.\n"
            "- Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _localize_message(request: AgentRequest, message: str, chinese_fallback: str) -> str:
        user_text = f"{request.resolved_user_input or ''} {request.user_input or ''}"
        if not any("\u4e00" <= char <= "\u9fff" for char in user_text):
            return message
        if any("\u4e00" <= char <= "\u9fff" for char in message):
            return message
        return chinese_fallback

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

    @staticmethod
    def _is_spurious_schema_research_intent_override(
        request: AgentRequest,
        code: str,
        message: str,
    ) -> bool:
        normalized = f"{code} {message}".lower()
        if "missing_intent_fields" not in normalized and "intent summary" not in normalized:
            return False
        constraints = request.constraints
        if constraints and constraints.target_field_concepts:
            return False
        user_text = f"{request.resolved_user_input or ''} {request.user_input or ''}".lower()
        mentioned_fields = re.findall(r"\b[A-Z][A-Za-z0-9]*(?:[A-Z][A-Za-z0-9]*)+\b", message)
        for field in mentioned_fields:
            tokens = [token.lower() for token in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", field)]
            informative = [token for token in tokens if len(token) >= 4 or token in {"gl", "id", "wbs"}]
            if informative and all(token in user_text for token in informative):
                return False
        return True

    @staticmethod
    def _is_spurious_unrequested_field_requirement(
        request: AgentRequest,
        code: str,
        message: str,
    ) -> bool:
        normalized = f"{code} {message}".lower()
        if not any(marker in normalized for marker in ("missing", "required", "critical", "wrong_field")):
            return False
        user_text = f"{request.resolved_user_input or ''} {request.user_input or ''}".lower()
        concept_groups = [
            (("name", "名称", "名字", "description", "描述", "text field"), ("name", "名称", "名字", "description", "描述", "文本")),
            (("postingdate", "documentdate", "date", "日期", "过账日期", "凭证日期"), ("date", "日期", "过账日期", "凭证日期")),
            (("debit", "credit", "debitcredit", "借贷", "借方", "贷方"), ("debit", "credit", "借贷", "借方", "贷方")),
        ]
        mentioned_groups = [
            requested_markers
            for message_markers, requested_markers in concept_groups
            if any(marker in normalized for marker in message_markers)
        ]
        if not mentioned_groups:
            return False
        return not any(
            marker in user_text
            for requested_markers in mentioned_groups
            for marker in requested_markers
        )

    @staticmethod
    def _is_spurious_unrequested_name_field_finding(
        request: AgentRequest,
        code: str,
        message: str,
    ) -> bool:
        normalized = f"{code} {message}".lower()
        if "wrong_field" not in normalized and "field_semantics" not in normalized:
            return False
        if not any(marker in normalized for marker in ("name", "名称", "text field", "description")):
            return False
        user_text = f"{request.resolved_user_input or ''} {request.user_input or ''}".lower()
        requested_name_markers = (
            "名称",
            "名字",
            "描述",
            "文本",
            "name",
            "description",
            "text",
        )
        return not any(marker in user_text for marker in requested_name_markers)

    @staticmethod
    def _is_spurious_supplier_address_binding_finding(
        plan: QueryPlan,
        code: str,
        message: str,
    ) -> bool:
        normalized = f"{code} {message}".lower()
        if "wrong_field" not in normalized and "field_semantics" not in normalized:
            return False
        if "supplier" not in normalized or "businesspartner" not in normalized:
            return False
        if plan.service_name != "API_BUSINESS_PARTNER":
            return False
        if plan.filters:
            return False
        steps_by_id = {step.step_id: step for step in plan.steps or []}
        supplier_step_ids = {
            step.step_id
            for step in plan.steps or []
            if step.entity_set == "A_Supplier"
            and (
                "Supplier" in set(step.select_fields or [])
                or any(condition.field == "Supplier" for condition in step.filters or [])
            )
        }
        if not supplier_step_ids:
            return False
        for step in plan.steps or []:
            if step.entity_set != "A_BusinessPartnerAddress":
                continue
            for binding in step.filter_from_previous or []:
                if (
                    binding.field == "BusinessPartner"
                    and binding.source_field == "Supplier"
                    and binding.source_step_id in supplier_step_ids
                    and binding.source_step_id in steps_by_id
                ):
                    return True
        return False
