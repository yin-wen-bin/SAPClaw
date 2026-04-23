from __future__ import annotations

from typing import Any

from sap_odata_agent.domain.models import AgentRequest, CardinalityPolicy, GuardrailDecision, QueryPlan


class PlannerGuardrail:
    def evaluate(self, request: AgentRequest, plan: QueryPlan) -> GuardrailDecision:
        reasons: list[str] = []
        severity = "info"
        accepted = True
        winner = "plan"

        diagnostics = plan.planner_diagnostics or {}
        winner = str(diagnostics.get("planner_winner") or winner)
        adjudication = diagnostics.get("llm_adjudication") or {}
        if isinstance(adjudication, dict):
            for reason in adjudication.get("reasons", []):
                if isinstance(reason, str) and reason not in reasons:
                    reasons.append(reason)
            if winner == "fallback" and adjudication.get("accepted") is False:
                severity = "warning"

        constraints = request.constraints
        if constraints is not None:
            required_fields = set(constraints.target_field_concepts or [])
            selected_fields = set(plan.select_fields or [])
            missing_required_fields = required_fields - selected_fields
            if required_fields and not required_fields.intersection(selected_fields):
                accepted = False
                severity = "blocking"
                reasons.append(
                    "required_target_field_missing:"
                    + ",".join(sorted(required_fields))
                )

            if constraints.cardinality == CardinalityPolicy.MANY and plan.top == 1:
                accepted = False
                severity = "blocking"
                reasons.append("list_query_top_too_small")

            if constraints.name_match_mode == "contains" and plan.filters:
                if not any(filter_item.operator == "contains" for filter_item in plan.filters):
                    accepted = False
                    severity = "blocking"
                    reasons.append("contains_query_built_as_eq")

            if request.user_input and constraints.target_object == "business_partner":
                identifier = next((value for value in constraints.filter_values if str(value).isdigit()), None)
                if identifier and plan.filters:
                    bad_anchor = [
                        filter_item.field
                        for filter_item in plan.filters
                        if filter_item.field in required_fields and filter_item.value == identifier
                    ]
                    if bad_anchor:
                        accepted = False
                        severity = "blocking"
                        reasons.append("identifier_used_as_answer_field")

        if not reasons:
            reasons.append("plan_respects_current_guardrails")

        return GuardrailDecision(
            accepted=accepted,
            winner=winner if accepted else "repair",
            reasons=reasons,
            severity=severity,
        )
