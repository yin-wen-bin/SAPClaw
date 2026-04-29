import pytest
import json

from sap_odata_agent.domain.models import FilterCondition, FunctionParameter, QueryPlan
from sap_odata_agent.infrastructure.sap.odata_client import BasicODataCompiler, BasicPlanValidator


def test_validator_blocks_unknown_service() -> None:
    plan = QueryPlan(service_name="UNKNOWN_SERVICE", entity_set="A_Test")
    issues = BasicPlanValidator().validate(plan)
    assert any(issue.field == "service_name" for issue in issues)


def test_validator_blocks_cds_view_only_service() -> None:
    plan = QueryPlan(service_name="I_PurchaseOrderHistoryAPI01", entity_set="I_PurchaseOrderHistoryAPI01")
    issues = BasicPlanValidator().validate(plan)
    assert any("CDS_VIEW_ONLY" in issue.message for issue in issues)


def test_compiler_rejects_cds_view_only_service() -> None:
    plan = QueryPlan(service_name="I_PurchaseOrderHistoryAPI01", entity_set="I_PurchaseOrderHistoryAPI01")

    with pytest.raises(ValueError, match="CDS_VIEW_ONLY"):
        BasicODataCompiler(base_url="https://sap.example.com").compile(plan)


def test_compiler_builds_basic_odata_url() -> None:
    plan = QueryPlan(
        service_name="API_BUSINESS_PARTNER",
        entity_set="A_BusinessPartner",
        select_fields=["BusinessPartner", "Customer"],
        filters=[FilterCondition(field="BusinessPartner", operator="eq", value="1000001")],
        top=10,
    )
    compiled = BasicODataCompiler(base_url="https://sap.example.com").compile(plan)
    assert compiled.url.startswith("https://sap.example.com/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner?")
    assert "$top=10" in compiled.url
    assert "BusinessPartner eq '1000001'" in compiled.url


def test_compiler_uses_odata_v2_substringof_for_contains_filter() -> None:
    plan = QueryPlan(
        service_name="API_BUSINESS_PARTNER",
        entity_set="A_BusinessPartner",
        select_fields=["BusinessPartner", "BusinessPartnerFullName"],
        filters=[FilterCondition(field="BusinessPartnerFullName", operator="contains", value="trea")],
        top=50,
    )

    compiled = BasicODataCompiler(base_url="https://sap.example.com").compile(plan)

    assert "substringof('trea',BusinessPartnerFullName) eq true" in compiled.url
    assert "BusinessPartnerFullName contains 'trea'" not in compiled.url


def test_compiler_maps_versioned_index_service_name_to_sap_runtime_path() -> None:
    plan = QueryPlan(
        service_name="API_BILL_OF_MATERIAL_SRV_0002",
        entity_set="A_BillOfMaterial",
        select_fields=["BillOfMaterial"],
        filters=[FilterCondition(field="BillOfMaterial", operator="eq", value="BOM1")],
        top=10,
    )

    compiled = BasicODataCompiler(base_url="https://sap.example.com").compile(plan)

    assert compiled.url.startswith("https://sap.example.com/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV;v=0002/")


def test_compiler_keeps_non_versioned_suffix_service_name() -> None:
    plan = QueryPlan(
        service_name="API_MRP_MATERIALS_SRV_01",
        entity_set="A_MRPMaterial",
        select_fields=["Material"],
        filters=[FilterCondition(field="Material", operator="eq", value="TG0011")],
        top=10,
    )

    compiled = BasicODataCompiler(base_url="https://sap.example.com").compile(plan)

    assert compiled.url.startswith("https://sap.example.com/sap/opu/odata/sap/API_MRP_MATERIALS_SRV_01/")


def test_compiler_uses_runtime_service_name_from_index_metadata_source(tmp_path) -> None:
    service_dir = tmp_path / "data" / "index" / "API_PRODUCTION_ROUTING"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_PRODUCTION_ROUTING",
                    "source": (
                        "https://sap.example.com/sap/opu/odata/sap/"
                        "API_PRODUCTION_ROUTING;v=0002/$metadata?sap-client=100"
                    ),
                }
            ]
        ),
        encoding="utf-8",
    )
    plan = QueryPlan(
        service_name="API_PRODUCTION_ROUTING",
        entity_set="ProductionRoutingHeader",
        select_fields=["ProductionRoutingGroup", "ProductionRouting"],
        top=10,
    )

    compiled = BasicODataCompiler(
        base_url="https://sap.example.com",
        index_root=tmp_path / "data" / "index",
    ).compile(plan)

    assert compiled.url.startswith("https://sap.example.com/sap/opu/odata/sap/API_PRODUCTION_ROUTING;v=0002/")


