from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sap_odata_agent.domain.models import (
    AgentRequest,
    CriticFinding,
    ExecutionStep,
    FeasibilityResult,
    FeasibilityViolation,
    QueryPlan,
)
from sap_odata_agent.infrastructure.indexing.index_loader import LocalIndexLoader


class SchemaFeasibilityValidator:
    """Validate that a plan can be proven against the indexed OData schema.

    This is deliberately API-neutral: it checks entity/field/filter/path facts,
    not BP-specific business rules.
    """

    def __init__(
        self,
        index_root: str = "data/index",
        service_name: str = "API_BUSINESS_PARTNER",
        enabled: bool = True,
    ) -> None:
        self.loader = LocalIndexLoader(index_root=index_root)
        self.service_name = service_name
        self.enabled = enabled

    def validate(self, request: AgentRequest, plan: QueryPlan) -> FeasibilityResult:
        if not self.enabled:
            return FeasibilityResult(passed=True)
        try:
            snapshot = self.loader.load(plan.service_name or self.service_name)
        except FileNotFoundError:
            try:
                snapshot = self.loader.load(self.service_name)
            except FileNotFoundError:
                return FeasibilityResult(
                    passed=True,
                    evidence=["schema_feasibility_skipped:index_unavailable"],
                )

        violations: list[FeasibilityViolation] = []
        evidence: list[str] = []
        coverage: dict[str, list[str]] = {"answer_fields": [], "filter_fields": []}
        entity_sets = {entity.get("entity_set", "") for entity in snapshot.entities}
        planner_failure_reason = self._planner_failure_reason(plan)
        if planner_failure_reason:
            planner_timed_out = self._is_timeout_text(planner_failure_reason)
            violations.append(
                FeasibilityViolation(
                    code="planner_llm_timeout" if planner_timed_out else "planner_failed",
                    message=(
                        "Planner LLM timed out before producing an executable query plan. No SAP request was executed."
                        if planner_timed_out
                        else f"Planner did not produce an executable schema plan: {planner_failure_reason}"
                    ),
                    entity_set=plan.entity_set,
                )
            )
        elif plan.entity_set not in entity_sets:
            violations.append(
                FeasibilityViolation(
                    code="entity_not_found",
                    message=f"Entity set `{plan.entity_set}` is not present in indexed metadata.",
                    entity_set=plan.entity_set,
                )
            )

        constraints = request.constraints
        required_answer_fields = set((constraints.target_field_concepts if constraints else []) or [])
        required_filter_fields = set((constraints.filter_concepts if constraints else []) or [])
        required_filter_values = set((constraints.filter_values if constraints else []) or [])

        if plan.plan_kind in {"lookup", "multi_step"} and plan.steps:
            self._validate_steps(snapshot, plan.steps, violations, evidence)
            selected_fields = self._selected_fields(plan)
            filter_fields = self._step_filter_fields(plan.steps)
        else:
            entity_field_map = self._field_map(snapshot, plan.entity_set)
            self._validate_direct_fields(plan, entity_field_map, violations)
            selected_fields = set(plan.select_fields or [])
            filter_fields = {condition.field for condition in plan.filters or []}

        covered_answer_fields = sorted(required_answer_fields & selected_fields)
        covered_filter_fields = sorted(required_filter_fields & filter_fields)
        coverage["answer_fields"] = covered_answer_fields
        coverage["filter_fields"] = covered_filter_fields

        if required_answer_fields and not covered_answer_fields:
            violations.append(
                FeasibilityViolation(
                    code="missing_required_answer_field",
                    message=(
                        "The plan does not select any required answer field: "
                        + ", ".join(sorted(required_answer_fields))
                    ),
                    entity_set=plan.entity_set,
                )
            )

        if required_filter_fields and not covered_filter_fields:
            violations.append(
                FeasibilityViolation(
                    code="missing_required_filter_field",
                    message=(
                        "The plan does not apply any required filter field: "
                        + ", ".join(sorted(required_filter_fields))
                    ),
                    entity_set=plan.entity_set,
                )
            )

        if required_filter_values and not self._plan_contains_filter_value(plan, required_filter_values):
            violations.append(
                FeasibilityViolation(
                    code="filter_value_dropped",
                    message=(
                        "The plan does not preserve required filter value(s): "
                        + ", ".join(sorted(required_filter_values))
                    ),
                    entity_set=plan.entity_set,
                )
            )

        if covered_answer_fields:
            evidence.append("answer_fields_covered:" + ",".join(covered_answer_fields))
        if covered_filter_fields:
            evidence.append("filter_fields_covered:" + ",".join(covered_filter_fields))

        return FeasibilityResult(
            passed=not violations,
            violations=violations,
            coverage=coverage,
            evidence=evidence,
        )

    @staticmethod
    def _planner_failure_reason(plan: QueryPlan) -> str:
        diagnostics = plan.planner_diagnostics or {}
        llm_diagnostics = diagnostics.get("llm_dynamic_path_planner") or {}
        reason = str(llm_diagnostics.get("reason") or "").strip()
        accepted = llm_diagnostics.get("accepted")
        if plan.entity_set == "UNKNOWN_ENTITY" and accepted is False and reason:
            return reason
        return ""

    @staticmethod
    def _is_timeout_text(text: str) -> bool:
        value = str(text or "").lower()
        return "timed out" in value or "timeout" in value

    def to_critic_findings(self, result: FeasibilityResult) -> list[CriticFinding]:
        return [
            CriticFinding(
                code=(
                    "planner_llm_timeout"
                    if violation.code == "planner_llm_timeout"
                    else f"schema_{violation.code}"
                ),
                message=violation.message,
                severity="error",
                blocking=True,
            )
            for violation in result.violations
        ]

    @staticmethod
    def to_debug_payload(result: FeasibilityResult) -> dict[str, Any]:
        return asdict(result)

    def _validate_direct_fields(
        self,
        plan: QueryPlan,
        entity_field_map: dict[str, dict[str, Any]],
        violations: list[FeasibilityViolation],
    ) -> None:
        for field_name in plan.select_fields or []:
            if field_name not in entity_field_map:
                violations.append(
                    FeasibilityViolation(
                        code="select_field_not_in_entity",
                        message=f"Selected field `{field_name}` is not present on `{plan.entity_set}`.",
                        field=field_name,
                        entity_set=plan.entity_set,
                    )
                )
        for condition in plan.filters or []:
            field = entity_field_map.get(condition.field)
            if field is None:
                violations.append(
                    FeasibilityViolation(
                        code="filter_field_not_in_entity",
                        message=f"Filter field `{condition.field}` is not present on `{plan.entity_set}`.",
                        field=condition.field,
                        entity_set=plan.entity_set,
                    )
                )
                continue
            if field.get("filterable") is False:
                violations.append(
                    FeasibilityViolation(
                        code="filter_field_not_filterable",
                        message=f"Filter field `{condition.field}` is not filterable on `{plan.entity_set}`.",
                        field=condition.field,
                        entity_set=plan.entity_set,
                    )
                )

    def _validate_steps(
        self,
        snapshot,
        steps: list[ExecutionStep],
        violations: list[FeasibilityViolation],
        evidence: list[str],
    ) -> None:
        by_step = {step.step_id: step for step in steps}
        selected_by_step = {step.step_id: set(step.select_fields or []) for step in steps}
        for index, step in enumerate(steps):
            field_map = self._field_map(snapshot, step.entity_set)
            if not field_map:
                violations.append(
                    FeasibilityViolation(
                        code="step_entity_not_found",
                        message=f"Step `{step.step_id}` entity `{step.entity_set}` is not present in metadata.",
                        entity_set=step.entity_set,
                        step_id=step.step_id,
                    )
                )
                continue
            for field_name in step.select_fields or []:
                if field_name not in field_map:
                    violations.append(
                        FeasibilityViolation(
                            code="step_select_field_not_in_entity",
                            message=f"Step `{step.step_id}` selects unknown field `{field_name}`.",
                            field=field_name,
                            entity_set=step.entity_set,
                            step_id=step.step_id,
                        )
                    )
            for condition in step.filters or []:
                if condition.field not in field_map:
                    violations.append(
                        FeasibilityViolation(
                            code="step_filter_field_not_in_entity",
                            message=f"Step `{step.step_id}` filters on unknown field `{condition.field}`.",
                            field=condition.field,
                            entity_set=step.entity_set,
                            step_id=step.step_id,
                        )
                    )
            for binding in step.filter_from_previous or []:
                if binding.field not in field_map:
                    violations.append(
                        FeasibilityViolation(
                            code="step_binding_target_not_in_entity",
                            message=f"Step `{step.step_id}` binding target `{binding.field}` is not on `{step.entity_set}`.",
                            field=binding.field,
                            entity_set=step.entity_set,
                            step_id=step.step_id,
                        )
                    )
                source_step = by_step.get(binding.source_step_id)
                if source_step is None:
                    violations.append(
                        FeasibilityViolation(
                            code="step_binding_source_missing",
                            message=f"Step `{step.step_id}` references missing source step `{binding.source_step_id}`.",
                            step_id=step.step_id,
                        )
                    )
                elif binding.source_field not in selected_by_step.get(binding.source_step_id, set()):
                    violations.append(
                        FeasibilityViolation(
                            code="step_binding_source_field_not_selected",
                            message=(
                                f"Step `{step.step_id}` needs `{binding.source_field}` from "
                                f"`{binding.source_step_id}`, but it is not selected there."
                            ),
                            field=binding.source_field,
                            entity_set=source_step.entity_set,
                            step_id=step.step_id,
                    )
                )
            if index > 0 and not step.filters and not step.filter_from_previous:
                violations.append(
                    FeasibilityViolation(
                        code="step_missing_filter_or_binding",
                        message=(
                            f"Step `{step.step_id}` has no direct filter or binding from a previous step, "
                            "so it would execute as an unbounded query."
                        ),
                        entity_set=step.entity_set,
                        step_id=step.step_id,
                    )
                )
        if steps:
            evidence.append(f"steps_validated:{len(steps)}")

    @staticmethod
    def _field_map(snapshot, entity_set: str) -> dict[str, dict[str, Any]]:
        return {
            str(field.get("field_name", "")): field
            for field in snapshot.fields
            if field.get("entity_set") == entity_set and field.get("field_name")
        }

    @staticmethod
    def _selected_fields(plan: QueryPlan) -> set[str]:
        fields = set(plan.select_fields or [])
        fields.update(plan.response_summary_fields or [])
        for step in plan.steps or []:
            fields.update(step.select_fields or [])
            fields.update(step.response_summary_fields or [])
        return fields

    @staticmethod
    def _step_filter_fields(steps: list[ExecutionStep]) -> set[str]:
        fields: set[str] = set()
        for step in steps:
            fields.update(condition.field for condition in step.filters or [])
            fields.update(binding.field for binding in step.filter_from_previous or [])
        return fields

    @staticmethod
    def _plan_contains_filter_value(plan: QueryPlan, values: set[str]) -> bool:
        for condition in plan.filters or []:
            if condition.value in values:
                return True
        for step in plan.steps or []:
            for condition in step.filters or []:
                if condition.value in values:
                    return True
        return False
