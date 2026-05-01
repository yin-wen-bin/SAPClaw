from __future__ import annotations

from sap_odata_agent.application.llm_plan_critic import LlmPlanCritic
from sap_odata_agent.domain.models import AgentRequest, ApiRouteDecision, QueryConstraints, QueryPlan, QueryShape, SelectedApi
from sap_odata_agent.infrastructure.llm.api_specific_planner import LlmApiSpecificPlanner
from sap_odata_agent.infrastructure.llm.plan_repairer import LlmPlanRepairer
from sap_odata_agent.infrastructure.llm.prompts import (
    API_ROUTER_TASK_PROMPT,
    METADATA_MATCHING_TASK_PROMPT,
    QUERY_PLANNER_TASK_PROMPT,
    REPAIR_TASK_PROMPT,
)


class StaticJsonClient:
    def __init__(self, payload: dict):
        self.payload = payload

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        import json

        return json.dumps(self.payload)


def test_prompts_distinguish_output_field_lists_from_filters() -> None:
    prompts = [
        API_ROUTER_TASK_PROMPT,
        METADATA_MATCHING_TASK_PROMPT,
        QUERY_PLANNER_TASK_PROMPT,
        REPAIR_TASK_PROMPT,
        LlmApiSpecificPlanner._user_prompt(
            AgentRequest(user_input="show planned orders with issued quantity"),
            route_decision=type(
                "Route",
                (),
                {
                    "resolved_user_input": "",
                    "selected_apis": [],
                    "intent_summary": "",
                    "business_domain": "",
                    "business_object": "",
                },
            )(),
            schema_context={"service_name": "API_PLANNED_ORDERS"},
        ),
        LlmPlanRepairer._repair_user_prompt(
            AgentRequest(user_input="show planned orders with issued quantity"),
            route_decision=type("Route", (), {"resolved_user_input": ""})(),
            schema_context={"service_name": "API_PLANNED_ORDERS"},
            previous_plan=QueryPlan(service_name="API_PLANNED_ORDERS", entity_set="A_PlannedOrder"),
            attempt_number=1,
            max_attempts=3,
            failure_context={},
        ),
    ]

    for prompt in prompts:
        assert "with/include/show/display" in prompt
        assert (
            "not filters" in prompt
            or "not used as filters" in prompt
            or "not create filters" in prompt
            or "Treat them as filters only" in prompt
            or "Add filters only" in prompt
            or "Preserve those as select fields" in prompt
        )


def test_api_planner_prompt_supports_cross_service_multistep_steps() -> None:
    prompt = LlmApiSpecificPlanner._user_prompt(
        AgentRequest(user_input="query company 1710 expense accounts"),
        route_decision=type(
            "Route",
            (),
            {
                "resolved_user_input": "",
                "selected_apis": [],
                "intent_summary": "",
                "business_domain": "",
                "business_object": "",
            },
        )(),
        schema_context={
            "service_name": "API_COMPANYCODE_SRV",
            "service_names": ["API_COMPANYCODE_SRV", "API_GLACCOUNTINCHARTOFACCOUNTS_SRV"],
        },
    )

    assert "service_name" in prompt
    assert "cross-service join_hints" in prompt
    assert "every multi_step step must include service_name" in prompt


