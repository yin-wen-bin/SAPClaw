from sap_odata_agent.application.orchestrator import AgentOrchestrator
from sap_odata_agent.application.llm_plan_critic import LlmPlanCritic
from sap_odata_agent.application.plan_critic import PlanCritic
from sap_odata_agent.application.planner_guardrail import PlannerGuardrail
from sap_odata_agent.application.presentation_verifier import PresentationVerifier
from sap_odata_agent.domain.models import (
    AgentRequest,
    CardinalityPolicy,
    FilterCondition,
    QueryConstraints,
    QueryPlan,
    QueryShape,
    ResultPresentation,
)


class JsonClient:
    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        import json

        return json.dumps(self.payload)


def test_guardrail_rejects_missing_required_target_field() -> None:
    request = AgentRequest(
        user_input="业务伙伴1000561的地区是哪里？",
        constraints=QueryConstraints(
            query_shape=QueryShape.SINGLE_FACT,
            cardinality=CardinalityPolicy.ONE,
            target_object="business_partner",
            target_field_concepts=["Region"],
            filter_concepts=["BusinessPartner"],
            filter_values=["1000561"],
        ),
    )
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_BusinessPartnerAddress",
        select_fields=["BusinessPartner", "District"],
        filters=[FilterCondition(field="BusinessPartner", operator="eq", value="1000561")],
    )

    decision = PlannerGuardrail().evaluate(request, plan)

    assert decision.accepted is False
    assert "required_target_field_missing:Region" in decision.reasons


def test_critic_flags_list_query_with_top_one() -> None:
    request = AgentRequest(
        user_input="销售组织1710的所有客户",
        constraints=QueryConstraints(
            query_shape=QueryShape.LIST_QUERY,
            cardinality=CardinalityPolicy.MANY,
            target_object="customer",
            filter_concepts=["SalesOrganization"],
            filter_values=["1710"],
        ),
    )
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_CustomerSalesArea",
        select_fields=["Customer", "SalesOrganization"],
        filters=[FilterCondition(field="SalesOrganization", operator="eq", value="1710")],
        top=1,
    )

    findings = PlanCritic().review(request, plan)

    assert any(item.code == "list_query_top_too_small" and item.blocking for item in findings)


def test_critic_blocks_field_list_output_fields_used_as_filters_without_filter_intent() -> None:
    request = AgentRequest(
        user_input=(
            "Show planned order records with issued quantity, planned order bom is fixed, "
            "planned order capacity is dsptchd, and planned order is convertible"
        ),
        constraints=QueryConstraints(
            query_shape=QueryShape.LIST_QUERY,
            cardinality=CardinalityPolicy.MANY,
            target_object="planned_order",
            target_field_concepts=[
                "IssuedQuantity",
                "PlannedOrderBOMIsFixed",
                "PlannedOrderCapacityIsDsptchd",
                "PlannedOrderIsConvertible",
            ],
        ),
    )
    plan = QueryPlan(
        service_name="API_PLANNED_ORDERS",
        entity_set="A_PlannedOrder",
        select_fields=[
            "PlannedOrder",
            "IssuedQuantity",
            "PlannedOrderBOMIsFixed",
            "PlannedOrderCapacityIsDsptchd",
            "PlannedOrderIsConvertible",
        ],
        filters=[
            FilterCondition(field="IssuedQuantity", operator="gt", value="0"),
            FilterCondition(field="PlannedOrderBOMIsFixed", operator="eq", value="true"),
        ],
    )

    findings = PlanCritic().review(request, plan)

    assert any(item.code == "output_field_used_as_filter" and item.blocking for item in findings)


