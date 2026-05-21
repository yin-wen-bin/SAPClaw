from __future__ import annotations

import json

from sap_odata_agent.application.llm_plan_critic import LlmPlanCritic
from sap_odata_agent.domain.models import (
    AgentRequest,
    ApiRouteDecision,
    ExecutionStep,
    FilterCondition,
    QueryConstraints,
    QueryPlan,
    QueryShape,
    SelectedApi,
    StepBinding,
)
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


def test_api_router_prompt_distinguishes_company_chart_attribute_from_gl_accounts() -> None:
    assert "company code's chart of accounts" in API_ROUTER_TASK_PROMPT
    assert "company code API" in API_ROUTER_TASK_PROMPT
    assert "G/L account API" in API_ROUTER_TASK_PROMPT


def test_api_router_prompt_prefers_target_document_api_for_source_references() -> None:
    assert "target documents related to a source document" in API_ROUTER_TASK_PROMPT
    assert "delivery documents for sales order 3773" in API_ROUTER_TASK_PROMPT
    assert "outbound delivery API" in API_ROUTER_TASK_PROMPT
    assert "OrderID or ReferenceSDDocument" in API_ROUTER_TASK_PROMPT


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


def test_api_planner_prompt_asks_llm_to_choose_basic_profile_fields() -> None:
    prompt = LlmApiSpecificPlanner._user_prompt(
        AgentRequest(user_input="查询供应商17300003的基本信息"),
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
        schema_context={"service_name": "API_BUSINESS_PARTNER"},
    )

    assert "basic information/profile/detail/overview" in QUERY_PLANNER_TASK_PROMPT
    assert "actively choose the most business-relevant select_fields" in prompt
    assert "Do not blindly copy default_select_fields" in METADATA_MATCHING_TASK_PROMPT
    assert "Avoid returning mainly block flags" in prompt


def test_api_planner_prompt_omits_function_imports_for_plain_read_queries() -> None:
    route_decision = ApiRouteDecision(
        selected_apis=[SelectedApi("API_OUTBOUND_DELIVERY_SRV", confidence=0.9)],
        requires_multi_api=False,
    )
    prompt = LlmApiSpecificPlanner._user_prompt(
        AgentRequest(user_input="query delivered but not billed deliveries"),
        route_decision=route_decision,
        schema_context={
            "service_name": "API_OUTBOUND_DELIVERY_SRV",
            "service_names": ["API_OUTBOUND_DELIVERY_SRV"],
            "entities": [
                {
                    "service_name": "API_OUTBOUND_DELIVERY_SRV",
                    "entity_set": "A_OutbDeliveryHeader",
                    "fields": [
                        {
                            "entity_set": "A_OutbDeliveryHeader",
                            "field_name": "OverallDelivReltdBillgStatus",
                            "label": "Billing Status",
                            "data_type": "Edm.String",
                            "filterable": True,
                        }
                    ],
                }
            ],
            "function_imports": [
                {
                    "name": "MutatingAction",
                    "parameters": [{"name": "DeliveryDocument", "data_type": "Edm.String"}],
                    "return_fields": [{"field_name": f"Field{index}"} for index in range(100)],
                }
            ],
            "api_skill": {
                "service_name": "API_OUTBOUND_DELIVERY_SRV",
                "summary": "Use delivery billing status for delivered but not billed lists.",
                "content": "x" * 10000,
            },
        },
    )

    payload = json.loads(prompt.split("Input:\n", 1)[1].split("\n\nPlanning rules", 1)[0])
    prompt_context = payload["schema_context"]

    assert "function_imports" not in prompt_context
    assert "content" not in prompt_context["api_skill"]
    assert len(prompt) < 25000


def test_api_planner_prompt_keeps_function_imports_for_availability_queries() -> None:
    route_decision = ApiRouteDecision(
        selected_apis=[SelectedApi("API_PRODUCT_AVAILY_INFO_BASIC", confidence=0.9)],
        requires_multi_api=False,
    )
    prompt = LlmApiSpecificPlanner._user_prompt(
        AgentRequest(user_input="查询物料TG0011在工厂1710今天是否有货"),
        route_decision=route_decision,
        schema_context={
            "service_name": "API_PRODUCT_AVAILY_INFO_BASIC",
            "service_names": ["API_PRODUCT_AVAILY_INFO_BASIC"],
            "entities": [{"entity_set": "DetermineAvailabilityAt", "kind": "function_import"}],
            "function_imports": [
                {
                    "name": "DetermineAvailabilityAt",
                    "parameters": [
                        {"name": "Product", "data_type": "Edm.String", "value_type": "string", "required": True},
                        {"name": "Plant", "data_type": "Edm.String", "value_type": "string", "required": True},
                    ],
                    "return_type": "Availability",
                }
            ],
        },
    )

    payload = json.loads(prompt.split("Input:\n", 1)[1].split("\n\nPlanning rules", 1)[0])

    assert payload["schema_context"]["function_imports"][0]["name"] == "DetermineAvailabilityAt"


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
    assert "same natural language as user_input" in prompt


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


