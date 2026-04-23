import json
from pathlib import Path

from sap_odata_agent.domain.models import AgentRequest, RetrievedContext, RetrievedDocument
from sap_odata_agent.infrastructure.llm.planner import LlmStructuredIntentPlanner


def _write_fixture(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps([{"service_name": "API_TEST", "entity_sets": ["A_Supplier", "A_SupplierCompany"]}]),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Supplier",
                    "entity_type": "A_SupplierType",
                    "key_fields": ["Supplier"],
                    "default_select_fields": ["Supplier", "SupplierName"],
                    "supported_methods": ["GET"],
                    "description": "Supplier header data",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierCompany",
                    "entity_type": "A_SupplierCompanyType",
                    "key_fields": ["Supplier", "CompanyCode"],
                    "default_select_fields": ["Supplier", "CompanyCode", "PaymentTerms"],
                    "supported_methods": ["GET"],
                    "description": "Supplier company data",
                },
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "fields.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Supplier",
                    "field_name": "Supplier",
                    "description": "Supplier id",
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Supplier",
                    "field_name": "SupplierName",
                    "description": "Supplier name",
                    "filterable": False,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierCompany",
                    "field_name": "Supplier",
                    "description": "Supplier id",
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierCompany",
                    "field_name": "CompanyCode",
                    "description": "Company code",
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierCompany",
                    "field_name": "PaymentTerms",
                    "description": "Payment terms",
                    "filterable": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "relations.json").write_text("[]", encoding="utf-8")
    (service_dir / "business_terms.json").write_text("[]", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


class StubClient:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        return self.response_text


class SequenceStubClient:
    def __init__(self, response_texts: list[str]) -> None:
        self.response_texts = response_texts
        self.calls = 0

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        index = min(self.calls, len(self.response_texts) - 1)
        self.calls += 1
        return self.response_texts[index]


def test_llm_planner_prefers_specific_entity_for_payment_terms(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    planner = LlmStructuredIntentPlanner(
        index_root=tmp_path,
        service_name="API_TEST",
        llm_client=StubClient(
            json.dumps(
                {
                    "entity_set": "A_SupplierCompany",
                    "http_method": "GET",
                    "select_fields": ["Supplier", "CompanyCode", "PaymentTerms"],
                    "response_summary_fields": ["CompanyCode", "PaymentTerms"],
                    "filters": [{"field": "Supplier", "operator": "eq", "value": "17300003"}],
                    "requires_confirmation": False,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "clarification_options": [],
                    "response_directive": "Answer with the payment terms and company code.",
                    "rationale": "PaymentTerms is available on A_SupplierCompany.",
                }
            )
        ),
    )
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_Supplier",
                content="Supplier header",
                score=8.0,
                metadata={"entity_set": "A_Supplier"},
            ),
            RetrievedDocument(
                source="field",
                title="A_SupplierCompany.PaymentTerms",
                content="Payment terms",
                score=12.0,
                metadata={"entity_set": "A_SupplierCompany", "field_name": "PaymentTerms"},
            ),
        ]
    )

    plan = planner.plan(AgentRequest(user_input="供应商17300003的付款条件是什么"), context)

    assert plan.entity_set == "A_SupplierCompany"
    assert "PaymentTerms" in plan.select_fields
    assert plan.response_summary_fields == ["CompanyCode", "PaymentTerms"]
    assert plan.response_directive == "Answer with the payment terms and company code."
    assert plan.filters[0].field == "Supplier"
    assert plan.planner_diagnostics["planner_winner"] == "llm"
    assert plan.planner_diagnostics["fallback_plan_snapshot"]["entity_set"] == "A_SupplierCompany"
    assert plan.planner_diagnostics["llm_plan_snapshot"]["entity_set"] == "A_SupplierCompany"


def test_llm_planner_falls_back_when_json_is_invalid(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    planner = LlmStructuredIntentPlanner(
        index_root=tmp_path,
        service_name="API_TEST",
        llm_client=StubClient("not-json"),
    )
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_Supplier",
                content="Supplier header",
                score=8.0,
                metadata={"entity_set": "A_Supplier"},
            )
        ]
    )

    plan = planner.plan(AgentRequest(user_input="查询供应商17300003的基本信息"), context)

    assert plan.entity_set == "A_Supplier"
    assert plan.service_name == "API_TEST"


