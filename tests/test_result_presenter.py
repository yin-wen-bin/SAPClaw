import json

from sap_odata_agent.domain.models import AgentRequest, CardinalityPolicy, QueryConstraints, QueryPlan, QueryShape
from sap_odata_agent.infrastructure.llm.result_presenter import LlmResultPresenter


class StubClient:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        return self.response_text


def test_result_presenter_falls_back_to_text_for_single_record() -> None:
    presenter = LlmResultPresenter(enabled=False)
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_SupplierPurchasingOrg",
        select_fields=["Supplier", "PurchasingOrganization", "PaymentTerms"],
        response_summary_fields=["PurchasingOrganization", "PaymentTerms"],
    )
    data = {
        "result_count": 1,
        "results": [
            {
                "Supplier": "17300003",
                "PurchasingOrganization": "1710",
                "PaymentTerms": "0001",
            }
        ],
    }

    presentation = presenter.present(AgentRequest(user_input="供应商17300003的付款条件是什么？"), plan, data)

    assert presentation.kind == "text"
    assert "PaymentTerms为0001" in presentation.text


def test_result_presenter_uses_table_when_llm_requests_it() -> None:
    presenter = LlmResultPresenter(
        llm_client=StubClient(
            json.dumps(
                {
                    "kind": "table",
                    "title": "供应商列表",
                    "text": "以下是付款条件为0001的供应商列表。",
                    "columns": ["Supplier", "SupplierName", "PaymentTerms"],
                    "rows": [
                        {"Supplier": "17300003", "SupplierName": "Vendor A", "PaymentTerms": "0001"},
                        {"Supplier": "17300004", "SupplierName": "Vendor B", "PaymentTerms": "0001"},
                    ],
                }
            )
        )
    )
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_SupplierCompany",
        select_fields=["Supplier", "SupplierName", "PaymentTerms"],
        response_summary_fields=["Supplier", "SupplierName", "PaymentTerms"],
    )
    data = {
        "result_count": 2,
        "results": [
            {"Supplier": "17300003", "SupplierName": "Vendor A", "PaymentTerms": "0001"},
            {"Supplier": "17300004", "SupplierName": "Vendor B", "PaymentTerms": "0001"},
        ],
    }

    presentation = presenter.present(AgentRequest(user_input="付款条件为0001的供应商有哪些？"), plan, data)

    assert presentation.kind == "table"
    assert presentation.columns == ["Supplier", "SupplierName", "PaymentTerms"]
    assert len(presentation.rows) == 2


def test_result_presenter_filters_target_object_rows_and_recovers_from_empty_llm_rows() -> None:
    presenter = LlmResultPresenter(
        llm_client=StubClient(
            json.dumps(
                {
                    "kind": "table",
                    "title": "\u4f9b\u5e94\u5546\u5217\u8868",
                    "text": "\u5728\u5730\u533aHH\u5171\u67092\u4e2a\u4f9b\u5e94\u5546\u3002",
                    "columns": ["\u4e1a\u52a1\u4f19\u4f34\u7f16\u53f7", "\u4f9b\u5e94\u5546\u7f16\u53f7", "\u5b8c\u6574\u540d\u79f0"],
                    "rows": [
                        {"\u4e1a\u52a1\u4f19\u4f34\u7f16\u53f7": "", "\u4f9b\u5e94\u5546\u7f16\u53f7": "", "\u5b8c\u6574\u540d\u79f0": ""},
                        {"\u4e1a\u52a1\u4f19\u4f34\u7f16\u53f7": "", "\u4f9b\u5e94\u5546\u7f16\u53f7": "", "\u5b8c\u6574\u540d\u79f0": ""},
                    ],
                }
            )
        )
    )
    request = AgentRequest(
        user_input="\u67e5\u627e\u5730\u533a\u4e3aHH\u7684\u4f9b\u5e94\u5546",
        constraints=QueryConstraints(
            query_shape=QueryShape.SEARCH_BY_ATTRIBUTE,
            cardinality=CardinalityPolicy.MANY,
            target_object="supplier",
            filter_concepts=["Region"],
            filter_values=["HH"],
        ),
    )
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_BusinessPartner",
        select_fields=["BusinessPartner", "Supplier", "Customer", "BusinessPartnerFullName"],
        response_summary_fields=["BusinessPartner", "Supplier", "BusinessPartnerFullName"],
    )
    data = {
        "result_count": 3,
        "results": [
            {"BusinessPartner": "10100006", "Supplier": "", "Customer": "10100006", "BusinessPartnerFullName": "Customer"},
            {"BusinessPartner": "10300006", "Supplier": "10300006", "Customer": "", "BusinessPartnerFullName": "Vendor A"},
            {"BusinessPartner": "10386301", "Supplier": "10386301", "Customer": "", "BusinessPartnerFullName": "Vendor B"},
        ],
    }

    presentation = presenter.present(request, plan, data)

    assert presentation.kind == "table"
    assert presentation.text == "\u67e5\u8be2\u7ed3\u679c\u603b\u51712\u6761\uff0c\u5f53\u524d\u663e\u793a\u524d2\u6761"
    assert presentation.columns == ["BusinessPartner", "Supplier", "BusinessPartnerFullName"]
    assert presentation.rows == [
        {"BusinessPartner": "10300006", "Supplier": "10300006", "BusinessPartnerFullName": "Vendor A"},
        {"BusinessPartner": "10386301", "Supplier": "10386301", "BusinessPartnerFullName": "Vendor B"},
    ]


