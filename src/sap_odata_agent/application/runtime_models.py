from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sap_odata_agent.domain.models import (
    AggregateMetric,
    ExecutionStep,
    FilterCondition,
    FunctionParameter,
    OutputContract,
    QueryPlan,
    ResultTransform,
    StepBinding,
)


FilterOperator = Literal["eq", "ne", "gt", "ge", "lt", "le", "contains", "in"]
PlanKind = Literal["direct", "lookup", "multi_step", "function_import"]


class RuntimeFilter(BaseModel):
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


class RuntimeFunctionParameter(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)
    value: str
    value_type: str = "string"

    def to_domain(self) -> FunctionParameter:
        return FunctionParameter(name=self.name, value=self.value, value_type=self.value_type)


class RuntimeStepBinding(BaseModel):
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


class RuntimeExecutionStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    step_id: str = Field(min_length=1)
    entity_set: str = Field(min_length=1)
    service_name: str | None = None
    http_method: Literal["GET"] = "GET"
    select_fields: list[str] = Field(default_factory=list)
    response_summary_fields: list[str] = Field(default_factory=list)
    filters: list[RuntimeFilter] = Field(default_factory=list)
    filter_from_previous: list[RuntimeStepBinding] = Field(default_factory=list)
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


class RuntimeAggregateMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation: Literal["count", "count_distinct", "sum", "sum_abs"]
    output_field: str = Field(min_length=1)
    field: str | None = Field(default=None, min_length=1)
    distinct_fields: list[str] = Field(default_factory=list)
    currency_field: str | None = Field(default=None, min_length=1)

    @field_validator("distinct_fields")
    @classmethod
    def validate_distinct_fields(cls, values: list[str]) -> list[str]:
        if any(not str(value).strip() for value in values):
            raise ValueError("Distinct field names must not be empty.")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_metric_shape(self) -> "RuntimeAggregateMetric":
        if self.operation == "count":
            if self.field or self.distinct_fields or self.currency_field:
                raise ValueError("count accepts only output_field.")
        elif self.operation == "count_distinct":
            if not self.distinct_fields:
                raise ValueError("count_distinct requires distinct_fields.")
            if self.field or self.currency_field:
                raise ValueError("count_distinct does not accept field or currency_field.")
        elif not self.field:
            raise ValueError(f"{self.operation} requires field.")
        elif self.distinct_fields:
            raise ValueError(f"{self.operation} does not accept distinct_fields.")
        return self

    def to_domain(self) -> AggregateMetric:
        return AggregateMetric(
            operation=self.operation,
            output_field=self.output_field,
            field=self.field,
            distinct_fields=list(self.distinct_fields),
            currency_field=self.currency_field,
        )


