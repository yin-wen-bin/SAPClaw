from sap_odata_agent.domain.models import AgentRequest, FilterCondition, QueryConstraints, QueryPlan, QueryShape
from sap_odata_agent.infrastructure.llm.result_verifier_agent import LlmResultVerifierAgent


def test_result_verifier_prompt_allows_empty_list_results() -> None:
    prompt = LlmResultVerifierAgent._user_prompt(
        request=type("Request", (), {"resolved_user_input": "", "user_input": "查询传真号码列表"})(),
        plan=type(
            "Plan",
            (),
            {
                "plan_kind": "direct",
                "entity_set": "A_AddressFaxNumber",
                "select_fields": ["AddressID", "FaxNumber"],
                "response_summary_fields": ["AddressID", "FaxNumber"],
                "filters": [],
                "steps": [],
            },
        )(),
        data={"result_count": 0, "results": []},
        schema_research={},
        schema_context_summary={},
    )

    assert "result_count=0 can be a correct answer" in prompt
    assert "Do not require enrichment identifiers" in prompt
    assert "business object name" in prompt
    assert "detail child entities" in prompt
    assert "field-list wording" in prompt


def test_result_verifier_static_passes_field_list_output_request_without_filters() -> None:
    verifier = LlmResultVerifierAgent(enabled=False)

    result = verifier.verify(
        request=AgentRequest(
            user_input=(
                "Show planned order records with issued quantity, planned order bom is fixed, "
                "planned order capacity is dsptchd, and planned order is convertible"
            ),
            constraints=QueryConstraints(
                query_shape=QueryShape.LIST_QUERY,
                target_object="planned order",
                target_field_concepts=[
                    "IssuedQuantity",
                    "PlannedOrderBOMIsFixed",
                    "PlannedOrderCapacityIsDsptchd",
                    "PlannedOrderIsConvertible",
                ],
            ),
        ),
        plan=QueryPlan(
            service_name="API_PLANNED_ORDERS",
            entity_set="A_PlannedOrder",
            select_fields=[
                "PlannedOrder",
                "IssuedQuantity",
                "PlannedOrderBOMIsFixed",
                "PlannedOrderCapacityIsDsptchd",
                "PlannedOrderIsConvertible",
            ],
            filters=[],
        ),
        data={"result_count": 317, "results": [{"PlannedOrder": "1152", "IssuedQuantity": "0"}]},
        schema_context_summary={"service_name": "API_PLANNED_ORDERS"},
    )

    assert result["passed"] is True
    assert result["source"] == "field_list_static_result_verifier"


def test_result_verifier_blocks_blank_less_specific_product_tax_classification() -> None:
    verifier = LlmResultVerifierAgent(enabled=False)
    plan = QueryPlan(
        service_name="API_PRODUCT_SRV",
        entity_set="A_ProductSales",
        select_fields=["Product", "TaxClassification"],
        response_summary_fields=["Product", "TaxClassification"],
        filters=[FilterCondition(field="Product", operator="eq", value="TG0011")],
    )
    schema_context_summary = {
        "service_name": "API_PRODUCT_SRV",
        "api_skill": {
            "service_name": "API_PRODUCT_SRV",
            "summary": (
                "Prefer A_ProductSalesTax.Product, A_ProductSalesTax.Country, "
                "A_ProductSalesTax.TaxCategory, and A_ProductSalesTax.TaxClassification. "
                "A_ProductSales.TaxClassification is not sufficient evidence."
            ),
        },
        "available_fields": [
            {"entity_set": "A_ProductSalesTax", "field_name": "Product", "data_type": "Edm.String"},
            {"entity_set": "A_ProductSalesTax", "field_name": "Country", "data_type": "Edm.String"},
            {"entity_set": "A_ProductSalesTax", "field_name": "TaxCategory", "data_type": "Edm.String"},
            {"entity_set": "A_ProductSalesTax", "field_name": "TaxClassification", "data_type": "Edm.String"},
            {"entity_set": "A_ProductSales", "field_name": "TaxClassification", "data_type": "Edm.String"},
        ],
    }

    result = verifier.verify(
        request=AgentRequest(user_input="\u67e5\u8be2\u7269\u6599TG0011\u7684\u7a0e\u5206\u7c7b"),
        plan=plan,
        data={"result_count": 1, "results": [{"Product": "TG0011", "TaxClassification": ""}]},
        schema_context_summary=schema_context_summary,
    )

    assert result["passed"] is False
    assert result["issues"][0]["code"] == "wrong_business_level_for_tax_classification"
    assert result["repair_hints"]["preferred_entity_set"] == "A_ProductSalesTax"
    assert result["repair_hints"]["preferred_select_fields"] == [
        "Product",
        "Country",
        "TaxCategory",
        "TaxClassification",
    ]
    assert result["repair_hints"]["preferred_filters"] == [
        {
            "entity_set": "A_ProductSalesTax",
            "field": "Product",
            "operator": "eq",
            "value": "TG0011",
            "value_type": "string",
        }
    ]