def test_llm_planner_repairs_invalid_json_once_before_fallback(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    planner = LlmStructuredIntentPlanner(
        index_root=tmp_path,
        service_name="API_TEST",
        llm_client=SequenceStubClient(
            [
                '{"entity_set":"A_SupplierCompany","http_method":"GET","select_fields":["Supplier","CompanyCode","PaymentTerms"],',
                json.dumps(
                    {
                        "entity_set": "A_SupplierCompany",
                        "http_method": "GET",
                        "select_fields": ["Supplier", "CompanyCode", "PaymentTerms"],
                        "response_summary_fields": ["CompanyCode", "PaymentTerms"],
                        "filters": [{"field": "Supplier", "operator": "eq", "value": "17300003"}],
                        "requires_confirmation": False,
                        "needs_clarification": False,
                        "clarification_question": "",
                        "clarification_options": [],
                        "response_directive": "Answer with the payment terms and company code.",
                        "rationale": "PaymentTerms is available on A_SupplierCompany.",
                    }
                ),
            ]
        ),
    )
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_SupplierCompany",
                content="Supplier company",
                score=10.0,
                metadata={"entity_set": "A_SupplierCompany"},
            ),
            RetrievedDocument(
                source="field",
                title="A_SupplierCompany.PaymentTerms",
                content="Payment terms",
                score=12.0,
                metadata={"entity_set": "A_SupplierCompany", "field_name": "PaymentTerms"},
            ),
        ]
    )

    plan = planner.plan(AgentRequest(user_input="供应商17300003的付款条件是什么"), context)

    assert plan.entity_set == "A_SupplierCompany"
    assert plan.filters[0].field == "Supplier"
    assert "PaymentTerms" in plan.select_fields


def test_llm_planner_retries_when_first_response_is_empty(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    planner = LlmStructuredIntentPlanner(
        index_root=tmp_path,
        service_name="API_TEST",
        llm_client=SequenceStubClient(
            [
                "",
                json.dumps(
                    {
                        "entity_set": "A_SupplierCompany",
                        "http_method": "GET",
                        "select_fields": ["Supplier", "CompanyCode", "PaymentTerms"],
                        "response_summary_fields": ["CompanyCode", "PaymentTerms"],
                        "filters": [{"field": "Supplier", "operator": "eq", "value": "17300003"}],
                        "requires_confirmation": False,
                        "needs_clarification": False,
                        "clarification_question": "",
                        "clarification_options": [],
                        "response_directive": "Answer with the payment terms and company code.",
                        "rationale": "PaymentTerms is available on A_SupplierCompany.",
                    }
                ),
            ]
        ),
    )
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_SupplierCompany",
                content="Supplier company",
                score=10.0,
                metadata={"entity_set": "A_SupplierCompany"},
            ),
            RetrievedDocument(
                source="field",
                title="A_SupplierCompany.PaymentTerms",
                content="Payment terms",
                score=12.0,
                metadata={"entity_set": "A_SupplierCompany", "field_name": "PaymentTerms"},
            ),
        ]
    )

    plan = planner.plan(AgentRequest(user_input="供应商17300003的付款条件是什么"), context)

    assert plan.entity_set == "A_SupplierCompany"
    assert plan.response_summary_fields == ["CompanyCode", "PaymentTerms"]


