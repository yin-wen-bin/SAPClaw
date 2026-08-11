from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class QueryConstraints:
    target_field_concepts: list[str] = field(default_factory=list)
    filter_concepts: list[str] = field(default_factory=list)
    filter_values: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeValidationContext:
    user_input: str
    resolved_user_input: str | None = None
    constraints: QueryConstraints | None = None
    detected_time_expressions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class FeasibilityViolation:
    code: str
    message: str
    field: str | None = None
    entity_set: str | None = None
    step_id: str | None = None

@dataclass(slots=True)
class FeasibilityResult:
    passed: bool = True
    violations: list[FeasibilityViolation] = field(default_factory=list)
    coverage: dict[str, list[str]] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)

@dataclass(slots=True)
class SelectedApi:
    service_name: str
    confidence: float = 0.0
    reason: str = ""

@dataclass(slots=True)
class ApiRouteDecision:
    resolved_user_input: str = ""
    should_carry_context: bool = False
    selected_apis: list[SelectedApi] = field(default_factory=list)
    requires_multi_api: bool = False
    intent_summary: str = ""
    business_domain: str = ""
    business_object: str = ""
    needs_clarification: bool = False
    clarification_question: str | None = None
    clarification_options: list[str] = field(default_factory=list)
    raw_response: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class RetrievedDocument:
    source: str
    title: str
    content: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class FilterCondition:
    field: str
    operator: str
    value: str
    value_type: str = "string"

@dataclass(slots=True)
class FunctionParameter:
    name: str
    value: str
    value_type: str = "string"

@dataclass(slots=True)
class AggregateMetric:
    operation: str
    output_field: str
    distinct_fields: list[str] = field(default_factory=list)
    field: str | None = None
    currency_field: str | None = None

@dataclass(slots=True)
class ResultTransform:
    type: str = ""
    group_by: list[str] = field(default_factory=list)
    sum_fields: list[str] = field(default_factory=list)
    metrics: list[AggregateMetric] = field(default_factory=list)
    deduplicate_by: list[str] = field(default_factory=list)

@dataclass(slots=True)
class OutputContract:
    """A schema-bound contract for fields visible in a SAPClaw Runtime result."""

    mode: str = "inferred"
    display_grain: str = ""
    requested_fields: list[str] = field(default_factory=list)
    display_fields: list[str] = field(default_factory=list)
    support_fields: list[str] = field(default_factory=list)
    reason: str = ""

@dataclass(slots=True)
class StepBinding:
    field: str
    source_step_id: str
    source_field: str
    fanout: bool = False
    fetch_all_for_binding: bool = False

@dataclass(slots=True)
class ExecutionStep:
    step_id: str
    entity_set: str
    service_name: str | None = None
    http_method: str = "GET"
    select_fields: list[str] = field(default_factory=list)
    response_summary_fields: list[str] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    filter_from_previous: list[StepBinding] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)
    top: int | None = 20
    rationale: str = ""

@dataclass(slots=True)
class QueryPlan:
    service_name: str
    entity_set: str
    http_method: str = "GET"
    select_fields: list[str] = field(default_factory=list)
    response_summary_fields: list[str] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)
    top: int | None = 20
    payload: dict[str, Any] | None = None
    requires_confirmation: bool = False
    needs_clarification: bool = False
    clarification_question: str | None = None
    clarification_options: list[str] = field(default_factory=list)
    response_directive: str = ""
    rationale: str = ""
    plan_kind: str = "direct"
    anchor_object: str | None = None
    anchor_value: str | None = None
    target_field: str | None = None
    target_entity_set: str | None = None
    path_id: str | None = None
    steps: list[ExecutionStep] = field(default_factory=list)
    function_parameters: list[FunctionParameter] = field(default_factory=list)
    result_transform: ResultTransform | None = None
    output_contract: OutputContract | None = None

@dataclass(slots=True)
class ValidationIssue:
    severity: str
    message: str
    field: str | None = None

@dataclass(slots=True)
class CompiledRequest:
    method: str
    url: str
    payload: dict[str, Any] | None = None

@dataclass(slots=True)
class ExecutionAttempt:
    attempt_number: int
    request: CompiledRequest
    success: bool
    step_id: str | None = None
    status_code: int | None = None
    response_preview: dict[str, Any] | None = None
    extracted_values: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
