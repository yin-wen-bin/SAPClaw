from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ExecutionMode(str, Enum):
    READ_ONLY = "read_only"
    WRITE_CONFIRM_REQUIRED = "write_confirm_required"


class QueryShape(str, Enum):
    SINGLE_FACT = "single_fact"
    LIST_QUERY = "list_query"
    SEARCH_BY_ATTRIBUTE = "search_by_attribute"
    NAME_CONTAINS_SEARCH = "name_contains_search"
    BOOLEAN_CHECK = "boolean_check"
    CLARIFICATION_ANSWER = "clarification_answer"
    UNKNOWN = "unknown"


class CardinalityPolicy(str, Enum):
    ONE = "one"
    MANY = "many"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ContextCarryDecision:
    should_carry: bool = False
    reason: str = ""
    confidence: float = 0.0


@dataclass(slots=True)
class QueryConstraints:
    query_shape: QueryShape = QueryShape.UNKNOWN
    cardinality: CardinalityPolicy = CardinalityPolicy.UNKNOWN
    target_object: str | None = None
    target_field_concepts: list[str] = field(default_factory=list)
    filter_concepts: list[str] = field(default_factory=list)
    filter_values: list[str] = field(default_factory=list)
    requested_operation: str = "read"
    name_match_mode: str | None = None
    boolean_intent: bool = False


@dataclass(slots=True)
class CandidatePlan:
    candidate_id: str
    candidate_type: str
    entity_set: str | None = None
    path_id: str | None = None
    target_field: str | None = None
    target_entity_set: str | None = None
    hard_constraints_passed: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    final_score: float = 0.0
    ambiguity_group: str | None = None


@dataclass(slots=True)
class SchemaFieldRef:
    service_name: str
    entity_set: str
    field_name: str
    confidence: float = 0.0
    reason: str = ""


@dataclass(slots=True)
class FieldRequirement:
    user_phrase: str
    semantic_role: str = "answer"
    candidate_fields: list[SchemaFieldRef] = field(default_factory=list)
    required: bool = True


@dataclass(slots=True)
class FilterRequirement:
    user_phrase: str
    value: str
    operator: str = "eq"
    candidate_fields: list[SchemaFieldRef] = field(default_factory=list)
    required: bool = True


@dataclass(slots=True)
class SemanticFrame:
    intent_type: str = "unknown"
    target_object: str | None = None
    target_identifier: str | None = None
    answer_requirements: list[FieldRequirement] = field(default_factory=list)
    filter_requirements: list[FilterRequirement] = field(default_factory=list)
    output_shape: str = "text"
    business_scope: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0


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
class PlanCandidate:
    candidate_id: str
    plan: QueryPlan
    llm_confidence: float = 0.0
    schema_proof: dict[str, Any] = field(default_factory=dict)
    feasibility: FeasibilityResult | None = None


@dataclass(slots=True)
class GuardrailDecision:
    accepted: bool = True
    winner: str = "plan"
    reasons: list[str] = field(default_factory=list)
    severity: str = "info"


@dataclass(slots=True)
class CriticFinding:
    code: str
    message: str
    severity: str = "warning"
    blocking: bool = False


@dataclass(slots=True)
class FailureAttribution:
    category: str
    root_cause: str
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PresentationVerification:
    passed: bool = True
    issues: list[str] = field(default_factory=list)


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
class PlanningAttemptRecord:
    attempt_number: int
    stage: str
    plan: QueryPlan | None = None
    success: bool = False
    failure_reason: str = ""
    schema_violations: list[dict[str, Any]] = field(default_factory=list)
    guardrail_reasons: list[str] = field(default_factory=list)
    critic_findings: list[dict[str, Any]] = field(default_factory=list)
    sap_error: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FailureDiagnosis:
    category: str = "unknown"
    root_cause: str = ""
    evidence: list[str] = field(default_factory=list)
    suggested_next_action: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentRequest:
    user_input: str
    conversation_id: str | None = None
    mode: ExecutionMode = ExecutionMode.READ_ONLY
    llm_profile_id: str | None = None
    resolved_user_input: str | None = None
    feedback_hints: list[dict[str, str]] = field(default_factory=list)
    feedback_memories: list[dict[str, Any]] = field(default_factory=list)
    semantic_frame: dict[str, Any] = field(default_factory=dict)
    schema_rerank: dict[str, Any] = field(default_factory=dict)
    query_shape: QueryShape = QueryShape.UNKNOWN
    cardinality_policy: CardinalityPolicy = CardinalityPolicy.UNKNOWN
    constraints: QueryConstraints | None = None
    context_carry_decision: ContextCarryDecision | None = None