def test_compiler_uses_unquoted_boolean_literals() -> None:
    plan = QueryPlan(
        service_name="API_PURCHASEORDER_PROCESS_SRV",
        entity_set="A_PurchaseOrderItem",
        select_fields=["PurchaseOrder", "PurchaseOrderItem", "GoodsReceiptIsExpected"],
        filters=[
            FilterCondition(
                field="GoodsReceiptIsExpected",
                operator="eq",
                value="true",
                value_type="Edm.Boolean",
            )
        ],
        top=50,
    )

    compiled = BasicODataCompiler(base_url="https://sap.example.com").compile(plan)

    assert "GoodsReceiptIsExpected eq true" in compiled.url
    assert "GoodsReceiptIsExpected eq 'true'" not in compiled.url


def test_compiler_uses_odata_v2_datetime_literal_for_date_values() -> None:
    plan = QueryPlan(
        service_name="API_PURCHASEORDER_PROCESS_SRV",
        entity_set="A_PurchaseOrderScheduleLine",
        select_fields=["PurchasingDocument", "ScheduleLineDeliveryDate"],
        filters=[
            FilterCondition(
                field="ScheduleLineDeliveryDate",
                operator="eq",
                value="2018-11-23",
                value_type="Edm.DateTime",
            )
        ],
        top=1,
    )

    compiled = BasicODataCompiler(base_url="https://sap.example.com").compile(plan)

    assert "ScheduleLineDeliveryDate eq datetime'2018-11-23T00:00:00'" in compiled.url
    assert "ScheduleLineDeliveryDate eq '2018-11-23'" not in compiled.url


def test_compiler_normalizes_dotted_dates_for_datetime_filters() -> None:
    plan = QueryPlan(
        service_name="API_PURCHASEORDER_PROCESS_SRV",
        entity_set="A_PurchaseOrderScheduleLine",
        select_fields=["PurchasingDocument", "ScheduleLineDeliveryDate"],
        filters=[
            FilterCondition(
                field="ScheduleLineDeliveryDate",
                operator="eq",
                value="2018.11.23",
                value_type="date",
            )
        ],
        top=1,
    )

    compiled = BasicODataCompiler(base_url="https://sap.example.com").compile(plan)

    assert "ScheduleLineDeliveryDate eq datetime'2018-11-23T00:00:00'" in compiled.url


def test_compiler_does_not_quote_llm_supplied_datetime_wrapper() -> None:
    plan = QueryPlan(
        service_name="API_PURCHASEORDER_PROCESS_SRV",
        entity_set="A_PurchaseOrderScheduleLine",
        select_fields=["PurchasingDocument", "ScheduleLineDeliveryDate"],
        filters=[
            FilterCondition(
                field="ScheduleLineDeliveryDate",
                operator="eq",
                value="datetime'2018-11-23'",
                value_type="date",
            )
        ],
        top=1,
    )

    compiled = BasicODataCompiler(base_url="https://sap.example.com").compile(plan)

    assert "ScheduleLineDeliveryDate eq datetime'2018-11-23T00:00:00'" in compiled.url
    assert "'datetime''2018-11-23'''" not in compiled.url


def test_compiler_builds_function_import_url_without_system_query_options() -> None:
    plan = QueryPlan(
        service_name="API_PRODUCT_AVAILY_INFO_BASIC",
        entity_set="DetermineAvailabilityAt",
        plan_kind="function_import",
        function_parameters=[
            FunctionParameter(name="Material", value="TG0011", value_type="string"),
            FunctionParameter(name="SupplyingPlant", value="1710", value_type="string"),
            FunctionParameter(name="ATPCheckingRule", value="A", value_type="string"),
            FunctionParameter(name="RequestedUTCDateTime", value="2026.04.29", value_type="datetimeoffset"),
        ],
        top=50,
    )

    compiled = BasicODataCompiler(base_url="https://sap.example.com").compile(plan)

    assert compiled.url.startswith(
        "https://sap.example.com/sap/opu/odata/sap/API_PRODUCT_AVAILY_INFO_BASIC/DetermineAvailabilityAt?"
    )
    assert "Material='TG0011'" in compiled.url
    assert "SupplyingPlant='1710'" in compiled.url
    assert "ATPCheckingRule='A'" in compiled.url
    assert "RequestedUTCDateTime=datetimeoffset'2026-04-29T00:00:00Z'" in compiled.url
    assert "$top" not in compiled.url
    assert "$filter" not in compiled.url
    assert "$select" not in compiled.url
    assert "$inlinecount" not in compiled.url


def test_compiler_uses_decimal_literal_for_function_import_quantity() -> None:
    plan = QueryPlan(
        service_name="API_PRODUCT_AVAILY_INFO_BASIC",
        entity_set="DetermineAvailabilityOf",
        plan_kind="function_import",
        function_parameters=[
            FunctionParameter(name="RequestedQuantityInBaseUnit", value="10", value_type="decimal"),
        ],
    )

    compiled = BasicODataCompiler(base_url="https://sap.example.com").compile(plan)

    assert "RequestedQuantityInBaseUnit=10M" in compiled.url
    assert "RequestedQuantityInBaseUnit='10'" not in compiled.url
