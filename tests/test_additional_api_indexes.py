from pathlib import Path

from sap_odata_agent.application.orchestrator import AgentOrchestrator
from sap_odata_agent.infrastructure.indexing.api_catalog_provider import ApiCatalogProvider
from sap_odata_agent.infrastructure.indexing.api_skill_provider import ApiSkillProvider
from sap_odata_agent.infrastructure.indexing.index_loader import LocalIndexLoader
from sap_odata_agent.infrastructure.indexing.schema_context_provider import SchemaContextProvider
from sap_odata_agent.domain.models import ApiRouteDecision, SelectedApi


ADDITIONAL_APIS = {
    "API_INFORECORD_PROCESS_SRV",
    "API_MATERIAL_DOCUMENT_SRV",
    "API_MATERIAL_STOCK_SRV",
    "API_PRODUCT_AVAILY_INFO_BASIC",
    "API_PRODUCT_SRV",
    "API_PURCHASEORDER_PROCESS_SRV",
    "API_PURCHASEREQ_PROCESS_SRV",
    "API_SUPPLIERINVOICE_PROCESS_SRV",
}


def test_api_catalog_discovers_additional_indexed_apis() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    service_names = {item["service_name"] for item in catalog}

    assert ADDITIONAL_APIS <= service_names


def test_api_catalog_cache_returns_isolated_copies() -> None:
    provider = ApiCatalogProvider(index_root="data/index")
    first = provider.load()
    assert first

    first[0]["service_name"] = "MUTATED"
    first[0]["top_entities"].append("MUTATED_ENTITY")

    second = provider.load()

    assert second[0]["service_name"] != "MUTATED"
    assert "MUTATED_ENTITY" not in second[0]["top_entities"]


def test_api_catalog_uses_compact_router_shape() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    purchase_order = next(
        item for item in catalog if item["service_name"] == "API_PURCHASEORDER_PROCESS_SRV"
    )

    assert set(purchase_order) == {
        "service_name",
        "service_kind",
        "runtime_available",
        "odata_runtime_available",
        "runtime_notes",
        "short_description",
        "primary_business_objects",
        "top_entities",
        "top_filter_fields",
        "top_answer_fields",
    }
    assert purchase_order["service_kind"] == "ODATA"
    assert purchase_order["odata_runtime_available"] is True
    assert purchase_order["primary_business_objects"][:3] == [
        "Purchase Order",
        "Purchase Order Item",
        "Purchase Order Schedule Line",
    ]
    assert purchase_order["top_entities"][:3] == [
        "A_PurchaseOrder",
        "A_PurchaseOrderItem",
        "A_PurchaseOrderScheduleLine",
    ]
    assert len(purchase_order["top_filter_fields"]) <= 18
    assert len(purchase_order["top_answer_fields"]) <= 24
    assert "A_PurchaseOrderItem.IsFinallyInvoiced" in purchase_order["top_filter_fields"]
    assert "A_PurchaseOrderItem.Material" in purchase_order["top_filter_fields"]
    assert "A_PurchaseOrderScheduleLine.ScheduleLineDeliveryDate" in purchase_order["top_filter_fields"]


def test_api_catalog_exposes_answer_fields_for_router_selection() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    journal = next(item for item in catalog if item["service_name"] == "API_JOURNALENTRYITEMBASIC_SRV")
    line_item = next(item for item in catalog if item["service_name"] == "API_GLACCOUNTLINEITEM")
    operational_cube = next(item for item in catalog if item["service_name"] == "API_OPLACCTGDOCITEMCUBE_SRV")
    trial_balance = next(item for item in catalog if item["service_name"] == "C_TRIALBALANCE_CDS")

    assert "A_JournalEntryItemBasic.GLAccountName" in journal["top_answer_fields"]
    assert "A_JournalEntryItemBasic.CompanyCodeName" in journal["top_answer_fields"]
    assert "GLAccountLineItem.ClearingDate" in line_item["top_filter_fields"]
    assert "GLAccountLineItem.PostingDate" in line_item["top_filter_fields"]
    assert "GLAccountLineItem.ClearingDate" in line_item["top_answer_fields"]
    assert "GLAccountLineItem.CompanyCodeCurrency" in line_item["top_answer_fields"]
    assert "GLAccountLineItem.ID" not in line_item["top_answer_fields"]
    assert "GLAccountLineItem.GLAccountName" not in line_item["top_answer_fields"]
    assert "GLAccountLineItem.CompanyCodeName" not in line_item["top_answer_fields"]
    assert "A_OperationalAcctgDocItemCube.AccountingDocumentType" in operational_cube["top_filter_fields"]
    assert "A_OperationalAcctgDocItemCube.AccountingDocCreatedByUser" in operational_cube["top_answer_fields"]
    assert "A_OperationalAcctgDocItemCube.AmountInCompanyCodeCurrency" in operational_cube["top_answer_fields"]
    assert "C_TRIALBALANCEResults.FiscalPeriod" in trial_balance["top_filter_fields"]
    assert "C_TRIALBALANCEResults.EndingBalanceAmtInCoCodeCrcy" in trial_balance["top_answer_fields"]
    assert "C_TRIALBALANCEResults.ID" not in trial_balance["top_answer_fields"]


