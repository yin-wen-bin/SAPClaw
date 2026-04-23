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