def test_result_verifier_allows_filled_product_sales_tax_classification() -> None:
    verifier = LlmResultVerifierAgent(enabled=False)
    result = verifier.verify(
        request=AgentRequest(user_input="\u67e5\u8be2\u7269\u6599TG0011\u7684\u7a0e\u5206\u7c7b"),
        plan=QueryPlan(
            service_name="API_PRODUCT_SRV",
            entity_set="A_ProductSales",
            select_fields=["Product", "TaxClassification"],
            filters=[FilterCondition(field="Product", operator="eq", value="TG0011")],
        ),
        data={"result_count": 1, "results": [{"Product": "TG0011", "TaxClassification": "1"}]},
        schema_context_summary={
            "api_skill": {
                "summary": "A_ProductSalesTax.TaxClassification; A_ProductSales.TaxClassification"
            },
            "available_fields": [
                {"entity_set": "A_ProductSalesTax", "field_name": "Product"},
                {"entity_set": "A_ProductSalesTax", "field_name": "Country"},
                {"entity_set": "A_ProductSalesTax", "field_name": "TaxCategory"},
                {"entity_set": "A_ProductSalesTax", "field_name": "TaxClassification"},
            ],
        },
    )

    assert result["passed"] is True


def test_result_verifier_blocks_purchase_order_history_answered_by_pricing_only() -> None:
    verifier = LlmResultVerifierAgent(enabled=False)
    plan = QueryPlan(
        service_name="API_PURCHASEORDER_PROCESS_SRV",
        entity_set="A_PurOrdPricingElement",
        plan_kind="multi_step",
        select_fields=["PurchaseOrder", "PurchaseOrderItem", "ConditionType", "ConditionRateValue"],
        filters=[FilterCondition(field="PurchaseOrder", operator="eq", value="4500001513")],
    )

    result = verifier.verify(
        request=AgentRequest(
            user_input="\u67e5\u8be2\u91c7\u8d2d\u8ba2\u53554500001513\u7684\u91c7\u8d2d\u8ba2\u5355\u5386\u53f2\u8bb0\u5f55"
        ),
        plan=plan,
        data={
            "result_count": 2,
            "results": [
                {
                    "PurchaseOrder": "4500001513",
                    "PurchaseOrderItem": "10",
                    "ConditionType": "PBXX",
                    "ConditionRateValue": "10.000000000",
                }
            ],
            "execution_trace": [
                {
                    "step_id": "step_pricing",
                    "entity_set": "A_PurOrdPricingElement",
                    "success": True,
                }
            ],
        },
        schema_context_summary={"service_name": "API_PURCHASEORDER_PROCESS_SRV"},
    )

    assert result["passed"] is False
    assert result["issues"][0]["code"] == "wrong_business_level_for_purchase_order_history"
    assert result["repair_hints"]["rejected_entity_set"] == "A_PurOrdPricingElement"


def test_result_verifier_allows_purchase_order_history_when_user_asks_for_pricing() -> None:
    verifier = LlmResultVerifierAgent(enabled=False)

    result = verifier.verify(
        request=AgentRequest(
            user_input="\u67e5\u8be2\u91c7\u8d2d\u8ba2\u53554500001513\u7684\u5b9a\u4ef7\u5386\u53f2"
        ),
        plan=QueryPlan(
            service_name="API_PURCHASEORDER_PROCESS_SRV",
            entity_set="A_PurOrdPricingElement",
            select_fields=["PurchaseOrder", "ConditionType"],
        ),
        data={
            "result_count": 1,
            "results": [{"PurchaseOrder": "4500001513", "ConditionType": "PBXX"}],
        },
        schema_context_summary={"service_name": "API_PURCHASEORDER_PROCESS_SRV"},
    )

    assert result["passed"] is True
