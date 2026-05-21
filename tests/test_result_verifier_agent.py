from sap_odata_agent.domain.models import AgentRequest, FilterCondition, QueryConstraints, QueryPlan, QueryShape, ResultTransform
from sap_odata_agent.infrastructure.llm.result_verifier_agent import LlmResultVerifierAgent


class StaticJsonClient:
    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        import json

        return json.dumps(self.payload)


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
    assert "same natural language as user_input" in prompt


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


def test_result_verifier_accepts_unconfirmed_production_order_empty_string_indicator() -> None:
    verifier = LlmResultVerifierAgent(enabled=False)

    result = verifier.verify(
        request=AgentRequest(user_input="\u67e5\u8be2\u5de5\u53821710\u4e0b\uff0c\u6240\u6709\u672a\u786e\u8ba4\u7684\u751f\u4ea7\u8ba2\u5355"),
        plan=QueryPlan(
            service_name="API_PRODUCTION_ORDER_2_SRV",
            entity_set="A_ProductionOrder_2",
            select_fields=["ManufacturingOrder", "ProductionPlant", "OrderIsConfirmed"],
            filters=[
                FilterCondition(field="ProductionPlant", operator="eq", value="1710"),
                FilterCondition(field="OrderIsConfirmed", operator="eq", value=""),
            ],
        ),
        data={
            "result_count": 1,
            "results": [
                {
                    "ManufacturingOrder": "1000000",
                    "ProductionPlant": "1710",
                    "OrderIsConfirmed": "",
                }
            ],
        },
        schema_context_summary={"service_name": "API_PRODUCTION_ORDER_2_SRV"},
    )

    assert result["passed"] is True
    assert result["source"] == "skill_grounded_result_verifier"


def test_result_verifier_localizes_english_issue_for_chinese_request() -> None:
    result = LlmResultVerifierAgent._materialize(
        {
            "passed": False,
            "issues": [
                {
                    "code": "invalid_filter_value",
                    "message": "The plan uses an empty string as filter value.",
                    "blocking": True,
                }
            ],
            "repair_hints": {
                "reason": "Use a valid status indicator.",
                "preferred_filters": [],
            },
        },
        {},
        AgentRequest(user_input="\u67e5\u8be2\u5de5\u53821710\u4e0b\uff0c\u6240\u6709\u672a\u786e\u8ba4\u7684\u751f\u4ea7\u8ba2\u5355"),
    )

    assert result["passed"] is False
    assert result["issues"][0]["message"].startswith("\u7ed3\u679c\u6821\u9a8c\u672a\u901a\u8fc7")
    assert "The plan uses" not in result["issues"][0]["message"]
    assert result["repair_hints"]["reason"].startswith("\u8bf7\u4f7f\u7528")


def test_result_verifier_drops_unrequested_document_date_and_debit_credit_fields() -> None:
    verifier = LlmResultVerifierAgent(
        llm_client=StaticJsonClient(
            {
                "passed": False,
                "issues": [
                    {
                        "code": "missing_required_fields",
                        "message": "The result omitted AccountingDocument, PostingDate, and DebitCreditIndicator.",
                        "blocking": True,
                    }
                ],
                "repair_hints": {},
            }
        )
    )

    result = verifier.verify(
        request=AgentRequest(user_input="查询公司1710中科目10010000的日记账行项目"),
        plan=QueryPlan(
            service_name="API_JOURNALENTRYITEMBASIC_SRV",
            entity_set="A_JournalEntryItemBasic",
            select_fields=["ID", "CompanyCode", "GLAccount", "AmountInCompanyCodeCurrency"],
            filters=[],
        ),
        data={
            "result_count": 1,
            "results": [{"ID": "1", "CompanyCode": "1710", "GLAccount": "10010000"}],
        },
        schema_context_summary={"service_name": "API_JOURNALENTRYITEMBASIC_SRV"},
    )

    assert result["passed"] is True
    assert result["issues"] == []


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


def test_result_verifier_handles_null_preferred_filters_from_llm() -> None:
    verifier = LlmResultVerifierAgent(
        llm_client=StaticJsonClient(
            {
                "passed": False,
                "issues": [
                    {
                        "code": "unsupported_business_conclusion",
                        "message": "Returned data does not prove the requested business status.",
                        "blocking": True,
                    }
                ],
                "repair_hints": {"reason": "Try a status field instead.", "preferred_filters": None},
            }
        )
    )

    result = verifier.verify(
        request=AgentRequest(user_input="query open purchase order items"),
        plan=QueryPlan(
            service_name="API_PURCHASEORDER_PROCESS_SRV",
            entity_set="A_PurchaseOrderItem",
            select_fields=["PurchaseOrder", "PurchaseOrderItem"],
            filters=[],
        ),
        data={
            "result_count": 1,
            "results": [{"PurchaseOrder": "4500001513", "PurchaseOrderItem": "10"}],
        },
        schema_context_summary={
            "service_name": "API_PURCHASEORDER_PROCESS_SRV",
            "available_fields": [
                {
                    "entity_set": "A_PurchaseOrderItem",
                    "field_name": "IsCompletelyDelivered",
                }
            ],
        },
    )

    assert result["passed"] is False
    assert result["repair_hints"]["preferred_filters"] == []


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


