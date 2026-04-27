from sap_odata_agent.domain.models import FilterCondition, QueryPlan
from sap_odata_agent.infrastructure.sap.odata_client import BasicODataCompiler, BasicPlanValidator


def test_validator_blocks_unknown_service() -> None:
    plan = QueryPlan(service_name="UNKNOWN_SERVICE", entity_set="A_Test")
    issues = BasicPlanValidator().validate(plan)
    assert any(issue.field == "service_name" for issue in issues)


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