def test_critic_allows_explicit_true_filter_for_field_list_wording() -> None:
    request = AgentRequest(
        user_input="Show only planned order records where planned order bom is fixed is true",
        constraints=QueryConstraints(
            query_shape=QueryShape.LIST_QUERY,
            cardinality=CardinalityPolicy.MANY,
            target_object="planned_order",
            target_field_concepts=["PlannedOrderBOMIsFixed"],
            filter_concepts=["PlannedOrderBOMIsFixed"],
            filter_values=["true"],
        ),
    )
    plan = QueryPlan(
        service_name="API_PLANNED_ORDERS",
        entity_set="A_PlannedOrder",
        select_fields=["PlannedOrder", "PlannedOrderBOMIsFixed"],
        filters=[FilterCondition(field="PlannedOrderBOMIsFixed", operator="eq", value="true")],
    )

    findings = PlanCritic().review(request, plan)

    assert not any(item.code == "output_field_used_as_filter" for item in findings)


def test_orchestrator_removes_output_field_filters_without_filter_intent() -> None:
    request = AgentRequest(
        user_input="Show planned indep rqmt records with plnd indep rqmt is active and requirement plan is external",
        constraints=QueryConstraints(
            query_shape=QueryShape.LIST_QUERY,
            cardinality=CardinalityPolicy.MANY,
            target_object="planned_indep_rqmt",
            target_field_concepts=["PlndIndepRqmtIsActive", "RequirementPlanIsExternal"],
        ),
    )
    plan = QueryPlan(
        service_name="API_PLND_INDEP_RQMT_SRV",
        entity_set="PlannedIndepRqmt",
        select_fields=["Product", "PlndIndepRqmtIsActive", "RequirementPlanIsExternal"],
        filters=[
            FilterCondition(field="PlndIndepRqmtIsActive", operator="eq", value="X"),
            FilterCondition(field="RequirementPlanIsExternal", operator="eq", value="true"),
        ],
    )

    repaired = AgentOrchestrator._remove_output_field_filters_without_filter_intent(request, plan)

    assert repaired.filters == []
    assert repaired.planner_diagnostics["auto_removed_output_field_filters"] == [
        "PlndIndepRqmtIsActive",
        "RequirementPlanIsExternal",
    ]


def test_orchestrator_removes_unmentioned_filter_values_for_field_list_request() -> None:
    request = AgentRequest(
        user_input="Show planned indep rqmt records with plnd indep rqmt is active and requirement plan is external",
        constraints=QueryConstraints(query_shape=QueryShape.LIST_QUERY, target_object="planned_indep_rqmt"),
    )
    plan = QueryPlan(
        service_name="API_PLND_INDEP_RQMT_SRV",
        entity_set="PlannedIndepRqmt",
        select_fields=["Product", "Plant", "MRPArea"],
        filters=[
            FilterCondition(field="PlndIndepRqmtIsActive", operator="eq", value="X"),
            FilterCondition(field="RequirementPlanIsExternal", operator="eq", value="true"),
        ],
    )

    repaired = AgentOrchestrator._remove_output_field_filters_without_filter_intent(request, plan)

    assert repaired.filters == []


def test_field_list_detection_keeps_explicit_identifier_filters() -> None:
    request = AgentRequest(
        user_input="Show trial balance material balances for company code 1710 and ledger 0L",
        constraints=QueryConstraints(query_shape=QueryShape.LIST_QUERY, target_object="trial_balance"),
    )

    assert PlanCritic._looks_like_field_list_without_filter_intent(request) is False


def test_field_list_detection_does_not_treat_records_as_identifier() -> None:
    request = AgentRequest(
        user_input="Show sales order records with their main identifying details",
        constraints=QueryConstraints(query_shape=QueryShape.LIST_QUERY, target_object="sales_order"),
    )

    assert PlanCritic._looks_like_field_list_without_filter_intent(request) is True