def test_result_verifier_blocks_material_level_stock_returned_by_batch() -> None:
    verifier = LlmResultVerifierAgent(enabled=False)

    result = verifier.verify(
        request=AgentRequest(user_input="查询物料2211在工厂1710的物料层级的库存"),
        plan=QueryPlan(
            service_name="API_MATERIAL_STOCK_SRV",
            entity_set="A_MatlStkInAcctMod",
            select_fields=["Material", "Plant", "Batch", "MatlWrhsStkQtyInMatlBaseUnit"],
            response_summary_fields=["Material", "Plant", "Batch", "MatlWrhsStkQtyInMatlBaseUnit"],
            filters=[
                FilterCondition(field="Material", operator="eq", value="2211"),
                FilterCondition(field="Plant", operator="eq", value="1710"),
            ],
        ),
        data={
            "result_count": 1,
            "results": [
                {
                    "Material": "2211",
                    "Plant": "1710",
                    "Batch": "B1",
                    "MatlWrhsStkQtyInMatlBaseUnit": "10",
                }
            ],
        },
        schema_context_summary={"service_name": "API_MATERIAL_STOCK_SRV"},
    )

    assert result["passed"] is False
    assert result["issues"][0]["code"] == "wrong_business_level_for_material_stock"
    assert result["repair_hints"]["preferred_result_transform"] == {
        "type": "aggregate",
        "group_by": ["Material", "Plant", "MaterialBaseUnit"],
        "sum_fields": ["MatlWrhsStkQtyInMatlBaseUnit"],
    }


def test_result_verifier_accepts_material_level_stock_aggregation() -> None:
    verifier = LlmResultVerifierAgent(enabled=False)

    result = verifier.verify(
        request=AgentRequest(user_input="查询物料2211在工厂1710的物料层级的库存"),
        plan=QueryPlan(
            service_name="API_MATERIAL_STOCK_SRV",
            entity_set="A_MatlStkInAcctMod",
            select_fields=["Material", "Plant", "MaterialBaseUnit", "MatlWrhsStkQtyInMatlBaseUnit"],
            response_summary_fields=["Material", "Plant", "MaterialBaseUnit", "MatlWrhsStkQtyInMatlBaseUnit"],
            result_transform=ResultTransform(
                type="aggregate",
                group_by=["Material", "Plant", "MaterialBaseUnit"],
                sum_fields=["MatlWrhsStkQtyInMatlBaseUnit"],
            ),
        ),
        data={
            "result_count": 1,
            "results": [
                {
                    "Material": "2211",
                    "Plant": "1710",
                    "MaterialBaseUnit": "PC",
                    "MatlWrhsStkQtyInMatlBaseUnit": "10",
                }
            ],
        },
        schema_context_summary={"service_name": "API_MATERIAL_STOCK_SRV"},
    )

    assert result["passed"] is True


def test_result_verifier_blocks_outbound_delivery_shipping_date_from_delivery_date() -> None:
    verifier = LlmResultVerifierAgent(enabled=False)

    result = verifier.verify(
        request=AgentRequest(user_input="列出发货日期大于2023.03.20的交货单"),
        plan=QueryPlan(
            service_name="API_OUTBOUND_DELIVERY_SRV",
            entity_set="A_OutbDeliveryHeader",
            select_fields=["DeliveryDocument", "DeliveryDate"],
            response_summary_fields=["DeliveryDocument", "DeliveryDate"],
            filters=[
                FilterCondition(
                    field="DeliveryDate",
                    operator="gt",
                    value="2023-03-20T00:00:00",
                    value_type="datetime",
                )
            ],
        ),
        data={
            "result_count": 1,
            "results": [{"DeliveryDocument": "80000001", "DeliveryDate": "/Date(1679270400000)/"}],
        },
        schema_context_summary={
            "service_name": "API_OUTBOUND_DELIVERY_SRV",
            "api_skill": {
                "summary": (
                    "For 发货日期 delivery lists, use A_OutbDeliveryHeader.ActualGoodsMovementDate. "
                    "Do not use A_OutbDeliveryHeader.DeliveryDate for 发货日期; DeliveryDate means 交货日期."
                )
            },
        },
    )

    assert result["passed"] is False
    assert result["issues"][0]["code"] == "wrong_business_level_for_outbound_delivery_shipping_date"
    assert result["repair_hints"]["preferred_filters"] == [
        {
            "entity_set": "A_OutbDeliveryHeader",
            "field": "ActualGoodsMovementDate",
            "operator": "gt",
            "value": "2023-03-20T00:00:00",
            "value_type": "datetime",
        }
    ]
    assert result["repair_hints"]["forbidden_fields_unless_requested"] == ["DeliveryDate"]


def test_result_verifier_accepts_outbound_delivery_actual_shipping_date() -> None:
    verifier = LlmResultVerifierAgent(enabled=False)

    result = verifier.verify(
        request=AgentRequest(user_input="列出发货日期大于2023.03.20的交货单"),
        plan=QueryPlan(
            service_name="API_OUTBOUND_DELIVERY_SRV",
            entity_set="A_OutbDeliveryHeader",
            select_fields=["DeliveryDocument", "ActualGoodsMovementDate"],
            response_summary_fields=["DeliveryDocument", "ActualGoodsMovementDate"],
            filters=[
                FilterCondition(
                    field="ActualGoodsMovementDate",
                    operator="gt",
                    value="2023-03-20T00:00:00",
                    value_type="datetime",
                )
            ],
        ),
        data={
            "result_count": 1,
            "results": [{"DeliveryDocument": "80000001", "ActualGoodsMovementDate": "/Date(1679270400000)/"}],
        },
        schema_context_summary={
            "service_name": "API_OUTBOUND_DELIVERY_SRV",
            "api_skill": {
                "summary": (
                    "For 发货日期 delivery lists, use A_OutbDeliveryHeader.ActualGoodsMovementDate. "
                    "Do not use A_OutbDeliveryHeader.DeliveryDate for 发货日期; DeliveryDate means 交货日期."
                )
            },
        },
    )

    assert result["passed"] is True