def test_llm_planner_can_request_clarification_for_ambiguous_context(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    planner = LlmStructuredIntentPlanner(
        index_root=tmp_path,
        service_name="API_TEST",
        llm_client=StubClient(
            json.dumps(
                {
                    "entity_set": "A_SupplierCompany",
                    "http_method": "GET",
                    "select_fields": ["Supplier", "CompanyCode", "PaymentTerms"],
                    "response_summary_fields": [],
                    "filters": [{"field": "Supplier", "operator": "eq", "value": "17300003"}],
                    "requires_confirmation": False,
                    "needs_clarification": True,
                    "clarification_question": "你要看公司代码层面的付款条件，还是采购组织层面的付款条件？",
                    "clarification_options": ["公司代码层面", "采购组织层面"],
                    "response_directive": "Ask the user to clarify the business context before querying SAP.",
                    "rationale": "PaymentTerms exists in more than one supplier context.",
                }
            )
        ),
    )
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_SupplierCompany",
                content="Supplier company data",
                score=11.0,
                metadata={"entity_set": "A_SupplierCompany"},
            ),
            RetrievedDocument(
                source="field",
                title="A_SupplierCompany.PaymentTerms",
                content="Payment terms",
                score=12.0,
                metadata={"entity_set": "A_SupplierCompany", "field_name": "PaymentTerms"},
            ),
        ]
    )

    plan = planner.plan(AgentRequest(user_input="供应商17300003的付款条件是什么"), context)

    assert plan.needs_clarification is True
    assert plan.clarification_question is not None
    assert plan.clarification_options == ["公司代码层面", "采购组织层面"]


def test_llm_planner_falls_back_when_llm_ignores_strong_answer_field(tmp_path: Path) -> None:
    service_dir = tmp_path / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps([{"service_name": "API_TEST", "entity_sets": ["A_SupplierPurchasingOrg", "A_CustomerSalesArea"]}]),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "entity_type": "A_SupplierPurchasingOrgType",
                    "key_fields": ["Supplier", "PurchasingOrganization"],
                    "default_select_fields": ["Supplier", "PurchasingOrganization", "ShippingCondition"],
                    "supported_methods": ["GET"],
                    "description": "Supplier purchasing org data",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_CustomerSalesArea",
                    "entity_type": "A_CustomerSalesAreaType",
                    "key_fields": ["Customer", "SalesOrganization"],
                    "default_select_fields": ["Customer", "SalesOrganization", "IncotermsClassification"],
                    "supported_methods": ["GET"],
                    "description": "Customer sales area data",
                },
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "fields.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "Supplier",
                    "description": "Supplier id",
                    "filterable": True,
                    "business_aliases": ["供应商"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "PurchasingOrganization",
                    "description": "Purchasing organization",
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "ShippingCondition",
                    "description": "Shipping condition",
                    "filterable": True,
                    "business_aliases": ["shipping condition", "装运条件"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_CustomerSalesArea",
                    "field_name": "Customer",
                    "description": "Customer id",
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_CustomerSalesArea",
                    "field_name": "IncotermsClassification",
                    "description": "Incoterms",
                    "filterable": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "relations.json").write_text("[]", encoding="utf-8")
    (service_dir / "business_terms.json").write_text("[]", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")

    planner = LlmStructuredIntentPlanner(
        index_root=tmp_path,
        service_name="API_TEST",
        llm_client=StubClient(
            json.dumps(
                {
                    "entity_set": "A_CustomerSalesArea",
                    "http_method": "GET",
                    "select_fields": ["Customer", "IncotermsClassification"],
                    "response_summary_fields": ["IncotermsClassification"],
                    "filters": [{"field": "Customer", "operator": "eq", "value": "17300003"}],
                    "requires_confirmation": False,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "clarification_options": [],
                    "response_directive": "Answer with Incoterms.",
                    "rationale": "Wrong answer on purpose for guardrail test.",
                }
            )
        ),
    )
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_SupplierPurchasingOrg",
                content="Supplier purchasing org",
                score=12.0,
                metadata={"entity_set": "A_SupplierPurchasingOrg"},
            ),
            RetrievedDocument(
                source="field",
                title="A_SupplierPurchasingOrg.ShippingCondition",
                content="Shipping condition",
                score=20.0,
                metadata={"entity_set": "A_SupplierPurchasingOrg", "field_name": "ShippingCondition"},
            ),
        ]
    )

    plan = planner.plan(AgentRequest(user_input="供应商17300003的shipping conditon是什么？"), context)

    assert plan.entity_set == "A_SupplierPurchasingOrg"
    assert "ShippingCondition" in plan.select_fields
    assert plan.planner_diagnostics["planner_winner"] == "fallback"
    assert plan.planner_diagnostics["llm_adjudication"]["accepted"] is False
    assert "strong_answer_field_ignored_by_llm" in plan.planner_diagnostics["llm_adjudication"]["reasons"]