def test_company_code_catalog_prioritizes_chart_of_accounts_for_router() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    company_code = next(item for item in catalog if item["service_name"] == "API_COMPANYCODE_SRV")

    assert company_code["top_filter_fields"][:3] == [
        "A_CompanyCode.CompanyCode",
        "A_CompanyCode.ChartOfAccounts",
        "A_CompanyCode.CountryChartOfAccounts",
    ]
    assert "A_CompanyCode.ChartOfAccounts" in company_code["top_answer_fields"][:4]
    assert "A_CompanyCode.CountryChartOfAccounts" in company_code["top_answer_fields"][:4]


def test_sales_order_and_outbound_delivery_catalog_expose_document_reference_fields() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    sales_order = next(item for item in catalog if item["service_name"] == "API_SALES_ORDER_SRV")
    delivery = next(item for item in catalog if item["service_name"] == "API_OUTBOUND_DELIVERY_SRV")

    assert sales_order["top_entities"][:2] == ["A_SalesOrder", "A_SalesOrderItem"]
    assert "A_SalesOrder.SalesOrder" in sales_order["top_filter_fields"][:4]
    assert "A_SalesOrderItem.Material" in sales_order["top_filter_fields"][:4]
    assert "A_SalesOrderItem.DeliveryStatus" in sales_order["top_filter_fields"][:4]
    assert "A_SalesOrder.SalesOrder" in sales_order["top_answer_fields"][:4]
    assert "A_SalesOrderItem.Material" in sales_order["top_answer_fields"][:4]

    assert delivery["top_entities"][:3] == [
        "A_OutbDeliveryHeader",
        "A_OutbDeliveryItem",
        "A_OutbDeliveryDocFlow",
    ]
    assert delivery["top_filter_fields"][:10] == [
        "A_OutbDeliveryItem.ReferenceSDDocument",
        "A_OutbDeliveryItem.ReferenceSDDocumentItem",
        "A_OutbDeliveryHeader.SoldToParty",
        "A_OutbDeliveryHeader.ShipToParty",
        "A_OutbDeliveryHeader.OverallGoodsMovementStatus",
        "A_OutbDeliveryHeader.OverallDelivReltdBillgStatus",
        "A_OutbDeliveryItem.GoodsMovementStatus",
        "A_OutbDeliveryItem.DeliveryRelatedBillingStatus",
        "A_OutbDeliveryHeader.OrderID",
        "A_OutbDeliveryHeader.DeliveryDocument",
    ]
    assert delivery["top_answer_fields"][:4] == [
        "A_OutbDeliveryHeader.DeliveryDocument",
        "A_OutbDeliveryHeader.ActualGoodsMovementDate",
        "A_OutbDeliveryHeader.DeliveryDate",
        "A_OutbDeliveryHeader.SoldToParty",
    ]
    assert "A_OutbDeliveryHeader.OverallGoodsMovementStatus" in delivery["top_answer_fields"][:8]
    assert "A_OutbDeliveryHeader.OverallDelivReltdBillgStatus" in delivery["top_answer_fields"][:8]
    assert "A_OutbDeliveryHeader.ActualGoodsMovementDate" in delivery["top_filter_fields"][:12]
    assert "A_OutbDeliveryItem.ReferenceSDDocument" in delivery["top_answer_fields"]
    assert "A_OutbDeliveryItem.ReferenceSDDocumentItem" in delivery["top_answer_fields"]


def test_multi_api_schema_context_can_be_enriched_by_primary_api_skill() -> None:
    route_decision = ApiRouteDecision(
        selected_apis=[
            SelectedApi("API_OUTBOUND_DELIVERY_SRV", confidence=0.95),
            SelectedApi("API_BILLING_DOCUMENT_SRV", confidence=0.7),
        ],
        requires_multi_api=True,
    )
    provider = SchemaContextProvider(index_root="data/index")
    context = provider.build(
        "API_OUTBOUND_DELIVERY_SRV",
        "\u67e5\u8be2\u5ba2\u623717100003\u5df2\u53d1\u8d27\u4f46\u8fd8\u6ca1\u5f00\u7968\u7684\u4ea4\u8d27\u5355",
        route_decision=route_decision,
    )
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_OUTBOUND_DELIVERY_SRV")
    assert skill is not None

    enriched = provider.enrich_with_api_skill(context, skill.as_prompt_payload())

    fields = {
        (field.get("service_name"), field.get("entity_set"), field.get("field_name"))
        for field in enriched["candidate_fields"]
    }
    assert (
        "API_OUTBOUND_DELIVERY_SRV",
        "A_OutbDeliveryHeader",
        "OverallGoodsMovementStatus",
    ) in fields
    assert (
        "API_OUTBOUND_DELIVERY_SRV",
        "A_OutbDeliveryHeader",
        "OverallDelivReltdBillgStatus",
    ) in fields
    assert any(
        match.get("matched_field") == "A_OutbDeliveryHeader.OverallDelivReltdBillgStatus"
        for match in enriched["skill_field_matches"]
    )


