from __future__ import annotations

from sap_odata_agent.domain.models import (
    AgentRequest,
    CriticFinding,
    FailureAttribution,
    GuardrailDecision,
    PresentationVerification,
    QueryPlan,
)


class FailureAttributor:
    def attribute(
        self,
        request: AgentRequest,
        plan: QueryPlan,
        *,
        success: bool,
        final_message: str,
        guardrail_decision: GuardrailDecision | None = None,
        critic_findings: list[CriticFinding] | None = None,
        presentation_verification: PresentationVerification | None = None,
    ) -> FailureAttribution | None:
        critic_findings = critic_findings or []

        if guardrail_decision is not None and not guardrail_decision.accepted:
            return FailureAttribution(
                category="plan_guardrail_blocked",
                root_cause="The plan violated a guardrail before execution.",
                evidence=list(guardrail_decision.reasons),
            )

        blocking_findings = [finding for finding in critic_findings if finding.blocking]
        if blocking_findings:
            blocking_findings = self._sort_blocking_findings(blocking_findings)
            return FailureAttribution(
                category=blocking_findings[0].code,
                root_cause=blocking_findings[0].message,
                evidence=[finding.code for finding in blocking_findings],
            )

        if presentation_verification is not None and not presentation_verification.passed:
            return FailureAttribution(
                category="presenter_mismatch",
                root_cause="The rendered answer is inconsistent with the structured result rows.",
                evidence=list(presentation_verification.issues),
            )

        if success:
            return None

        if plan.needs_clarification:
            return FailureAttribution(
                category="clarification_required",
                root_cause="The planner determined that more context is needed before querying SAP.",
                evidence=[plan.clarification_question or ""],
            )

        if request.constraints and request.constraints.target_field_concepts:
            return FailureAttribution(
                category="target_field_lost_or_unresolved",
                root_cause="The execution did not complete successfully after planning the requested target field.",
                evidence=[*request.constraints.target_field_concepts, final_message],
            )

        return FailureAttribution(
            category="sap_execution_error",
            root_cause=final_message,
            evidence=[plan.entity_set, plan.plan_kind],
        )

    @staticmethod
    def _sort_blocking_findings(findings: list[CriticFinding]) -> list[CriticFinding]:
        priority = {
            "schema_filter_value_dropped": 0,
            "schema_missing_required_filter_field": 1,
            "filter_concept_missing": 2,
            "llm_filter_concept_missing": 3,
            "llm_wrong_entity_for_target": 4,
            "llm_wrong_entity_selection": 4,
            "required_field_available_but_not_selected": 5,
            "required_target_field_missing": 6,
            "llm_required_target_field_missing": 7,
            "anchor_field_misclassified_as_target": 20,
            "recalled_answer_field_not_in_constraints": 21,
        }
        return sorted(
            findings,
            key=lambda finding: priority.get(finding.code, 10),
        )
