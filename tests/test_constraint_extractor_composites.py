from sap_odata_agent.domain.models import CardinalityPolicy, QueryShape
from sap_odata_agent.infrastructure.llm.constraint_extractor import QueryConstraintExtractor


def test_unmodified_base_field_does_not_require_composite_business_partner_fields() -> None:
    extractor = QueryConstraintExtractor()
    constraints = extractor.extract(
        "查询客户300001的业务伙伴",
        QueryShape.SINGLE_FACT,
        CardinalityPolicy.ONE,
        candidate_fields=[
            {
                "entity_set": "A_BusinessPartner",
                "field_name": "BusinessPartner",
                "label": "业务伙伴",
                "description": "业务伙伴编号",
            },
            {
                "entity_set": "A_BPContactToAddress",
                "field_name": "BusinessPartnerCompany",
                "label": "业务伙伴",
                "description": "业务伙伴编号",
            },
            {
                "entity_set": "A_BPContactToAddress",
                "field_name": "BusinessPartnerPerson",
                "label": "业务伙伴",
                "description": "业务伙伴编号",
            },
            {
                "entity_set": "A_BusinessPartner",
                "field_name": "Customer",
                "label": "客户",
                "description": "客户编号",
            },
        ],
    )

    assert constraints.target_object == "customer"
    assert constraints.target_field_concepts == ["BusinessPartner"]
    assert constraints.filter_values == ["300001"]


def test_explicit_composite_modifier_can_keep_composite_target() -> None:
    extractor = QueryConstraintExtractor()
    constraints = extractor.extract(
        "查询客户300001的业务伙伴公司",
        QueryShape.SINGLE_FACT,
        CardinalityPolicy.ONE,
        candidate_fields=[
            {
                "entity_set": "A_BusinessPartner",
                "field_name": "BusinessPartner",
                "label": "业务伙伴",
                "description": "业务伙伴编号",
            },
            {
                "entity_set": "A_BPContactToAddress",
                "field_name": "BusinessPartnerCompany",
                "label": "业务伙伴公司",
                "description": "业务伙伴公司编号",
            },
            {
                "entity_set": "A_BusinessPartner",
                "field_name": "Customer",
                "label": "客户",
                "description": "客户编号",
            },
        ],
    )

    assert "BusinessPartnerCompany" in constraints.target_field_concepts