def test_api_planner_materializes_cross_service_steps_from_router_selection() -> None:
    planner = LlmApiSpecificPlanner(
        index_root="data/index",
        llm_client=StaticJsonClient(
            {
                "plan_kind": "multi_step",
                "service_name": "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
                "entity_set": "A_GLAccountInChartOfAccounts",
                "steps": [
                    {
                        "step_id": "resolve_chart",
                        "service_name": "API_COMPANYCODE_SRV",
                        "entity_set": "A_CompanyCode",
                        "select_fields": ["CompanyCode", "ChartOfAccounts"],
                        "filters": [
                            {
                                "field": "CompanyCode",
                                "operator": "eq",
                                "value": "1710",
                                "value_type": "string",
                            }
                        ],
                        "top": 1,
                    },
                    {
                        "step_id": "fetch_accounts",
                        "service_name": "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
                        "entity_set": "A_GLAccountInChartOfAccounts",
                        "select_fields": [
                            "ChartOfAccounts",
                            "GLAccount",
                            "IsBalanceSheetAccount",
                            "ProfitLossAccountType",
                        ],
                        "filters": [
                            {
                                "field": "IsBalanceSheetAccount",
                                "operator": "eq",
                                "value": "false",
                                "value_type": "Edm.Boolean",
                            }
                        ],
                        "filter_from_previous": [
                            {
                                "field": "ChartOfAccounts",
                                "source_step_id": "resolve_chart",
                                "source_field": "ChartOfAccounts",
                            }
                        ],
                        "top": 50,
                    },
                ],
                "target_entity_set": "A_GLAccountInChartOfAccounts",
                "target_fields": ["GLAccount"],
                "presentation": {"kind": "table", "reason": "list"},
                "rationale": "Cross-service chart-of-accounts bridge.",
            }
        ),
    )
    route_decision = ApiRouteDecision(
        selected_apis=[
            SelectedApi("API_COMPANYCODE_SRV", confidence=0.85),
            SelectedApi("API_GLACCOUNTINCHARTOFACCOUNTS_SRV", confidence=0.75),
        ],
        requires_multi_api=True,
    )

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询公司1710的费用类科目"),
        route_decision,
        {
            "service_name": "API_COMPANYCODE_SRV",
            "service_names": ["API_COMPANYCODE_SRV", "API_GLACCOUNTINCHARTOFACCOUNTS_SRV"],
        },
    )

    assert plan.plan_kind == "multi_step"
    assert plan.service_name == "API_GLACCOUNTINCHARTOFACCOUNTS_SRV"
    assert [step.service_name for step in plan.steps] == [
        "API_COMPANYCODE_SRV",
        "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
    ]
    assert plan.steps[1].filters[0].field == "IsBalanceSheetAccount"
    assert plan.steps[1].filters[0].value_type == "Edm.Boolean"


def test_plan_critic_requires_explicit_filter_intent_before_missing_filters() -> None:
    request = AgentRequest(
        user_input="Show planned order records with issued quantity and fixed BOM indicator",
        constraints=QueryConstraints(
            query_shape=QueryShape.LIST_QUERY,
            target_object="planned order",
            target_field_concepts=["IssuedQuantity", "PlannedOrderBOMIsFixed"],
            filter_concepts=[],
            filter_values=[],
        ),
    )
    plan = QueryPlan(
        service_name="API_PLANNED_ORDERS",
        entity_set="A_PlannedOrder",
        select_fields=["PlannedOrder", "IssuedQuantity", "PlannedOrderBOMIsFixed"],
        filters=[],
    )

    prompt = LlmPlanCritic._user_prompt(request, context=None, plan=plan, existing_findings=[], schema_research={})

    assert "field-list wording" in prompt
    assert "Report missing_filters only when" in prompt
    assert "filter_concepts\": []" in prompt
    assert "target_field_concepts" in prompt


def test_llm_plan_critic_drops_spurious_missing_filters_for_field_list_output() -> None:
    critic = LlmPlanCritic(
        llm_client=StaticJsonClient(
            {
                "pass": False,
                "findings": [
                    {
                        "code": "missing_filters",
                        "message": "The plan is missing filters for the displayed status fields.",
                        "severity": "error",
                        "blocking": True,
                    }
                ],
            }
        )
    )
    request = AgentRequest(
        user_input="Show planned order records with issued quantity and planned order bom is fixed",
        constraints=QueryConstraints(
            query_shape=QueryShape.LIST_QUERY,
            target_object="planned order",
            target_field_concepts=["IssuedQuantity", "PlannedOrderBOMIsFixed"],
        ),
    )
    plan = QueryPlan(
        service_name="API_PLANNED_ORDERS",
        entity_set="A_PlannedOrder",
        select_fields=["PlannedOrder", "IssuedQuantity", "PlannedOrderBOMIsFixed"],
        filters=[],
    )

    findings = critic.review(request, context=None, plan=plan)

    assert findings == []
