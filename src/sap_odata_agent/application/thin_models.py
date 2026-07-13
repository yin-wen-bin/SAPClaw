from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sap_odata_agent.domain.models import (
    ExecutionStep,
    FilterCondition,
    FunctionParameter,
    QueryPlan,
    ResultTransform,
    StepBinding,
)


FilterOperator = Literal["eq", "ne", "gt", "ge", "lt", "le", "contains", "in"]
PlanKind = Literal["direct", "lookup", "multi_step", "function_import"]


class ThinFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    field: str = Field(min_length=1)
    operator: FilterOperator = "eq"
    value: str
    value_type: str = "string"

    def to_domain(self) -> FilterCondition:
        return FilterCondition(
            field=self.field,
            operator=self.operator,
            value=self.value,
            value_type=self.value_type,
        )


class ThinFunctionParameter(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)
    value: str
    value_type: str = "string"

    def to_domain(self) -> FunctionParameter:
        return FunctionParameter(name=self.name, value=self.value, value_type=self.value_type)


class ThinStepBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    field: str = Field(min_length=1)
    source_step_id: str = Field(min_length=1)
    source_field: str = Field(min_length=1)
    fanout: bool = False
    fetch_all_for_binding: bool = False

    def to_domain(self) -> StepBinding:
        return StepBinding(
            field=self.field,
            source_step_id=self.source_step_id,
            source_field=self.source_field,
            fanout=self.fanout,
            fetch_all_for_binding=self.fetch_all_for_binding,
        )


class ThinExecutionStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    step_id: str = Field(min_length=1)
    entity_set: str = Field(min_length=1)
    service_name: str | None = None
    http_method: Literal["GET"] = "GET"
    select_fields: list[str] = Field(default_factory=list)
    response_summary_fields: list[str] = Field(default_factory=list)
    filters: list[ThinFilter] = Field(default_factory=list)
    filter_from_previous: list[ThinStepBinding] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    top: int | None = Field(default=None, ge=1)
    rationale: str = ""

    @field_validator("select_fields", "response_summary_fields", "order_by")
    @classmethod
    def validate_field_names(cls, values: list[str]) -> list[str]:
        if any(not str(value).strip() for value in values):
            raise ValueError("Field names must not be empty.")
        return list(dict.fromkeys(values))

    def to_domain(self) -> ExecutionStep:
        selected = list(dict.fromkeys([*self.select_fields, *self.response_summary_fields]))
        return ExecutionStep(
            step_id=self.step_id,
            entity_set=self.entity_set,
            service_name=self.service_name,
            http_method=self.http_method,
            select_fields=selected,
            response_summary_fields=list(self.response_summary_fields),
            filters=[item.to_domain() for item in self.filters],
            filter_from_previous=[item.to_domain() for item in self.filter_from_previous],
            order_by=list(self.order_by),
            top=self.top,
            rationale=self.rationale,
        )


class ThinResultTransform(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["aggregate"]
    group_by: list[str] = Field(default_factory=list)
    sum_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_transform_fields(self) -> "ThinResultTransform":
        if not self.group_by and not self.sum_fields:
            raise ValueError("An aggregate transform requires group_by or sum_fields.")
        return self

    def to_domain(self) -> ResultTransform:
        return ResultTransform(
            type=self.type,
            group_by=list(dict.fromkeys(self.group_by)),
            sum_fields=list(dict.fromkeys(self.sum_fields)),
        )


class ThinQueryPlan(BaseModel):
    """Strict Codex-authored plan accepted by the read-only Thin Runtime."""

    model_config = ConfigDict(extra="forbid", strict=True)

    service_name: str = Field(min_length=1)
    entity_set: str = Field(min_length=1)
    http_method: Literal["GET"] = "GET"
    select_fields: list[str] = Field(default_factory=list)
    response_summary_fields: list[str] = Field(default_factory=list)
    filters: list[ThinFilter] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    top: int | None = Field(default=None, ge=1)
    plan_kind: PlanKind = "direct"
    target_entity_set: str | None = None
    anchor_object: str | None = None
    anchor_value: str | None = None
    target_field: str | None = None
    path_id: str | None = None
    steps: list[ThinExecutionStep] = Field(default_factory=list)
    function_parameters: list[ThinFunctionParameter] = Field(default_factory=list)
    result_transform: ThinResultTransform | None = None
    response_directive: str = ""
    rationale: str = ""

    @field_validator("select_fields", "response_summary_fields", "order_by")
    @classmethod
    def validate_field_names(cls, values: list[str]) -> list[str]:
        if any(not str(value).strip() for value in values):
            raise ValueError("Field names must not be empty.")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_shape(self) -> "ThinQueryPlan":
        if self.plan_kind in {"lookup", "multi_step"} and not self.steps:
            raise ValueError(f"{self.plan_kind} plans require at least one execution step.")
        if self.plan_kind == "function_import" and not self.function_parameters:
            raise ValueError("function_import plans require function_parameters.")
        if self.plan_kind not in {"lookup", "multi_step"} and self.steps:
            raise ValueError("Execution steps are allowed only for lookup or multi_step plans.")
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Execution step ids must be unique.")
        return self

    def to_domain(self) -> QueryPlan:
        selected = list(dict.fromkeys([*self.select_fields, *self.response_summary_fields]))
        return QueryPlan(
            service_name=self.service_name,
            entity_set=self.entity_set,
            http_method=self.http_method,
            select_fields=selected,
            response_summary_fields=list(self.response_summary_fields),
            filters=[item.to_domain() for item in self.filters],
            order_by=list(self.order_by),
            top=self.top,
            payload=None,
            requires_confirmation=False,
            response_directive=self.response_directive,
            rationale=self.rationale,
            plan_kind=self.plan_kind,
            anchor_object=self.anchor_object,
            anchor_value=self.anchor_value,
            target_field=self.target_field,
            target_entity_set=self.target_entity_set,
            path_id=self.path_id,
            steps=[step.to_domain() for step in self.steps],
            function_parameters=[item.to_domain() for item in self.function_parameters],
            result_transform=self.result_transform.to_domain() if self.result_transform else None,
        )


class RuntimeCatalogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str = ""
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class RuntimeSchemaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    service_name: str = Field(min_length=1)
    entity_sets: list[str] = Field(default_factory=list)
    query: str = ""
    include_fields: bool = True
    max_fields: int = Field(default=500, ge=1, le=5000)


class RuntimeGuidanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    user_input: str = Field(min_length=1)
    service_names: list[str] = Field(default_factory=list)
    max_feedback_memories: int = Field(default=5, ge=0, le=20)


class RuntimePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    plan: ThinQueryPlan
    user_input: str = ""
    conversation_id: str | None = None


class RuntimeGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    service_name: str = Field(min_length=1)
    resource_path: str = Field(min_length=1)
    query_options: dict[str, str] = Field(default_factory=dict)
    function_parameters: dict[str, str] = Field(default_factory=dict)
    user_input: str = ""
    conversation_id: str | None = None


class RuntimePageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    case_id: str = Field(min_length=1)
    skip: int = Field(default=0, ge=0)


class RuntimeFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    case_id: str = Field(min_length=1)
    status: Literal["correct", "incorrect"]
    comment: str = ""
    expected_result: str = ""


def validation_issue_payload(code: str, message: str, field: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "severity": "error", "message": message}
    if field:
        payload["field"] = field
    return payload