def test_orchestrator_enriches_multi_api_context_with_each_api_skill() -> None:
    route_decision = ApiRouteDecision(
        selected_apis=[
            SelectedApi("API_OUTBOUND_DELIVERY_SRV", confidence=0.95),
            SelectedApi("API_BILLING_DOCUMENT_SRV", confidence=0.7),
        ],
        requires_multi_api=True,
    )
    provider = SchemaContextProvider(index_root="data/index")
    skill_provider = ApiSkillProvider(skill_root="data/api_skills")
    context = provider.build(
        "API_OUTBOUND_DELIVERY_SRV",
        "\u67e5\u8be2\u5ba2\u623717100003\u4ea4\u8d27\u5355\u5bf9\u5e94\u7684\u5f00\u7968\u9879\u76ee",
        route_decision=route_decision,
    )
    primary_skill = skill_provider.load("API_OUTBOUND_DELIVERY_SRV")
    assert primary_skill is not None
    context = provider.enrich_with_api_skill(context, primary_skill.as_prompt_payload())
    context = {**context, "api_skill": primary_skill.as_prompt_payload()}
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator.api_skill_provider = skill_provider
    orchestrator.schema_context_provider = provider

    enriched = orchestrator._attach_multi_api_skills(context, timings=[])

    fields = {
        (field.get("service_name"), field.get("entity_set"), field.get("field_name"))
        for field in enriched["candidate_fields"]
    }
    assert (
        "API_BILLING_DOCUMENT_SRV",
        "A_BillingDocumentItem",
        "ReferenceSDDocument",
    ) in fields
    assert any(
        match.get("service_name") == "API_BILLING_DOCUMENT_SRV"
        and match.get("matched_field") == "A_BillingDocumentItem.ReferenceSDDocument"
        for match in enriched["skill_field_matches"]
    )


def test_outbound_delivery_skill_documents_delivered_not_billed_pattern() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_OUTBOUND_DELIVERY_SRV")
    assert skill is not None

    assert "Delivered But Not Billed Delivery Documents" in skill.content
    assert "A_OutbDeliveryHeader.OverallGoodsMovementStatus eq 'C'" in skill.content
    assert "A_OutbDeliveryHeader.OverallDelivReltdBillgStatus ne 'C'" in skill.content
    assert "A_OutbDeliveryHeader.OverallDelivReltdBillgStatus eq 'A'" not in skill.content


def test_outbound_delivery_skill_documents_shipping_date_pattern() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_OUTBOUND_DELIVERY_SRV")
    assert skill is not None

    assert "Actual Shipping Date For Delivery Documents" in skill.content
    assert "A_OutbDeliveryHeader.ActualGoodsMovementDate" in skill.content
    assert "Do not use `A_OutbDeliveryHeader.DeliveryDate` for `发货日期`" in skill.content


def test_outbound_delivery_skill_documents_product_master_pattern() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_OUTBOUND_DELIVERY_SRV")
    assert skill is not None

    assert "Product Master Data For Customer Delivery Items" in skill.content
    assert "A_OutbDeliveryItem.Material ne ''" in skill.content
    assert "A_Product.ProductGroup" in skill.content


def test_product_skill_basic_data_includes_product_group() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_PRODUCT_SRV")
    assert skill is not None

    assert "A_Product.ProductGroup" in skill.content


def test_sales_order_skill_documents_open_delivery_and_billing_patterns() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_SALES_ORDER_SRV")
    assert skill is not None

    assert "Customer Sales Orders Not Fully Delivered" in skill.content
    assert "A_SalesOrder.OverallTotalDeliveryStatus ne 'C'" in skill.content
    assert "Material Sales Orders Not Fully Delivered" in skill.content
    assert "A_SalesOrderItem.Material eq '<material>'" in skill.content
    assert "A_SalesOrderItem.DeliveryStatus ne 'C'" in skill.content
    assert "Customer Sales Orders Not Fully Billed" in skill.content
    assert "A_SalesOrder.OverallOrdReltdBillgStatus ne 'C'" in skill.content


def test_sales_order_material_open_delivery_context_promotes_item_fields() -> None:
    provider = SchemaContextProvider(index_root="data/index")
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_SALES_ORDER_SRV")
    assert skill is not None

    context = provider.build(
        "API_SALES_ORDER_SRV",
        "查询物料MZ-TG-Y240的未交货销售订单",
    )
    enriched = provider.enrich_with_api_skill(context, skill.as_prompt_payload())

    fields = {
        (field.get("entity_set"), field.get("field_name"))
        for field in enriched["candidate_fields"]
    }
    assert ("A_SalesOrderItem", "Material") in fields
    assert ("A_SalesOrderItem", "DeliveryStatus") in fields
    assert any(
        match.get("matched_field") == "A_SalesOrderItem.DeliveryStatus"
        for match in enriched["skill_field_matches"]
    )