def test_orchestrator_removes_placeholder_identifier_filter_for_field_list_request() -> None:
    request = AgentRequest(
        user_input="Show sales order records with their main identifying details",
        constraints=QueryConstraints(query_shape=QueryShape.LIST_QUERY, target_object="sales_order"),
    )
    plan = QueryPlan(
        service_name="API_SALES_ORDER_SRV",
        entity_set="A_SalesOrder",
        select_fields=["SalesOrder", "SalesOrderType"],
        filters=[FilterCondition(field="SalesOrder", operator="eq", value="<sales order>")],
    )

    repaired = AgentOrchestrator._remove_output_field_filters_without_filter_intent(request, plan)

    assert repaired.filters == []


def test_orchestrator_keeps_filters_when_values_are_explicitly_mentioned() -> None:
    request = AgentRequest(
        user_input="Show trial balance material balances for company code 1710 and ledger 0L",
        constraints=QueryConstraints(query_shape=QueryShape.LIST_QUERY, target_object="trial_balance"),
    )
    plan = QueryPlan(
        service_name="C_TRIALBALANCE_CDS",
        entity_set="C_TRIALBALANCEResults",
        select_fields=["Material", "CompanyCode", "Ledger"],
        filters=[
            FilterCondition(field="CompanyCode", operator="eq", value="1710"),
            FilterCondition(field="Ledger", operator="eq", value="0L"),
        ],
    )

    repaired = AgentOrchestrator._remove_output_field_filters_without_filter_intent(request, plan)

    assert [item.field for item in repaired.filters] == ["CompanyCode", "Ledger"]


def test_field_list_detection_uses_original_user_input_over_resolved_filter_rewrite() -> None:
    request = AgentRequest(
        user_input="Show planned indep rqmt records with plnd indep rqmt is active and requirement plan is external",
        resolved_user_input="Find records where active is true and requirement plan is external true",
        constraints=QueryConstraints(query_shape=QueryShape.LIST_QUERY, target_object="planned_indep_rqmt"),
    )

    assert PlanCritic._looks_like_field_list_without_filter_intent(request) is True


def test_llm_plan_critic_ignores_schema_research_only_required_fields() -> None:
    request = AgentRequest(
        user_input="List account assignments for service entry sheets",
        constraints=QueryConstraints(query_shape=QueryShape.LIST_QUERY, target_object="service_entry_sheet"),
    )
    plan = QueryPlan(
        service_name="API_SERVICE_ENTRY_SHEET_SRV",
        entity_set="A_SrvcEntrShtAcctAssignment",
        select_fields=["AccountAssignment", "ServiceEntrySheet", "ServiceEntrySheetItem"],
    )
    critic = LlmPlanCritic(
        llm_client=JsonClient(
            {
                "findings": [
                    {
                        "code": "missing_intent_fields",
                        "message": (
                            "The intent summary states the user wants fields such as OrderID, "
                            "SalesOrder, SalesOrderItem, SalesOrderScheduleLine, and GLAccount."
                        ),
                        "severity": "error",
                        "blocking": True,
                    }
                ]
            }
        ),
        enabled=True,
    )

    findings = critic.review(request, None, plan)

    assert findings == []


def test_presentation_verifier_repairs_table_count_text() -> None:
    verifier = PresentationVerifier()
    request = AgentRequest(
        user_input="城市为San Diego的供应商有哪些？",
        constraints=QueryConstraints(
            query_shape=QueryShape.SEARCH_BY_ATTRIBUTE,
            cardinality=CardinalityPolicy.MANY,
            target_object="supplier",
        ),
    )
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_BusinessPartnerAddress",
        select_fields=["Supplier", "CityName"],
        response_summary_fields=["Supplier", "CityName"],
    )
    presentation = ResultPresentation(
        kind="table",
        title="查询结果",
        text="共找到3家位于San Diego的供应商。",
        columns=["Supplier", "CityName"],
        rows=[
            {"Supplier": "17300003", "CityName": "San Diego"},
            {"Supplier": "17300016", "CityName": "San Diego"},
            {"Supplier": "17300017", "CityName": "San Diego"},
            {"Supplier": "17300273", "CityName": "San Diego"},
        ],
    )

    repaired, verification = verifier.verify_and_repair(request, plan, presentation)

    assert repaired is not None
    assert "4" in repaired.text
    assert verification.passed is False
    assert verification.issues == ["table_count_mismatch:3!=4"]


