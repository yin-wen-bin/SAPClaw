from __future__ import annotations

import json
from pathlib import Path

from sap_odata_agent.application.schema_feasibility_validator import SchemaFeasibilityValidator
from sap_odata_agent.domain.models import AgentRequest, ApiRouteDecision, FilterCondition, QueryPlan, SelectedApi
from sap_odata_agent.infrastructure.llm.api_specific_planner import LlmApiSpecificPlanner


class StaticJsonClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete_json(self, *_args, **_kwargs) -> str:
        return json.dumps(self.payload)


def _write_boolean_index(root: Path) -> None:
    service_dir = root / "API_TEST_ORDER"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps([{"service_name": "API_TEST_ORDER", "entity_sets": ["A_Order"]}]),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST_ORDER",
                    "entity_set": "A_Order",
                    "key_fields": ["OrderID"],
                    "default_select_fields": ["OrderID", "Plant", "OrderIsReleased", "OrderIsConfirmed"],
                    "supported_methods": ["GET"],
                }
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "fields.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST_ORDER",
                    "entity_set": "A_Order",
                    "field_name": "OrderID",
                    "filterable": True,
                    "data_type": "Edm.String",
                },
                {
                    "service_name": "API_TEST_ORDER",
                    "entity_set": "A_Order",
                    "field_name": "Plant",
                    "filterable": True,
                    "data_type": "Edm.String",
                },
                {
                    "service_name": "API_TEST_ORDER",
                    "entity_set": "A_Order",
                    "field_name": "OrderIsReleased",
                    "filterable": True,
                    "data_type": "Edm.Boolean",
                },
                {
                    "service_name": "API_TEST_ORDER",
                    "entity_set": "A_Order",
                    "field_name": "OrderIsConfirmed",
                    "filterable": True,
                    "data_type": "Edm.String",
                },
            ]
        ),
        encoding="utf-8",
    )
    for filename in ("relations.json", "entity_graph.json", "lookup_paths.json", "business_terms.json"):
        (service_dir / filename).write_text("[]", encoding="utf-8")


def _schema_context() -> dict:
    fields = [
        {
            "service_name": "API_TEST_ORDER",
            "entity_set": "A_Order",
            "field_name": "OrderID",
            "filterable": True,
            "data_type": "Edm.String",
        },
        {
            "service_name": "API_TEST_ORDER",
            "entity_set": "A_Order",
            "field_name": "Plant",
            "filterable": True,
            "data_type": "Edm.String",
        },
        {
            "service_name": "API_TEST_ORDER",
            "entity_set": "A_Order",
            "field_name": "OrderIsReleased",
            "filterable": True,
            "data_type": "Edm.Boolean",
        },
        {
            "service_name": "API_TEST_ORDER",
            "entity_set": "A_Order",
            "field_name": "OrderIsConfirmed",
            "filterable": True,
            "data_type": "Edm.String",
        },
    ]
    return {
        "service_name": "API_TEST_ORDER",
        "entities": [{"service_name": "API_TEST_ORDER", "entity_set": "A_Order", "fields": fields}],
        "candidate_fields": fields,
    }


def test_api_specific_planner_normalizes_negative_boolean_empty_filter(tmp_path: Path) -> None:
    _write_boolean_index(tmp_path)
    planner = LlmApiSpecificPlanner(
        index_root=tmp_path,
        llm_client=StaticJsonClient(
            {
                "plan_kind": "direct",
                "service_name": "API_TEST_ORDER",
                "entity_set": "A_Order",
                "select_fields": ["OrderID", "Plant", "OrderIsReleased", "OrderIsConfirmed"],
                "response_summary_fields": ["OrderID", "Plant", "OrderIsReleased", "OrderIsConfirmed"],
                "filters": [
                    {"field": "Plant", "operator": "eq", "value": "1710", "value_type": "Edm.String"},
                    {"field": "OrderIsReleased", "operator": "eq", "value": "", "value_type": "Edm.Boolean"},
                    {"field": "OrderIsConfirmed", "operator": "eq", "value": "", "value_type": "Edm.String"},
                ],
                "presentation": {"kind": "table"},
            }
        ),
    )

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询工厂1710下所有未下达的生产订单"),
        ApiRouteDecision(selected_apis=[SelectedApi("API_TEST_ORDER")]),
        _schema_context(),
    )

    values = {condition.field: condition.value for condition in plan.filters}
    assert values["OrderIsReleased"] == "false"
    assert values["OrderIsConfirmed"] == ""
    assert plan.planner_diagnostics["normalized_boolean_empty_filters"][0]["field"] == "OrderIsReleased"


def test_schema_feasibility_blocks_boolean_empty_filter_but_allows_string_indicator(tmp_path: Path) -> None:
    _write_boolean_index(tmp_path)
    validator = SchemaFeasibilityValidator(index_root=tmp_path, service_name="API_TEST_ORDER")

    invalid_result = validator.validate(
        AgentRequest(user_input="query unreleased orders"),
        QueryPlan(
            service_name="API_TEST_ORDER",
            entity_set="A_Order",
            select_fields=["OrderID", "OrderIsReleased"],
            filters=[FilterCondition(field="OrderIsReleased", operator="eq", value="", value_type="Edm.Boolean")],
        ),
    )
    valid_result = validator.validate(
        AgentRequest(user_input="query unconfirmed orders"),
        QueryPlan(
            service_name="API_TEST_ORDER",
            entity_set="A_Order",
            select_fields=["OrderID", "OrderIsConfirmed"],
            filters=[FilterCondition(field="OrderIsConfirmed", operator="eq", value="", value_type="Edm.String")],
        ),
    )

    assert any(violation.code == "boolean_filter_empty_value" for violation in invalid_result.violations)
    assert valid_result.passed is True