def test_sales_order_skill_documents_pricing_condition_pattern() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_SALES_ORDER_SRV")
    assert skill is not None

    assert "Sales Order Pricing Conditions" in skill.content
    assert "A_SalesOrderItemPrElement" in skill.content
    assert "A_SalesOrderItemPrElement.ConditionType" in skill.content


def test_billing_document_skill_documents_product_master_pattern() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_BILLING_DOCUMENT_SRV")
    assert skill is not None

    assert "Product Master Data For Customer Billing Items" in skill.content
    assert "A_BillingDocumentItem.Material ne ''" in skill.content
    assert "A_Product.ProductGroup" in skill.content


def test_info_record_skill_documents_supplier_name_bridge_pattern() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_INFORECORD_PROCESS_SRV")
    assert skill is not None

    assert "Supplier Name For Material Info Records" in skill.content
    assert "API_BUSINESS_PARTNER.A_Supplier" in skill.content
    assert "A_Supplier.SupplierName" in skill.content
    assert "SupplierRespSalesPersonName" in skill.content


def test_material_document_skill_documents_po_goods_receipt_target_pattern() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_MATERIAL_DOCUMENT_SRV")
    assert skill is not None

    assert "Purchase Orders With Goods Receipt Material Documents" in skill.content
    assert "API_MATERIAL_DOCUMENT_SRV.A_MaterialDocumentItem" in skill.content
    assert "target_entity_set" in skill.content
    assert "MaterialDocument" in skill.content


def test_material_document_skill_documents_production_order_material_documents() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_MATERIAL_DOCUMENT_SRV")
    assert skill is not None

    assert "Production Order Material Documents" in skill.content
    assert "API_PRODUCTION_ORDER_2_SRV.A_ProductionOrder_2" in skill.content
    assert "A_MaterialDocumentItem.ManufacturingOrder" in skill.content
    assert "material-only movement history" in skill.content


def test_material_document_catalog_pins_manufacturing_order_fields() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    material_doc = next(item for item in catalog if item["service_name"] == "API_MATERIAL_DOCUMENT_SRV")

    assert "A_MaterialDocumentItem.ManufacturingOrder" in material_doc["top_filter_fields"][:4]
    assert "A_MaterialDocumentItem.ManufacturingOrder" in material_doc["top_answer_fields"][:5]


def test_production_order_skill_documents_common_pp_patterns() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_PRODUCTION_ORDER_2_SRV")
    assert skill is not None

    assert "A_ProductionOrder_2.ProductionPlant" in skill.content
    assert "Production Order Operations" in skill.content
    assert "A_ProductionOrderOperation_2" in skill.content
    assert "A_ProductionOrderOperation_2.WorkCenter" in skill.content
    assert "Production Order Components" in skill.content
    assert "A_ProductionOrderComponent_2" in skill.content
    assert "Production Order Finished Product Master Data" in skill.content
    assert "API_PRODUCT_SRV.A_Product" in skill.content
    assert "Production Order Material Documents" in skill.content
    assert "API_MATERIAL_DOCUMENT_SRV.A_MaterialDocumentItem" in skill.content
    assert "A_MaterialDocumentItem.ManufacturingOrder" in skill.content


def test_material_stock_skill_documents_production_component_stock_pattern() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_MATERIAL_STOCK_SRV")
    assert skill is not None

    assert "Production Order Component Stock" in skill.content
    assert "API_PRODUCTION_ORDER_2_SRV.A_ProductionOrderComponent_2" in skill.content
    assert "A_MatlStkInAcctMod" in skill.content
    assert "MatlWrhsStkQtyInMatlBaseUnit" in skill.content


def test_material_stock_skill_documents_mrp_material_stock_pattern() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_MATERIAL_STOCK_SRV")
    assert skill is not None

    assert "MRP Material Stock" in skill.content
    assert "API_MRP_MATERIALS_SRV_01" in skill.content
    assert "A_MRPMaterial.Material" in skill.content
    assert "A_MatlStkInAcctMod.Material" in skill.content


def test_material_stock_skill_documents_material_level_aggregation() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_MATERIAL_STOCK_SRV")
    assert skill is not None

    assert "Material-Level Stock" in skill.content
    assert "物料层级库存" in skill.content
    assert "result_transform aggregate" in skill.content
    assert "A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit" in skill.content
    assert "Do not select `A_MatlStkInAcctMod.Batch`" in skill.content


def test_planned_orders_skill_documents_component_material_pattern() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_PLANNED_ORDERS")
    assert skill is not None

    assert "planned order component" in skill.content
    assert "A_PlannedOrderComponent.Material" in skill.content
    assert "A_PlannedOrderComponent.GoodsMovementEntryQty" in skill.content
    assert "BOMItem" in skill.content


