from pathlib import Path

from sap_odata_agent.infrastructure.indexing.api_catalog_provider import ApiCatalogProvider
from sap_odata_agent.infrastructure.indexing.index_loader import LocalIndexLoader
from sap_odata_agent.infrastructure.indexing.schema_context_provider import SchemaContextProvider


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


def test_api_catalog_uses_compact_router_shape() -> None:
    catalog = ApiCatalogProvider(index_root="data/index").load()
    purchase_order = next(
        item for item in catalog if item["service_name"] == "API_PURCHASEORDER_PROCESS_SRV"
    )

    assert set(purchase_order) == {
        "service_name",
        "short_description",
        "primary_business_objects",
        "top_entities",
    }
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
