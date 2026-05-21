from __future__ import annotations

import re
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
from sap_odata_agent.infrastructure.indexing.function_imports import function_imports_from_snapshot
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
            snapshot = self._load_snapshot(plan.service_name or self.service_name)
        except FileNotFoundError:
            try:
                snapshot = self._load_snapshot(self.service_name)
            except FileNotFoundError:
                return FeasibilityResult(
                    passed=True,
                    evidence=["schema_feasibility_skipped:index_unavailable"],
                )

        violations: list[FeasibilityViolation] = []
        evidence: list[str] = []
        coverage: dict[str, list[str]] = {"answer_fields": [], "filter_fields": []}
        entity_sets = {entity.get("entity_set", "") for entity in snapshot.entities}
        plan_metadata_entity_set = self._metadata_entity_set(snapshot, plan.entity_set)
        if plan_metadata_entity_set != plan.entity_set:
            evidence.append(f"entity_path_normalized:{plan.entity_set}->{plan_metadata_entity_set}")
        function_imports = {
            str(item.get("name", "") or item.get("entity_set", "")): item
            for item in function_imports_from_snapshot(snapshot)
        }
        is_function_import = plan.plan_kind == "function_import"
        planner_failure_reason = self._planner_failure_reason(plan)
        if planner_failure_reason:
            planner_timed_out = self._is_timeout_text(planner_failure_reason)
            violations.append(
                FeasibilityViolation(
                    code="planner_llm_timeout" if planner_timed_out else "planner_failed",
                    message=self._planner_failure_message(request, planner_failure_reason, planner_timed_out),
                    entity_set=plan.entity_set,
                )
            )
        elif is_function_import and plan.entity_set not in function_imports:
            violations.append(
                FeasibilityViolation(
                    code="function_import_not_found",
                    message=f"Function import `{plan.entity_set}` is not present in indexed metadata.",
                    entity_set=plan.entity_set,
                )
            )
        elif not is_function_import and plan_metadata_entity_set not in entity_sets:
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

        if is_function_import:
            function_import = function_imports.get(plan.entity_set, {})
            self._validate_function_import(plan, function_import, violations, evidence)
            selected_fields = {
                str(item.get("field_name", ""))
                for item in function_import.get("return_fields", [])
                if item.get("field_name")
            }
            filter_fields = {parameter.name for parameter in plan.function_parameters or []}
        elif plan.plan_kind in {"lookup", "multi_step"} and plan.steps:
            self._validate_steps(plan, violations, evidence)
            selected_fields = self._selected_fields(plan)
            filter_fields = self._step_filter_fields(plan.steps)
        else:
            entity_field_map = self._field_map(snapshot, plan_metadata_entity_set)
            self._validate_direct_fields(plan, entity_field_map, violations)
            selected_fields = set(plan.select_fields or [])
            filter_fields = {condition.field for condition in plan.filters or []}

        self._validate_result_transform(plan, violations, evidence)

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
    def _planner_failure_message(request: AgentRequest, reason: str, timed_out: bool) -> str:
        user_text = f"{request.resolved_user_input or ''} {request.user_input or ''}"
        if any("\u4e00" <= char <= "\u9fff" for char in user_text):
            if timed_out:
                return "Planner LLM 在生成可执行查询计划前超时，未向 SAP 发起请求。"
            return f"Planner 未能生成可执行的 schema 查询计划：{reason}"
        return (
            "Planner LLM timed out before producing an executable query plan. No SAP request was executed."
            if timed_out
            else f"Planner did not produce an executable schema plan: {reason}"
        )

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
        plan: QueryPlan,
        violations: list[FeasibilityViolation],
        evidence: list[str],
    ) -> None:
        steps = plan.steps
        by_step = {step.step_id: step for step in steps}
        selected_by_step = {step.step_id: set(step.select_fields or []) for step in steps}
        for index, step in enumerate(steps):
            service_name = step.service_name or plan.service_name or self.service_name
            try:
                snapshot = self._load_snapshot(service_name)
            except FileNotFoundError:
                violations.append(
                    FeasibilityViolation(
                        code="step_service_not_found",
                        message=f"Step `{step.step_id}` service `{service_name}` is not present in local index.",
                        entity_set=step.entity_set,
                        step_id=step.step_id,
                    )
                )
                continue
            step_metadata_entity_set = self._metadata_entity_set(snapshot, step.entity_set)
            if step_metadata_entity_set != step.entity_set:
                evidence.append(f"step_entity_path_normalized:{step.step_id}:{step.entity_set}->{step_metadata_entity_set}")
            field_map = self._field_map(snapshot, step_metadata_entity_set)
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

    def _validate_result_transform(
        self,
        plan: QueryPlan,
        violations: list[FeasibilityViolation],
        evidence: list[str],
    ) -> None:
        transform = plan.result_transform
        if transform is None:
            return
        if transform.type != "aggregate":
            violations.append(
                FeasibilityViolation(
                    code="unsupported_result_transform",
                    message=f"Unsupported result_transform type `{transform.type}`.",
                    entity_set=plan.entity_set,
                )
            )
            return

        service_name = plan.service_name or self.service_name
        entity_set = plan.entity_set
        if plan.steps:
            target_step = next(
                (step for step in plan.steps if step.entity_set == (plan.target_entity_set or plan.entity_set)),
                plan.steps[-1],
            )
            service_name = target_step.service_name or service_name
            entity_set = target_step.entity_set
        try:
            snapshot = self._load_snapshot(service_name)
        except FileNotFoundError:
            violations.append(
                FeasibilityViolation(
                    code="result_transform_service_not_found",
                    message=f"result_transform service `{service_name}` is not present in local index.",
                    entity_set=entity_set,
                )
            )
            return
        metadata_entity_set = self._metadata_entity_set(snapshot, entity_set)
        if metadata_entity_set != entity_set:
            evidence.append(f"result_transform_entity_path_normalized:{entity_set}->{metadata_entity_set}")
        field_map = self._field_map(snapshot, metadata_entity_set)
        selected_fields = self._selected_fields(plan)
        for field_name in transform.group_by:
            if field_name not in field_map:
                violations.append(
                    FeasibilityViolation(
                        code="result_transform_group_field_not_in_entity",
                        message=f"result_transform group_by field `{field_name}` is not present on `{entity_set}`.",
                        field=field_name,
                        entity_set=entity_set,
                    )
                )
            elif field_name not in selected_fields:
                violations.append(
                    FeasibilityViolation(
                        code="result_transform_group_field_not_selected",
                        message=f"result_transform group_by field `{field_name}` is not selected.",
                        field=field_name,
                        entity_set=entity_set,
                    )
                )
        for field_name in transform.sum_fields:
            field = field_map.get(field_name)
            if field is None:
                violations.append(
                    FeasibilityViolation(
                        code="result_transform_sum_field_not_in_entity",
                        message=f"result_transform sum field `{field_name}` is not present on `{entity_set}`.",
                        field=field_name,
                        entity_set=entity_set,
                    )
                )
            elif field_name not in selected_fields:
                violations.append(
                    FeasibilityViolation(
                        code="result_transform_sum_field_not_selected",
                        message=f"result_transform sum field `{field_name}` is not selected.",
                        field=field_name,
                        entity_set=entity_set,
                    )
                )
            elif not self._is_numeric_field(field):
                violations.append(
                    FeasibilityViolation(
                        code="result_transform_sum_field_not_numeric",
                        message=f"result_transform sum field `{field_name}` is not numeric.",
                        field=field_name,
                        entity_set=entity_set,
                    )
                )
        evidence.append(
            "result_transform:aggregate:"
            + ",".join([*transform.group_by, *transform.sum_fields])
        )

    def _load_snapshot(self, service_name: str):
        return self.loader.load(service_name)

    @staticmethod
    def _validate_function_import(
        plan: QueryPlan,
        function_import: dict[str, Any],
        violations: list[FeasibilityViolation],
        evidence: list[str],
    ) -> None:
        parameters = {parameter.name: parameter for parameter in plan.function_parameters or []}
        if not parameters:
            violations.append(
                FeasibilityViolation(
                    code="missing_function_import_parameters",
                    message=f"Function import `{plan.entity_set}` has no input parameters.",
                    entity_set=plan.entity_set,
                )
            )
            return

        metadata_parameters = {
            str(item.get("name", "")): item
            for item in function_import.get("parameters", [])
            if item.get("name")
        }
        for parameter_name, parameter in parameters.items():
            if metadata_parameters and parameter_name not in metadata_parameters:
                violations.append(
                    FeasibilityViolation(
                        code="unknown_function_import_parameter",
                        message=f"Function import `{plan.entity_set}` does not define parameter `{parameter_name}`.",
                        field=parameter_name,
                        entity_set=plan.entity_set,
                    )
                )
            expected_type = str(metadata_parameters.get(parameter_name, {}).get("value_type", "") or "")
            if (
                expected_type
                and parameter.value_type
                and SchemaFeasibilityValidator._normalize_value_type(parameter.value_type)
                != SchemaFeasibilityValidator._normalize_value_type(expected_type)
            ):
                violations.append(
                    FeasibilityViolation(
                        code="function_import_parameter_type_mismatch",
                        message=(
                            f"Function import parameter `{parameter_name}` expects `{expected_type}`, "
                            f"but plan used `{parameter.value_type}`."
                        ),
                        field=parameter_name,
                        entity_set=plan.entity_set,
                    )
                )

        for parameter_name, metadata in metadata_parameters.items():
            if metadata.get("required", True) and parameter_name not in parameters:
                violations.append(
                    FeasibilityViolation(
                        code="missing_function_import_parameter",
                        message=f"Function import `{plan.entity_set}` requires parameter `{parameter_name}`.",
                        field=parameter_name,
                        entity_set=plan.entity_set,
                    )
                )
            elif metadata.get("required", True) and not parameters[parameter_name].value.strip():
                violations.append(
                    FeasibilityViolation(
                        code="empty_required_function_import_parameter",
                        message=f"Function import `{plan.entity_set}` requires non-empty parameter `{parameter_name}`.",
                        field=parameter_name,
                        entity_set=plan.entity_set,
                    )
                )
        evidence.append(f"function_import_parameters:{','.join(sorted(parameters))}")

    @staticmethod
    def _normalize_value_type(value_type: str) -> str:
        normalized = str(value_type or "").lower().replace("edm.", "")
        if normalized in {"datetimeoffset"}:
            return "datetimeoffset"
        if normalized in {"datetime", "date"}:
            return "datetime"
        if normalized in {"decimal"}:
            return "decimal"
        if normalized in {"bool", "boolean"}:
            return "boolean"
        if normalized in {"int16", "int32", "int64", "integer", "int", "double", "single", "number"}:
            return "number"
        return normalized or "string"

    @staticmethod
    def _is_numeric_field(field: dict[str, Any]) -> bool:
        data_type = str(field.get("data_type") or "").lower()
        return not data_type or any(token in data_type for token in ("decimal", "double", "single", "int", "byte"))

    @staticmethod
    def _field_map(snapshot, entity_set: str) -> dict[str, dict[str, Any]]:
        return {
            str(field.get("field_name", "")): field
            for field in snapshot.fields
            if field.get("entity_set") == entity_set and field.get("field_name")
        }

    @staticmethod
    def _metadata_entity_set(snapshot, entity_set: str) -> str:
        entity_sets = {
            str(entity.get("entity_set", ""))
            for entity in snapshot.entities
            if entity.get("entity_set")
        }
        raw = str(entity_set or "")
        if raw in entity_sets:
            return raw

        path = raw.split("?", 1)[0].strip("/")
        if not path or ("/" not in path and "(" not in path):
            return raw

        segments = [segment for segment in path.split("/") if segment]
        if not segments:
            return raw
        base = re.sub(r"\(.*\)$", "", segments[0])
        navigation = re.sub(r"\(.*\)$", "", segments[-1]) if len(segments) > 1 else ""
        candidates = []
        if base and navigation:
            candidates.append(f"{base}{navigation}")
        if navigation:
            candidates.append(navigation)
        if base:
            candidates.append(base)
        for candidate in candidates:
            if candidate in entity_sets:
                return candidate

        base_lower = base.lower()
        navigation_lower = navigation.lower()
        for entity in entity_sets:
            lowered = entity.lower()
            if navigation_lower and lowered == f"{base_lower}{navigation_lower}":
                return entity
        for entity in entity_sets:
            lowered = entity.lower()
            if navigation_lower and lowered.endswith(navigation_lower) and lowered.startswith(base_lower):
                return entity
        return raw

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
        for parameter in plan.function_parameters or []:
            if parameter.value in values:
                return True
        for condition in plan.filters or []:
            if condition.value in values:
                return True
        for step in plan.steps or []:
            for condition in step.filters or []:
                if condition.value in values:
                    return True
        return False