class RuntimeResultTransform(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["aggregate"]
    group_by: list[str] = Field(default_factory=list)
    sum_fields: list[str] = Field(default_factory=list)
    metrics: list[RuntimeAggregateMetric] = Field(default_factory=list)
    deduplicate_by: list[str] = Field(default_factory=list)

    @field_validator("group_by", "sum_fields", "deduplicate_by")
    @classmethod
    def validate_transform_fields(cls, values: list[str]) -> list[str]:
        if any(not str(value).strip() for value in values):
            raise ValueError("Aggregate field names must not be empty.")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def require_transform_fields(self) -> "RuntimeResultTransform":
        if not self.group_by and not self.sum_fields and not self.metrics:
            raise ValueError("An aggregate transform requires group_by, sum_fields, or metrics.")
        output_fields = [metric.output_field for metric in self.metrics]
        if len(output_fields) != len(set(output_fields)):
            raise ValueError("Aggregate metric output_field values must be unique.")
        collisions = sorted(set(output_fields).intersection(self.group_by))
        if collisions:
            raise ValueError("Aggregate metric output fields collide with group_by fields: " + ", ".join(collisions))
        return self

    def to_domain(self) -> ResultTransform:
        return ResultTransform(
            type=self.type,
            group_by=list(dict.fromkeys(self.group_by)),
            sum_fields=list(dict.fromkeys(self.sum_fields)),
            metrics=[metric.to_domain() for metric in self.metrics],
            deduplicate_by=list(dict.fromkeys(self.deduplicate_by)),
        )


class RuntimeOutputContract(BaseModel):
    """Codex-authored, schema-validated selection of fields visible to the user."""

    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["explicit", "inferred"] = "inferred"
    display_grain: str = ""
    requested_fields: list[str] = Field(default_factory=list)
    display_fields: list[str] = Field(min_length=1)
    support_fields: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @field_validator("requested_fields", "display_fields", "support_fields")
    @classmethod
    def validate_contract_fields(cls, values: list[str]) -> list[str]:
        if any(not str(value).strip() for value in values):
            raise ValueError("Output contract field names must not be empty.")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_contract_shape(self) -> "RuntimeOutputContract":
        if self.mode == "explicit":
            if not self.requested_fields:
                raise ValueError("Explicit output contracts require requested_fields.")
            if self.requested_fields != self.display_fields:
                raise ValueError(
                    "Explicit output contracts must display exactly the requested_fields in the same order."
                )
        return self

    def to_domain(self) -> OutputContract:
        return OutputContract(
            mode=self.mode,
            display_grain=self.display_grain,
            requested_fields=list(self.requested_fields),
            display_fields=list(self.display_fields),
            support_fields=list(self.support_fields),
            reason=self.reason,
        )


class RuntimeQueryPlan(BaseModel):
    """Strict Codex-authored plan accepted by the read-only SAPClaw Runtime."""

    model_config = ConfigDict(extra="forbid", strict=True)

    service_name: str = Field(min_length=1)
    entity_set: str = Field(min_length=1)
    http_method: Literal["GET"] = "GET"
    select_fields: list[str] = Field(default_factory=list)
    response_summary_fields: list[str] = Field(default_factory=list)
    filters: list[RuntimeFilter] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    top: int | None = Field(default=None, ge=1)
    plan_kind: PlanKind = "direct"
    target_entity_set: str | None = None
    anchor_object: str | None = None
    anchor_value: str | None = None
    target_field: str | None = None
    path_id: str | None = None
    steps: list[RuntimeExecutionStep] = Field(default_factory=list)
    function_parameters: list[RuntimeFunctionParameter] = Field(default_factory=list)
    result_transform: RuntimeResultTransform | None = None
    output_contract: RuntimeOutputContract | None = None
    response_directive: str = ""
    rationale: str = ""

    @field_validator("select_fields", "response_summary_fields", "order_by")
    @classmethod
    def validate_field_names(cls, values: list[str]) -> list[str]:
        if any(not str(value).strip() for value in values):
            raise ValueError("Field names must not be empty.")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_shape(self) -> "RuntimeQueryPlan":
        if self.plan_kind in {"lookup", "multi_step"} and not self.steps:
            raise ValueError(f"{self.plan_kind} plans require at least one execution step.")
        if self.plan_kind == "function_import" and not self.function_parameters:
            raise ValueError("function_import plans require function_parameters.")
        if self.plan_kind not in {"lookup", "multi_step"} and self.steps:
            raise ValueError("Execution steps are allowed only for lookup or multi_step plans.")
        if self.result_transform is not None and self.top is not None:
            raise ValueError("Aggregate plans must leave top unset so the source can be proven complete.")
        aggregate_step_tops = [step.step_id for step in self.steps if self.result_transform is not None and step.top]
        if aggregate_step_tops:
            raise ValueError(
                "Aggregate plans must leave top unset on every execution step: "
                + ", ".join(aggregate_step_tops)
            )
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Execution step ids must be unique.")
        if self.output_contract and self.result_transform:
            transform_fields = (
                set(self.result_transform.group_by)
                | set(self.result_transform.sum_fields)
                | {metric.output_field for metric in self.result_transform.metrics}
            )
            missing = [field for field in self.output_contract.display_fields if field not in transform_fields]
            if missing:
                raise ValueError(
                    "Aggregate output contracts may display only group_by fields or aggregate outputs: "
                    + ", ".join(missing)
                )
        return self

    def to_domain(self) -> QueryPlan:
        output_contract = self.output_contract.to_domain() if self.output_contract else None
        display_fields = (
            list(output_contract.display_fields)
            if output_contract is not None
            else list(self.response_summary_fields)
        )
        support_fields = list(output_contract.support_fields) if output_contract is not None else []
        derived_fields = (
            {metric.output_field for metric in self.result_transform.metrics}
            if self.result_transform is not None
            else set()
        )
        source_display_fields = [field for field in display_fields if field not in derived_fields]
        selected = list(dict.fromkeys([*self.select_fields, *source_display_fields, *support_fields]))
        steps = [step.to_domain() for step in self.steps]
        if output_contract is not None and steps:
            final_step = steps[-1]
            final_step.select_fields = list(
                    dict.fromkeys([*final_step.select_fields, *source_display_fields, *support_fields])
            )
            final_step.response_summary_fields = display_fields
        return QueryPlan(
            service_name=self.service_name,
            entity_set=self.entity_set,
            http_method=self.http_method,
            select_fields=selected,
            response_summary_fields=display_fields,
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
            steps=steps,
            function_parameters=[item.to_domain() for item in self.function_parameters],
            result_transform=self.result_transform.to_domain() if self.result_transform else None,
            output_contract=output_contract,
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

    plan: RuntimeQueryPlan
    user_input: str = ""
    conversation_id: str | None = None
    resume_case_id: str | None = None


class RuntimeGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    service_name: str = Field(min_length=1)
    resource_path: str = Field(min_length=1)
    query_options: dict[str, str] = Field(default_factory=dict)
    function_parameters: dict[str, str] = Field(default_factory=dict)
    output_contract: RuntimeOutputContract | None = None
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