def test_result_presenter_uses_total_count_separate_from_displayed_rows() -> None:
    presenter = LlmResultPresenter(enabled=False)
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_Test",
        select_fields=["ObjectId"],
        response_summary_fields=["ObjectId"],
    )
    data = {
        "result_count": 80,
        "displayed_count": 50,
        "results": [{"ObjectId": str(index)} for index in range(50)],
        "pagination": {"skip": 0, "page_size": 50, "has_next": True, "next_skip": 50},
    }

    presentation = presenter.present(AgentRequest(user_input="查询对象列表"), plan, data)

    assert presentation.text == "查询结果总共80条，当前显示前50条"
    assert len(presentation.rows) == 50


def test_result_presenter_formats_sap_json_dates_for_display() -> None:
    presenter = LlmResultPresenter(enabled=False)
    plan = QueryPlan(
        service_name="API_PURCHASEORDER_PROCESS_SRV",
        entity_set="A_PurchaseOrderScheduleLine",
        select_fields=[
            "PurchasingDocument",
            "PurchasingDocumentItem",
            "ScheduleLine",
            "ScheduleLineDeliveryDate",
        ],
        response_summary_fields=[
            "PurchasingDocument",
            "PurchasingDocumentItem",
            "ScheduleLine",
            "ScheduleLineDeliveryDate",
        ],
    )
    data = {
        "result_count": 2,
        "results": [
            {
                "PurchasingDocument": "4500000468",
                "PurchasingDocumentItem": "10",
                "ScheduleLine": "1",
                "ScheduleLineDeliveryDate": "/Date(1777852800000)/",
            },
            {
                "PurchasingDocument": "4500000469",
                "PurchasingDocumentItem": "10",
                "ScheduleLine": "1",
                "ScheduleLineDeliveryDate": "Date(1777852800000)",
            }
        ],
    }

    presentation = presenter.present(AgentRequest(user_input="查询采购订单交货日期"), plan, data)

    assert presentation.rows[0]["ScheduleLineDeliveryDate"] == "2026.05.04"
    assert "/Date(" not in presentation.rows[0]["ScheduleLineDeliveryDate"]


def test_result_presenter_falls_back_to_yes_no_for_boolean_question() -> None:
    presenter = LlmResultPresenter(enabled=False)
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_SupplierPurchasingOrg",
        select_fields=["Supplier", "PurchasingOrganization", "InvoiceIsGoodsReceiptBased"],
        response_summary_fields=["PurchasingOrganization", "InvoiceIsGoodsReceiptBased"],
    )
    data = {
        "result_count": 1,
        "results": [
            {
                "Supplier": "17300003",
                "PurchasingOrganization": "1710",
                "InvoiceIsGoodsReceiptBased": True,
            }
        ],
    }

    presentation = presenter.present(AgentRequest(user_input="供应商17300003是基于收货的发票校验吗？"), plan, data)

    assert presentation.kind == "text"
    assert "：是。" in presentation.text
    assert "Supplier=17300003" in presentation.text
