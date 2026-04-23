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