def test_planned_orders_skill_distinguishes_header_material_master_data_from_components() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_PLANNED_ORDERS")
    assert skill is not None

    assert "计划订单物料的产品主数据" in skill.content
    assert "not `A_PlannedOrderComponent`" in skill.content
    assert "A_PlannedOrder.Material" in skill.content
    assert "API_PRODUCT_SRV.A_Product" in skill.content


def test_mrp_materials_skill_documents_supply_demand_key_fields() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_MRP_MATERIALS_SRV_01")
    assert skill is not None

    assert "SupplyDemandItems" in skill.content
    assert "SupplyDemandItems.MRPElement" in skill.content
    assert "SupplyDemandItems.MRPElementItem" in skill.content
    assert "SupplyDemandItems.MRPElementCategory" in skill.content
    assert "MRPElementOpenQuantity" in skill.content
    assert "MRP Material Stock" in skill.content
    assert "API_MATERIAL_STOCK_SRV.A_MatlStkInAcctMod" in skill.content


def test_production_routing_skill_distinguishes_routing_from_operations() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_PRODUCTION_ROUTING")
    assert skill is not None

    assert "ProductionRoutingMatlAssgmt" in skill.content
    assert "Product`, `Plant`, `ProductionRoutingGroup`, and `ProductionRouting`" in skill.content
    assert "Do not continue from `ProductionRoutingMatlAssgmt` into `ProductionRoutingOperation`" in skill.content
    assert "`工序`" in skill.content
    assert "ProductionRoutingOperation" in skill.content
    assert "`Operation`" in skill.content
    assert "`WorkCenterInternalID`" in skill.content
    assert "Routing Work Centers" in skill.content
    assert "API_WORK_CENTERS.A_WorkCenterAllCapacity" in skill.content
    assert "ProductionRoutingOperation.WorkCenterInternalID" in skill.content
    assert "ProductionRoutingHeader.PlanningWorkCenter" in skill.content


def test_work_centers_skill_documents_routing_bridge_fields() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_WORK_CENTERS")
    assert skill is not None

    assert "Routing Work Centers" in skill.content
    assert "A_WorkCenterAllCapacity.WorkCenterInternalID" in skill.content
    assert "A_WorkCenterAllCapacity.WorkCenter" in skill.content
    assert "A_WorkCenterAllCapacity.WorkCenterDesc" in skill.content


def test_routing_work_center_multi_api_context_promotes_bridge_fields() -> None:
    route_decision = ApiRouteDecision(
        selected_apis=[
            SelectedApi("API_PRODUCTION_ROUTING", confidence=0.9),
            SelectedApi("API_WORK_CENTERS", confidence=0.7),
        ],
        requires_multi_api=True,
    )
    provider = SchemaContextProvider(index_root="data/index")
    skill_provider = ApiSkillProvider(skill_root="data/api_skills")
    context = provider.build(
        "API_PRODUCTION_ROUTING",
        "查询产品MZ-FG-R300工艺路线用到的工作中心",
        route_decision=route_decision,
    )
    for service_name in ("API_PRODUCTION_ROUTING", "API_WORK_CENTERS"):
        skill = skill_provider.load(service_name)
        assert skill is not None
        context = provider.enrich_with_api_skill(context, skill.as_prompt_payload())

    fields = [
        (field.get("service_name"), field.get("entity_set"), field.get("field_name"))
        for field in context["candidate_fields"][:16]
    ]

    assert (
        "API_PRODUCTION_ROUTING",
        "ProductionRoutingOperation",
        "WorkCenterInternalID",
    ) in fields
    assert (
        "API_WORK_CENTERS",
        "A_WorkCenterAllCapacity",
        "WorkCenterInternalID",
    ) in fields
    assert (
        "API_WORK_CENTERS",
        "A_WorkCenterAllCapacity",
        "WorkCenter",
    ) in fields


def test_production_order_skill_does_not_clarify_plant_work_center_operations() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_PRODUCTION_ORDER_2_SRV")
    assert skill is not None

    assert "查询工厂1710工作中心上的生产订单工序" in skill.content
    assert "do not ask for a specific work center" in skill.content
    assert "WorkCenter eq '1710'" in skill.content
    assert "A_ProductionOrderOperation_2.ProductionPlant" in skill.content


def test_production_order_catalog_pins_operation_fields_for_router() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    production_order = next(item for item in catalog if item["service_name"] == "API_PRODUCTION_ORDER_2_SRV")

    assert production_order["top_filter_fields"][:4] == [
        "A_ProductionOrderOperation_2.ProductionPlant",
        "A_ProductionOrderOperation_2.WorkCenter",
        "A_ProductionOrderOperation_2.ManufacturingOrder",
        "A_ProductionOrderOperation_2.ManufacturingOrderOperation",
    ]
    assert production_order["top_answer_fields"][:5] == [
        "A_ProductionOrderOperation_2.ManufacturingOrder",
        "A_ProductionOrderOperation_2.ManufacturingOrderOperation",
        "A_ProductionOrderOperation_2.ProductionPlant",
        "A_ProductionOrderOperation_2.WorkCenter",
        "A_ProductionOrderOperation_2.MfgOrderOperationText",
    ]


