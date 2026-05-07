from pathlib import Path

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

    assert "A_JournalEntryItemBasic.GLAccountName" in journal["top_answer_fields"]
    assert "A_JournalEntryItemBasic.CompanyCodeName" in journal["top_answer_fields"]
    assert "GLAccountLineItem.GLAccountName" not in line_item["top_answer_fields"]
    assert "GLAccountLineItem.CompanyCodeName" not in line_item["top_answer_fields"]


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
    assert "A_SalesOrder.SalesOrder" in sales_order["top_answer_fields"][:4]

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
        "A_OutbDeliveryHeader.DeliveryDate",
        "A_OutbDeliveryHeader.SoldToParty",
        "A_OutbDeliveryHeader.ShipToParty",
    ]
    assert "A_OutbDeliveryHeader.OverallGoodsMovementStatus" in delivery["top_answer_fields"][:8]
    assert "A_OutbDeliveryHeader.OverallDelivReltdBillgStatus" in delivery["top_answer_fields"][:8]
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


def test_outbound_delivery_skill_documents_delivered_not_billed_pattern() -> None:
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_OUTBOUND_DELIVERY_SRV")
    assert skill is not None

    assert "Delivered But Not Billed Delivery Documents" in skill.content
    assert "A_OutbDeliveryHeader.OverallGoodsMovementStatus eq 'C'" in skill.content
    assert "A_OutbDeliveryHeader.OverallDelivReltdBillgStatus eq 'A'" in skill.content


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
        "A_OutbDeliveryHeader.DeliveryDate",
        "A_OutbDeliveryHeader.SoldToParty",
        "A_OutbDeliveryHeader.ShipToParty",
        "A_OutbDeliveryHeader.OverallGoodsMovementStatus",
        "A_OutbDeliveryHeader.OverallDelivReltdBillgStatus",
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