def test_llm_plan_critic_localizes_english_blocking_message_for_chinese_request() -> None:
    critic = LlmPlanCritic(
        llm_client=StaticJsonClient(
            {
                "pass": False,
                "findings": [
                    {
                        "code": "wrong_field_semantics",
                        "message": "The plan uses an empty string as filter value.",
                        "severity": "error",
                        "blocking": True,
                    }
                ],
            }
        )
    )
    request = AgentRequest(user_input="\u67e5\u8be2\u5de5\u53821710\u4e0b\uff0c\u6240\u6709\u672a\u786e\u8ba4\u7684\u751f\u4ea7\u8ba2\u5355")
    plan = QueryPlan(
        service_name="API_PRODUCTION_ORDER_2_SRV",
        entity_set="A_ProductionOrder_2",
        select_fields=["ManufacturingOrder", "ProductionPlant", "OrderIsConfirmed"],
        filters=[],
    )

    findings = critic.review(request, context=None, plan=plan)

    assert len(findings) == 1
    assert findings[0].message.startswith("\u8ba1\u5212\u8bc4\u5ba1\u672a\u901a\u8fc7")
    assert "The plan uses" not in findings[0].message


def test_llm_plan_critic_drops_unrequested_name_field_requirement() -> None:
    critic = LlmPlanCritic(
        llm_client=StaticJsonClient(
            {
                "pass": False,
                "findings": [
                    {
                        "code": "wrong_field_semantics",
                        "message": "The plan selects GLAccount but should select G/L account name fields.",
                        "severity": "error",
                        "blocking": True,
                    }
                ],
            }
        )
    )
    request = AgentRequest(user_input="查询公司1710的运营会计凭证项目")
    plan = QueryPlan(
        service_name="API_OPLACCTGDOCITEMCUBE_SRV",
        entity_set="A_OperationalAcctgDocItemCube",
        select_fields=["CompanyCode", "AccountingDocument", "GLAccount"],
        filters=[],
    )

    findings = critic.review(request, context=None, plan=plan)

    assert findings == []


def test_llm_plan_critic_accepts_supplier_to_business_partner_address_binding() -> None:
    critic = LlmPlanCritic(
        llm_client=StaticJsonClient(
            {
                "pass": False,
                "findings": [
                    {
                        "code": "wrong_field_semantics",
                        "message": (
                            "Supplier from A_Supplier is bound to BusinessPartner on "
                            "A_BusinessPartnerAddress, and the fields have different semantics."
                        ),
                        "severity": "error",
                        "blocking": True,
                    }
                ],
            }
        )
    )
    plan = QueryPlan(
        service_name="API_BUSINESS_PARTNER",
        entity_set="A_BusinessPartnerAddress",
        select_fields=["BusinessPartner", "AddressID", "CityName"],
        response_summary_fields=["BusinessPartner", "CityName"],
        filters=[],
        plan_kind="multi_step",
        target_entity_set="A_BusinessPartnerAddress",
        steps=[
            ExecutionStep(
                step_id="step_1",
                service_name="API_BUSINESS_PARTNER",
                entity_set="A_Supplier",
                select_fields=["Supplier", "SupplierName"],
                filters=[FilterCondition(field="Supplier", operator="eq", value="17300003")],
            ),
            ExecutionStep(
                step_id="step_2",
                service_name="API_BUSINESS_PARTNER",
                entity_set="A_BusinessPartnerAddress",
                select_fields=["BusinessPartner", "AddressID", "CityName"],
                filter_from_previous=[
                    StepBinding(field="BusinessPartner", source_step_id="step_1", source_field="Supplier")
                ],
            ),
        ],
    )

    findings = critic.review(
        AgentRequest(user_input="\u4f9b\u5e94\u554617300003\u7684\u57ce\u5e02\u662f\u4ec0\u4e48"),
        context=None,
        plan=plan,
    )

    assert findings == []


def test_llm_plan_critic_drops_unrequested_date_and_debit_credit_requirement() -> None:
    critic = LlmPlanCritic(
        llm_client=StaticJsonClient(
            {
                "pass": False,
                "findings": [
                    {
                        "code": "missing_critical_fields",
                        "message": "The plan is missing PostingDate and DebitCreditIndicator fields.",
                        "severity": "error",
                        "blocking": True,
                    }
                ],
            }
        )
    )
    request = AgentRequest(user_input="查询公司1710中科目10010000的日记账行项目")
    plan = QueryPlan(
        service_name="API_JOURNALENTRYITEMBASIC_SRV",
        entity_set="A_JournalEntryItemBasic",
        select_fields=["ID", "CompanyCode", "GLAccount"],
        filters=[],
    )

    findings = critic.review(request, context=None, plan=plan)

    assert findings == []