def test_sales_order_reference_fields_remain_in_outbound_delivery_answer_fields() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    delivery = next(item for item in catalog if item["service_name"] == "API_OUTBOUND_DELIVERY_SRV")

    assert "A_OutbDeliveryItem.ReferenceSDDocument" in delivery["top_answer_fields"]
    assert "A_OutbDeliveryItem.ReferenceSDDocumentItem" in delivery["top_answer_fields"]


def test_outbound_delivery_catalog_exposes_billing_status_fields() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    delivery = next(item for item in catalog if item["service_name"] == "API_OUTBOUND_DELIVERY_SRV")

    assert "A_OutbDeliveryHeader.OverallGoodsMovementStatus" in delivery["top_filter_fields"][:8]
    assert "A_OutbDeliveryHeader.OverallDelivReltdBillgStatus" in delivery["top_filter_fields"][:8]
    assert "A_OutbDeliveryHeader.SoldToParty" in delivery["top_filter_fields"][:4]
    assert "A_OutbDeliveryHeader.ShipToParty" in delivery["top_filter_fields"][:4]


def test_outbound_delivery_answer_fields_start_with_header_delivery_status() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    delivery = next(item for item in catalog if item["service_name"] == "API_OUTBOUND_DELIVERY_SRV")

    assert delivery["top_answer_fields"][:6] == [
        "A_OutbDeliveryHeader.DeliveryDocument",
        "A_OutbDeliveryHeader.ActualGoodsMovementDate",
        "A_OutbDeliveryHeader.DeliveryDate",
        "A_OutbDeliveryHeader.SoldToParty",
        "A_OutbDeliveryHeader.ShipToParty",
        "A_OutbDeliveryHeader.OverallGoodsMovementStatus",
    ]


def test_outbound_delivery_sales_order_item_answer_fields_are_still_available() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    delivery = next(item for item in catalog if item["service_name"] == "API_OUTBOUND_DELIVERY_SRV")

    assert "A_OutbDeliveryItem.DeliveryDocument" in delivery["top_answer_fields"]
    assert "A_OutbDeliveryItem.DeliveryDocumentItem" in delivery["top_answer_fields"]


def test_outbound_delivery_catalog_keeps_document_reference_fields_near_top() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    delivery = next(item for item in catalog if item["service_name"] == "API_OUTBOUND_DELIVERY_SRV")

    assert delivery["top_filter_fields"][:2] == [
        "A_OutbDeliveryItem.ReferenceSDDocument",
        "A_OutbDeliveryItem.ReferenceSDDocumentItem",
    ]


def test_api_catalog_pins_info_record_router_fields() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    info_record = next(item for item in catalog if item["service_name"] == "API_INFORECORD_PROCESS_SRV")

    assert "A_PurchasingInfoRecord.Supplier" in info_record["top_filter_fields"]
    assert "A_PurchasingInfoRecord.Material" in info_record["top_filter_fields"]
    assert "A_PurInfoRecdPrcgCndn.ConditionRecord" in info_record["top_filter_fields"]
    assert "A_PurInfoRecdPrcgCndn.ConditionRateAmount" in info_record["top_filter_fields"]
    assert "A_PurInfoRecdPrcgCndn.ConditionCurrency" in info_record["top_filter_fields"]
    assert "A_PurInfoRecdPrcgCndnValidity.Material" in info_record["top_filter_fields"]


def test_api_catalog_pins_material_stock_router_fields() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    stock = next(item for item in catalog if item["service_name"] == "API_MATERIAL_STOCK_SRV")

    assert "A_MaterialStock.Material" in stock["top_filter_fields"]
    assert "A_MaterialStock.MaterialBaseUnit" in stock["top_filter_fields"]
    assert "A_MatlStkInAcctMod.Material" in stock["top_filter_fields"]
    assert "A_MatlStkInAcctMod.Plant" in stock["top_filter_fields"]
    assert "A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit" in stock["top_filter_fields"]


def test_purchase_order_history_index_is_cds_view_only() -> None:
    snapshot = LocalIndexLoader(index_root="data/index").load("I_PurchaseOrderHistoryAPI01")
    service = snapshot.services[0]

    assert service["service_kind"] == "CDS_VIEW_ONLY"
    assert service["base_path"] == "cds://I_PurchaseOrderHistoryAPI01"
    assert service["runtime_available"] is False
    assert service["odata_runtime_available"] is False
    assert not service["runtime_path_template"]
    assert all(entity.get("runtime_kind") == "CDS_VIEW_ONLY" for entity in snapshot.entities)


