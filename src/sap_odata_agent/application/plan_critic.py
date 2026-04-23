from __future__ import annotations

from sap_odata_agent.domain.models import AgentRequest, CardinalityPolicy, CriticFinding, QueryPlan


class PlanCritic:
    def review(self, request: AgentRequest, plan: QueryPlan) -> list[CriticFinding]:
        constraints = request.constraints
        if constraints is None:
            return []

        findings: list[CriticFinding] = []
        selected_fields = set(plan.select_fields or [])
        filter_fields = {item.field for item in plan.filters}

        required_fields = set(constraints.target_field_concepts or [])
        missing_required = sorted(required_fields - selected_fields)
        if missing_required:
            findings.append(
                CriticFinding(
                    code="required_target_field_missing",
                    message="The final select list does not include the requested target field(s): "
                    + ", ".join(missing_required),
                    severity="error",
                    blocking=True,
                )
            )

        required_filter_fields = set(constraints.filter_concepts or [])
        if required_filter_fields and not required_filter_fields.intersection(filter_fields):
            findings.append(
                CriticFinding(
                    code="filter_concept_missing",
                    message="The plan does not apply any filter for the requested filter concept(s): "
                    + ", ".join(sorted(required_filter_fields)),
                    severity="error",
                    blocking=True,
                )
            )

        if constraints.cardinality == CardinalityPolicy.MANY and plan.top == 1:
            findings.append(
                CriticFinding(
                    code="list_query_top_too_small",
                    message="The query shape expects multiple rows, but the plan is limited to top=1.",
                    severity="error",
                    blocking=True,
                )
            )

        if constraints.name_match_mode == "contains" and plan.filters:
            if not any(item.operator == "contains" for item in plan.filters):
                findings.append(
                    CriticFinding(
                        code="contains_query_built_as_eq",
                        message="The query asks for a contains-style match, but the plan uses exact-match filters only.",
                        severity="error",
                        blocking=True,
                    )
                )

        return findings