@dataclass(slots=True)
class RetrievedDocument:
    source: str
    title: str
    content: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExampleCase:
    case_id: str
    user_input: str
    query_url: str
    summary: str
    score: float = 0.0


@dataclass(slots=True)
class RetrievedContext:
    documents: list[RetrievedDocument] = field(default_factory=list)
    examples: list[ExampleCase] = field(default_factory=list)


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
class StepBinding:
    field: str
    source_step_id: str
    source_field: str


@dataclass(slots=True)
class ExecutionStep:
    step_id: str
    entity_set: str
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
    planner_diagnostics: dict[str, Any] = field(default_factory=dict)
    plan_kind: str = "direct"
    anchor_object: str | None = None
    anchor_value: str | None = None
    target_field: str | None = None
    target_entity_set: str | None = None
    path_id: str | None = None
    steps: list[ExecutionStep] = field(default_factory=list)
    function_parameters: list[FunctionParameter] = field(default_factory=list)


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


@dataclass(slots=True)
class ResultPresentation:
    kind: str = "text"
    title: str = "查询结果"
    text: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class QueryFeedback:
    status: str
    comment: str = ""
    expected_result: str = ""
    created_at: datetime | None = None


@dataclass(slots=True)
class CaseRecord:
    case_id: str
    created_at: datetime
    request: AgentRequest
    context: RetrievedContext
    initial_plan: QueryPlan
    final_plan: QueryPlan | None
    attempts: list[ExecutionAttempt]
    final_status: str
    final_query_url: str | None
    response_preview: dict[str, Any] | None
    effective_user_input: str | None = None
    presentation: ResultPresentation | None = None
    guardrail_decision: GuardrailDecision | None = None
    critic_findings: list[CriticFinding] = field(default_factory=list)
    failure_attribution: FailureAttribution | None = None
    presentation_verification: PresentationVerification | None = None
    timings: list[dict[str, Any]] = field(default_factory=list)
    timing_summary: dict[str, float] = field(default_factory=dict)
    total_duration_ms: float | None = None
    route_decision: ApiRouteDecision | None = None
    planning_attempts: list[PlanningAttemptRecord] = field(default_factory=list)
    schema_context_summary: dict[str, Any] = field(default_factory=dict)
    final_failure_diagnosis: FailureDiagnosis | None = None
    feedback_memories_used: list[dict[str, Any]] = field(default_factory=list)
    feedback: QueryFeedback | None = None
    error_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentResponse:
    success: bool
    plan: QueryPlan
    validation_issues: list[ValidationIssue]
    attempts: list[ExecutionAttempt]
    data: dict[str, Any] | None = None
    presentation: ResultPresentation | None = None
    final_message: str = ""
    needs_clarification: bool = False
    clarification_question: str | None = None
    clarification_options: list[str] = field(default_factory=list)
    guardrail_decision: GuardrailDecision | None = None
    critic_findings: list[CriticFinding] = field(default_factory=list)
    failure_attribution: FailureAttribution | None = None
    presentation_verification: PresentationVerification | None = None
    timings: list[dict[str, Any]] = field(default_factory=list)
    timing_summary: dict[str, float] = field(default_factory=dict)
    total_duration_ms: float | None = None
    case_id: str | None = None