def test_production_version_index_is_cds_view_only_and_cataloged() -> None:
    snapshot = LocalIndexLoader(index_root="data/index").load("I_ProductionVersion")
    service = snapshot.services[0]
    entity = snapshot.entities[0]
    catalog = ApiCatalogProvider(index_root="data/index").load()
    production_version = next(item for item in catalog if item["service_name"] == "I_ProductionVersion")

    assert service["service_kind"] == "CDS_VIEW_ONLY"
    assert service["base_path"] == "cds://I_ProductionVersion"
    assert service["runtime_available"] is False
    assert service["odata_runtime_available"] is False
    assert entity["entity_set"] == "I_ProductionVersion"
    assert entity["key_fields"] == ["Material", "Plant", "ProductionVersion"]
    assert production_version["primary_business_objects"][:1] == ["Production Version"]
    assert "I_ProductionVersion.Material" in production_version["top_filter_fields"]
    assert "I_ProductionVersion.Plant" in production_version["top_filter_fields"]
    assert "I_ProductionVersion.ProductionVersion" in production_version["top_answer_fields"]
    assert "I_ProductionVersion.BillOfMaterialVariant" in production_version["top_answer_fields"]
    assert "I_ProductionVersion.BillOfOperationsGroup" in production_version["top_answer_fields"]


def test_production_version_schema_context_loads_assignment_fields() -> None:
    provider = SchemaContextProvider(index_root="data/index")
    skill = ApiSkillProvider(skill_root="data/api_skills").load("I_ProductionVersion")
    assert skill is not None

    context = provider.build(
        "I_ProductionVersion",
        "production version for material TG0011 plant 1710 with BOM and routing assignment",
    )
    context = provider.enrich_with_api_skill(context, skill.as_prompt_payload())
    summary = provider.summarize(context)

    available_fields = {
        (field["entity_set"], field["field_name"])
        for field in summary["available_fields"]
    }
    skill_matches = {
        match["matched_field"]
        for match in summary["skill_field_matches"]
    }

    assert ("I_ProductionVersion", "Material") in available_fields
    assert ("I_ProductionVersion", "Plant") in available_fields
    assert ("I_ProductionVersion", "ProductionVersion") in available_fields
    assert ("I_ProductionVersion", "BillOfMaterialVariant") in available_fields
    assert ("I_ProductionVersion", "BillOfOperationsGroup") in available_fields
    assert "I_ProductionVersion.BillOfMaterialVariant" in skill_matches
    assert "I_ProductionVersion.BillOfOperationsGroup" in skill_matches


def test_purchase_order_schema_context_loads_business_fields() -> None:
    context = SchemaContextProvider(index_root="data/index").build(
        "API_PURCHASEORDER_PROCESS_SRV",
        "purchase order supplier company code",
    )

    assert context["service_name"] == "API_PURCHASEORDER_PROCESS_SRV"
    assert any(entity["entity_set"] == "A_PurchaseOrder" for entity in context["entities"])

    fields = {
        (field["entity_set"], field["field_name"])
        for field in context["candidate_fields"]
    }
    assert ("A_PurchaseOrder", "PurchaseOrder") in fields
    assert ("A_PurchaseOrder", "Supplier") in fields
    assert ("A_PurchaseOrder", "CompanyCode") in fields


def test_multi_api_schema_context_includes_all_routed_services_and_cross_join() -> None:
    route_decision = ApiRouteDecision(
        selected_apis=[
            SelectedApi("API_COMPANYCODE_SRV", confidence=0.85),
            SelectedApi("API_GLACCOUNTINCHARTOFACCOUNTS_SRV", confidence=0.75),
        ],
        requires_multi_api=True,
    )
    context = SchemaContextProvider(index_root="data/index").build(
        "API_COMPANYCODE_SRV",
        "\u67e5\u8be2\u516c\u53f81710\u7684\u8d39\u7528\u7c7b\u79d1\u76ee",
        route_decision=route_decision,
    )

    assert context["multi_api"] is True
    assert context["service_names"] == [
        "API_COMPANYCODE_SRV",
        "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
    ]
    qualified_entities = {
        (entity["service_name"], entity["entity_set"])
        for entity in context["entities"]
    }
    assert ("API_COMPANYCODE_SRV", "A_CompanyCode") in qualified_entities
    assert (
        "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
        "A_GLAccountInChartOfAccounts",
    ) in qualified_entities
    assert any(
        hint.get("cross_service") is True and hint.get("field_name") == "ChartOfAccounts"
        for hint in context["join_hints"]
    )


def test_purchase_order_schema_summary_keeps_receipt_completion_fields() -> None:
    provider = SchemaContextProvider(index_root="data/index")
    context = provider.build(
        "API_PURCHASEORDER_PROCESS_SRV",
        "query supplier 17300003 unreceived purchase orders",
    )
    summary = provider.summarize(context)

    available_fields = {
        (field["entity_set"], field["field_name"])
        for field in summary["available_fields"]
    }
    assert ("A_PurchaseOrderItem", "IsCompletelyDelivered") in available_fields
    assert ("A_PurchaseOrderItem", "GoodsReceiptIsExpected") in available_fields