def test_presentation_verifier_repairs_empty_rows_and_filters_target_object() -> None:
    verifier = PresentationVerifier()
    request = AgentRequest(
        user_input="\u67e5\u627e\u5730\u533a\u4e3aHH\u7684\u4f9b\u5e94\u5546",
        constraints=QueryConstraints(
            query_shape=QueryShape.SEARCH_BY_ATTRIBUTE,
            cardinality=CardinalityPolicy.MANY,
            target_object="supplier",
        ),
    )
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_BusinessPartner",
        select_fields=["BusinessPartner", "Supplier", "Customer", "BusinessPartnerFullName"],
        response_summary_fields=["BusinessPartner", "Supplier", "BusinessPartnerFullName"],
    )
    presentation = ResultPresentation(
        kind="table",
        title="\u67e5\u8be2\u7ed3\u679c",
        text="\u5728\u5730\u533aHH\u5171\u67092\u4e2a\u4f9b\u5e94\u5546\u3002",
        columns=["\u4e1a\u52a1\u4f19\u4f34\u7f16\u53f7", "\u4f9b\u5e94\u5546\u7f16\u53f7", "\u5b8c\u6574\u540d\u79f0"],
        rows=[
            {"\u4e1a\u52a1\u4f19\u4f34\u7f16\u53f7": "", "\u4f9b\u5e94\u5546\u7f16\u53f7": "", "\u5b8c\u6574\u540d\u79f0": ""},
            {"\u4e1a\u52a1\u4f19\u4f34\u7f16\u53f7": "", "\u4f9b\u5e94\u5546\u7f16\u53f7": "", "\u5b8c\u6574\u540d\u79f0": ""},
        ],
    )
    data = {
        "results": [
            {"BusinessPartner": "10100006", "Supplier": "", "Customer": "10100006", "BusinessPartnerFullName": "Customer"},
            {"BusinessPartner": "10300006", "Supplier": "10300006", "Customer": "", "BusinessPartnerFullName": "Vendor A"},
            {"BusinessPartner": "10386301", "Supplier": "10386301", "Customer": "", "BusinessPartnerFullName": "Vendor B"},
        ]
    }

    repaired, verification = verifier.verify_and_repair(request, plan, presentation, data)

    assert repaired is not None
    assert repaired.columns == ["BusinessPartner", "Supplier", "Customer", "BusinessPartnerFullName"]
    assert repaired.rows == [
        {"BusinessPartner": "10300006", "Supplier": "10300006", "Customer": "", "BusinessPartnerFullName": "Vendor A"},
        {"BusinessPartner": "10386301", "Supplier": "10386301", "Customer": "", "BusinessPartnerFullName": "Vendor B"},
    ]
    assert verification.passed is False
    assert verification.issues == ["table_rows_empty_values"]


def test_guardrail_exposes_fallback_winner_from_planner_diagnostics() -> None:
    request = AgentRequest(
        user_input="供应商17300003的shipping condition是什么？",
        constraints=QueryConstraints(
            query_shape=QueryShape.SINGLE_FACT,
            cardinality=CardinalityPolicy.ONE,
            target_object="supplier",
            target_field_concepts=["ShippingCondition"],
        ),
    )
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_SupplierPurchasingOrg",
        select_fields=["Supplier", "ShippingCondition"],
        planner_diagnostics={
            "planner_winner": "fallback",
            "llm_adjudication": {
                "accepted": False,
                "reasons": ["strong_answer_field_ignored_by_llm"],
            },
        },
    )

    decision = PlannerGuardrail().evaluate(request, plan)

    assert decision.accepted is True
    assert decision.winner == "fallback"
    assert "strong_answer_field_ignored_by_llm" in decision.reasons