def test_purchase_order_schema_context_grounds_feedback_preferred_fields() -> None:
    provider = SchemaContextProvider(index_root="data/index")
    context = provider.build(
        "API_PURCHASEORDER_PROCESS_SRV",
        "\u67e5\u8be2\u4f9b\u5e94\u554617300003\u7684\u672a\u6e05\u53d1\u7968\u8ba2\u5355",
        feedback_memories=[
            {
                "case_id": "feedback-case",
                "memory_type": "field_disambiguation",
                "lesson": "Use IsFinallyInvoiced=false for open invoice purchase orders.",
                "preferred_fields": ["IsFinallyInvoiced"],
                "preferred_entities": ["PurchaseOrder"],
            }
        ],
    )
    summary = provider.summarize(context)

    candidate_fields = {
        (field["entity_set"], field["field_name"])
        for field in context["candidate_fields"]
    }
    available_fields = {
        (field["entity_set"], field["field_name"])
        for field in summary["available_fields"]
    }

    assert ("A_PurchaseOrderItem", "IsFinallyInvoiced") in candidate_fields
    assert ("A_PurchaseOrderItem", "IsFinallyInvoiced") in available_fields
    assert context["feedback_field_matches"] == [
        {
            "memory_case_id": "feedback-case",
            "memory_type": "field_disambiguation",
            "preferred_field": "IsFinallyInvoiced",
            "matched_field": "A_PurchaseOrderItem.IsFinallyInvoiced",
            "entity_set": "A_PurchaseOrderItem",
            "field_name": "IsFinallyInvoiced",
            "reason": "preferred field from feedback memory matched current API schema",
        }
    ]
    assert summary["feedback_field_matches"] == context["feedback_field_matches"]


def test_schema_context_grounds_api_skill_referenced_stock_quantity_field() -> None:
    provider = SchemaContextProvider(index_root="data/index")
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_MATERIAL_STOCK_SRV")
    assert skill is not None

    context = provider.build(
        "API_MATERIAL_STOCK_SRV",
        "\u67e5\u8be2\u7269\u6599\u5e93\u5b58\u5217\u8868",
    )
    context = provider.enrich_with_api_skill(context, skill.as_prompt_payload())
    summary = provider.summarize(context)

    candidate_fields = {
        (field["entity_set"], field["field_name"])
        for field in context["candidate_fields"]
    }
    available_fields = {
        (field["entity_set"], field["field_name"])
        for field in summary["available_fields"]
    }

    assert ("A_MatlStkInAcctMod", "MatlWrhsStkQtyInMatlBaseUnit") in candidate_fields
    assert ("A_MatlStkInAcctMod", "MatlWrhsStkQtyInMatlBaseUnit") in available_fields
    assert any(
        match["matched_field"] == "A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit"
        for match in summary["skill_field_matches"]
    )


def test_business_partner_schema_context_exposes_supplier_profile_fields() -> None:
    provider = SchemaContextProvider(index_root="data/index")
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_BUSINESS_PARTNER")
    assert skill is not None

    context = provider.build(
        "API_BUSINESS_PARTNER",
        "查询供应商17300003的基本信息",
    )
    context = provider.enrich_with_api_skill(context, skill.as_prompt_payload())
    summary = provider.summarize(context)

    available_fields = {
        (field["entity_set"], field["field_name"])
        for field in summary["available_fields"]
    }
    skill_matches = {
        match["matched_field"]
        for match in summary["skill_field_matches"]
    }

    assert ("A_Supplier", "SupplierName") in available_fields
    assert ("A_Supplier", "SupplierFullName") in available_fields
    assert ("A_BusinessPartnerAddress", "StreetName") in available_fields
    assert "A_Supplier.SupplierName" in skill_matches
    assert "A_BusinessPartnerAddress.AddressID" in skill_matches


def test_product_availability_index_is_marked_as_function_style_limited() -> None:
    snapshot = LocalIndexLoader(index_root="data/index").load("API_PRODUCT_AVAILY_INFO_BASIC")

    assert len(snapshot.entities) == 3
    assert snapshot.fields == []
    assert all(entity.get("runtime_available") is False for entity in snapshot.entities)
    assert any(entity.get("entity_set") == "DetermineAvailabilityOf" for entity in snapshot.entities)


def test_additional_api_raw_and_generated_files_exist() -> None:
    index_root = Path("data/index")
    required_files = {
        "services.json",
        "entities.json",
        "fields.json",
        "relations.json",
        "entity_graph.json",
        "lookup_paths.json",
        "business_terms.json",
        "vector_documents.jsonl",
        "doc_chunks.jsonl",
        "build_summary.json",
    }

    for service_name in ADDITIONAL_APIS:
        service_dir = index_root / service_name
        present = {path.name for path in service_dir.iterdir() if path.is_file()}
        assert required_files <= present
        assert list((service_dir / "raw").glob("*.json"))
        assert list((service_dir / "raw").glob("*.metadata.xml"))
