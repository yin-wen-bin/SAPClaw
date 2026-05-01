import json
import urllib.error
import urllib.parse

from sap_odata_agent.domain.models import CompiledRequest, ExecutionStep, FilterCondition, QueryPlan, StepBinding

from sap_odata_agent.infrastructure.sap.odata_client import (
    BasicODataCompiler,
    MultiStepSapExecutor,
    SapODataExecutor,
    SapRuntimeConfig,
)


def _build_executor() -> SapODataExecutor:
    return SapODataExecutor(
        SapRuntimeConfig(
            base_url="https://sap.example.com",
            username="user",
            password="pass",
            client="100",
            verify_ssl=True,
            auth_type="basic",
            timeout_seconds=30,
        )
    )


def test_prepare_runtime_url_appends_client_and_json_format() -> None:
    executor = _build_executor()
    prepared = executor._prepare_runtime_url("https://sap.example.com/sap/opu/odata/sap/API_TEST/A_Customer?$top=1")

    assert "sap-client=100" in prepared
    assert "$format=json" in prepared
    assert "$inlinecount=allpages" in prepared
    assert "$top=1" in prepared


def test_executor_returns_preview_for_json_results() -> None:
    class StubExecutor(SapODataExecutor):
        def _perform_request(self, compiled_request: CompiledRequest) -> dict[str, str | int]:
            return {
                "status_code": 200,
                "content_type": "application/json",
                "body": '{"d":{"__count":"12","results":[{"Customer":"1000001"},{"Customer":"1000002"}]}}',
            }

    executor = StubExecutor(_build_executor().config)
    attempt = executor.execute(
        CompiledRequest(method="GET", url="https://sap.example.com/sap/opu/odata/sap/API_TEST/A_Customer?$top=2"),
        attempt_number=1,
    )

    assert attempt.success is True
    assert attempt.status_code == 200
    assert attempt.response_preview["result_count"] == 12
    assert attempt.response_preview["returned_count"] == 2
    assert attempt.response_preview["displayed_count"] == 2
    assert len(attempt.response_preview["_all_results"]) == 2
    assert attempt.response_preview["_result_window_start"] == 0
    assert attempt.response_preview["pagination"]["has_next"] is True
    assert attempt.response_preview["pagination"]["next_skip"] == 2
    assert attempt.response_preview["results"][0]["Customer"] == "1000001"


def test_executor_marks_next_page_when_more_rows_returned_than_display_limit() -> None:
    class StubExecutor(SapODataExecutor):
        def _perform_request(self, compiled_request: CompiledRequest) -> dict[str, str | int]:
            rows = [{"ObjectId": str(index)} for index in range(71)]
            return {
                "status_code": 200,
                "content_type": "application/json",
                "body": json.dumps({"d": {"__count": "71", "results": rows}}),
            }

    executor = StubExecutor(_build_executor().config)
    attempt = executor.execute(
        CompiledRequest(method="GET", url="https://sap.example.com/sap/opu/odata/sap/API_TEST/A_Test?$top=100"),
        attempt_number=1,
    )

    assert attempt.success is True
    assert attempt.response_preview["result_count"] == 71
    assert attempt.response_preview["returned_count"] == 71
    assert attempt.response_preview["displayed_count"] == 50
    assert len(attempt.response_preview["results"]) == 50
    assert len(attempt.response_preview["_all_results"]) == 71
    assert attempt.response_preview["pagination"]["page_size"] == 100
    assert attempt.response_preview["pagination"]["display_limit"] == 50
    assert attempt.response_preview["pagination"]["has_next"] is True
    assert attempt.response_preview["pagination"]["next_skip"] == 50


def test_executor_retries_transient_url_error() -> None:
    class FlakyExecutor(SapODataExecutor):
        def __init__(self, config: SapRuntimeConfig) -> None:
            super().__init__(config)
            self.calls = 0

        def _perform_request(self, compiled_request: CompiledRequest) -> dict[str, str | int]:
            self.calls += 1
            if self.calls == 1:
                raise urllib.error.URLError(ConnectionRefusedError(10061, "connection refused"))
            return {
                "status_code": 200,
                "content_type": "application/json",
                "body": '{"d":{"results":[{"Customer":"1000001"}]}}',
            }

    config = _build_executor().config
    config.retry_attempts = 2
    config.retry_delay_seconds = 0
    executor = FlakyExecutor(config)

    attempt = executor.execute(
        CompiledRequest(method="GET", url="https://sap.example.com/sap/opu/odata/sap/API_TEST/A_Customer?$top=1"),
        attempt_number=1,
    )

    assert attempt.success is True
    assert executor.calls == 2
    assert attempt.response_preview["results"][0]["Customer"] == "1000001"


def test_executor_rejects_non_get_requests() -> None:
    executor = _build_executor()
    attempt = executor.execute(
        CompiledRequest(
            method="PATCH",
            url="https://sap.example.com/sap/opu/odata/sap/API_TEST/A_Customer('1000001')",
            payload={"CustomerName": "New Name"},
        ),
        attempt_number=1,
    )

    assert attempt.success is False
    assert "Only GET requests" in (attempt.error_message or "")


def test_extract_error_message_from_xml_body() -> None:
    executor = _build_executor()
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<error xmlns="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
        '<code>/IWFND/MED/170</code>'
        '<message xml:lang="zh">未找到服务</message>'
        "</error>"
    )

    assert executor._extract_error_message(body, "application/xml") == "未找到服务"


def test_multi_step_executor_passes_previous_step_value_into_next_filter() -> None:
    class StubExecutor(SapODataExecutor):
        def _perform_request(self, compiled_request: CompiledRequest) -> dict[str, str | int]:
            if "A_BusinessPartner?" in compiled_request.url:
                assert "Supplier+eq+'643266'" in compiled_request.url
                return {
                    "status_code": 200,
                    "content_type": "application/json",
                    "body": '{"d":{"results":[{"BusinessPartner":"9000000024","Supplier":"643266"}]}}',
                }
            assert "A_BusinessPartnerAddress?" in compiled_request.url
            assert "BusinessPartner+eq+'9000000024'" in compiled_request.url
            return {
                "status_code": 200,
                "content_type": "application/json",
                "body": '{"d":{"results":[{"BusinessPartner":"9000000024","PostalCode":"94030","CityName":"Palo Alto"}]}}',
            }

    executor = StubExecutor(_build_executor().config)
    compiler = BasicODataCompiler(base_url="https://sap.example.com")
    multi_step = MultiStepSapExecutor(compiler=compiler, executor=executor)
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_BusinessPartnerAddress",
        plan_kind="multi_step",
        anchor_object="Supplier",
        anchor_value="643266",
        target_field="PostalCode",
        target_entity_set="A_BusinessPartnerAddress",
        path_id="supplier_to_postal_code",
        steps=[
            ExecutionStep(
                step_id="resolve_business_partner",
                entity_set="A_BusinessPartner",
                select_fields=["BusinessPartner", "Supplier"],
                filters=[FilterCondition(field="Supplier", operator="eq", value="643266")],
                top=1,
            ),
            ExecutionStep(
                step_id="fetch_address",
                entity_set="A_BusinessPartnerAddress",
                select_fields=["BusinessPartner", "PostalCode", "CityName"],
                filter_from_previous=[
                    StepBinding(
                        field="BusinessPartner",
                        source_step_id="resolve_business_partner",
                        source_field="BusinessPartner",
                    )
                ],
                top=5,
            ),
        ],
    )

    attempts, data = multi_step.execute_plan(plan, starting_attempt_number=1)

    assert len(attempts) == 2
    assert attempts[0].success is True
    assert attempts[1].success is True
    assert data is not None
    assert data["results"][0]["PostalCode"] == "94030"
    assert data["lookup_context"]["path_id"] == "supplier_to_postal_code"
    assert data["primary_entity_set"] == "A_BusinessPartnerAddress"
    assert "resolve_business_partner" in data["step_results"]
    assert "fetch_address" in data["step_results"]


def test_multi_step_executor_uses_step_level_service_names() -> None:
    class StubExecutor(SapODataExecutor):
        def _perform_request(self, compiled_request: CompiledRequest) -> dict[str, str | int]:
            decoded_url = urllib.parse.unquote_plus(compiled_request.url)
            if "API_COMPANYCODE_SRV/A_CompanyCode?" in compiled_request.url:
                assert "CompanyCode eq '1710'" in decoded_url
                return {
                    "status_code": 200,
                    "content_type": "application/json",
                    "body": '{"d":{"results":[{"CompanyCode":"1710","ChartOfAccounts":"YCOA"}]}}',
                }

            assert "API_GLACCOUNTINCHARTOFACCOUNTS_SRV/A_GLAccountInChartOfAccounts?" in compiled_request.url
            assert "ChartOfAccounts eq 'YCOA'" in decoded_url
            assert "IsBalanceSheetAccount eq false" in decoded_url
            return {
                "status_code": 200,
                "content_type": "application/json",
                "body": (
                    '{"d":{"results":[{"ChartOfAccounts":"YCOA","GLAccount":"61000000",'
                    '"IsBalanceSheetAccount":false,"ProfitLossAccountType":"EXP"}]}}'
                ),
            }

    executor = StubExecutor(_build_executor().config)
    compiler = BasicODataCompiler(base_url="https://sap.example.com")
    multi_step = MultiStepSapExecutor(compiler=compiler, executor=executor)
    plan = QueryPlan(
        service_name="API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
        entity_set="A_GLAccountInChartOfAccounts",
        plan_kind="multi_step",
        target_entity_set="A_GLAccountInChartOfAccounts",
        steps=[
            ExecutionStep(
                step_id="resolve_chart",
                service_name="API_COMPANYCODE_SRV",
                entity_set="A_CompanyCode",
                select_fields=["CompanyCode", "ChartOfAccounts"],
                filters=[FilterCondition(field="CompanyCode", operator="eq", value="1710")],
                top=1,
            ),
            ExecutionStep(
                step_id="fetch_gl_accounts",
                service_name="API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
                entity_set="A_GLAccountInChartOfAccounts",
                select_fields=["ChartOfAccounts", "GLAccount", "IsBalanceSheetAccount", "ProfitLossAccountType"],
                filters=[
                    FilterCondition(
                        field="IsBalanceSheetAccount",
                        operator="eq",
                        value="false",
                        value_type="Edm.Boolean",
                    )
                ],
                filter_from_previous=[
                    StepBinding(
                        field="ChartOfAccounts",
                        source_step_id="resolve_chart",
                        source_field="ChartOfAccounts",
                    )
                ],
                top=50,
            ),
        ],
    )

    attempts, data = multi_step.execute_plan(plan, starting_attempt_number=1)

    assert len(attempts) == 2
    assert attempts[0].request.url.startswith(
        "https://sap.example.com/sap/opu/odata/sap/API_COMPANYCODE_SRV/A_CompanyCode?"
    )
    assert attempts[1].request.url.startswith(
        "https://sap.example.com/sap/opu/odata/sap/API_GLACCOUNTINCHARTOFACCOUNTS_SRV/A_GLAccountInChartOfAccounts?"
    )
    assert data is not None
    assert data["execution_trace"][0]["service_name"] == "API_COMPANYCODE_SRV"
    assert data["execution_trace"][1]["service_name"] == "API_GLACCOUNTINCHARTOFACCOUNTS_SRV"
    assert data["results"][0]["GLAccount"] == "61000000"


def test_multi_step_executor_expands_multiple_previous_values_into_in_filter() -> None:
    class StubExecutor(SapODataExecutor):
        def _perform_request(self, compiled_request: CompiledRequest) -> dict[str, str | int]:
            if "A_BusinessPartnerAddress?" in compiled_request.url:
                return {
                    "status_code": 200,
                    "content_type": "application/json",
                    "body": '{"d":{"results":[{"BusinessPartner":"9000000024","CityName":"San Diego"},{"BusinessPartner":"9000000025","CityName":"San Diego"}]}}',
                }
            assert "A_BusinessPartner?" in compiled_request.url
            assert "BusinessPartner+eq+'9000000024'" in compiled_request.url
            assert "BusinessPartner+eq+'9000000025'" in compiled_request.url
            return {
                "status_code": 200,
                "content_type": "application/json",
                "body": '{"d":{"results":[{"BusinessPartner":"9000000024","Supplier":"17300003"},{"BusinessPartner":"9000000025","Supplier":"17300004"}]}}',
            }

    executor = StubExecutor(_build_executor().config)
    compiler = BasicODataCompiler(base_url="https://sap.example.com")
    multi_step = MultiStepSapExecutor(compiler=compiler, executor=executor)
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_BusinessPartner",
        plan_kind="multi_step",
        anchor_object="Supplier",
        anchor_value="San Diego",
        target_field="CityName",
        target_entity_set="A_BusinessPartner",
        path_id="supplier_list_by_cityname_via_a_businesspartneraddress",
        steps=[
            ExecutionStep(
                step_id="filter_address",
                entity_set="A_BusinessPartnerAddress",
                select_fields=["BusinessPartner", "CityName"],
                filters=[FilterCondition(field="CityName", operator="eq", value="San Diego")],
                top=50,
            ),
            ExecutionStep(
                step_id="resolve_supplier",
                entity_set="A_BusinessPartner",
                select_fields=["BusinessPartner", "Supplier"],
                filter_from_previous=[
                    StepBinding(
                        field="BusinessPartner",
                        source_step_id="filter_address",
                        source_field="BusinessPartner",
                    )
                ],
                top=50,
            ),
        ],
    )

    attempts, data = multi_step.execute_plan(plan, starting_attempt_number=1)

    assert len(attempts) == 2
    assert attempts[1].success is True
    assert attempts[1].extracted_values["BusinessPartner"] == ["9000000024", "9000000025"]
    assert data is not None
    assert data["result_count"] == 2


def test_multi_step_executor_can_bind_empty_string_key_values() -> None:
    class StubExecutor(SapODataExecutor):
        def _perform_request(self, compiled_request: CompiledRequest) -> dict[str, str | int]:
            decoded_url = urllib.parse.unquote_plus(compiled_request.url)
            if "Batch?" in compiled_request.url:
                return {
                    "status_code": 200,
                    "content_type": "application/json",
                    "body": json.dumps(
                        {
                            "d": {
                                "results": [
                                    {
                                        "Material": "2211",
                                        "BatchIdentifyingPlant": "",
                                        "Batch": "0000000074",
                                    }
                                ]
                            }
                        }
                    ),
                }

            assert "BatchCharc?" in compiled_request.url
            assert "Material eq '2211'" in decoded_url
            assert "Batch eq '0000000074'" in decoded_url
            assert "BatchIdentifyingPlant eq ''" in decoded_url
            return {
                "status_code": 200,
                "content_type": "application/json",
                "body": json.dumps(
                    {
                        "d": {
                            "results": [
                                {
                                    "Material": "2211",
                                    "BatchIdentifyingPlant": "",
                                    "Batch": "0000000074",
                                    "CharcInternalID": "1000",
                                }
                            ]
                        }
                    }
                ),
            }

    executor = StubExecutor(_build_executor().config)
    compiler = BasicODataCompiler(base_url="https://sap.example.com")
    multi_step = MultiStepSapExecutor(compiler=compiler, executor=executor)
    plan = QueryPlan(
        service_name="API_BATCH_SRV",
        entity_set="BatchCharc",
        plan_kind="multi_step",
        target_entity_set="BatchCharc",
        steps=[
            ExecutionStep(
                step_id="step_1",
                entity_set="Batch",
                select_fields=["Material", "BatchIdentifyingPlant", "Batch"],
                top=1,
            ),
            ExecutionStep(
                step_id="step_2",
                entity_set="BatchCharc",
                select_fields=["Material", "BatchIdentifyingPlant", "Batch", "CharcInternalID"],
                filter_from_previous=[
                    StepBinding(field="Material", source_step_id="step_1", source_field="Material"),
                    StepBinding(field="Batch", source_step_id="step_1", source_field="Batch"),
                    StepBinding(
                        field="BatchIdentifyingPlant",
                        source_step_id="step_1",
                        source_field="BatchIdentifyingPlant",
                    ),
                ],
                top=50,
            ),
        ],
    )

    attempts, data = multi_step.execute_plan(plan, starting_attempt_number=1)

    assert len(attempts) == 2
    assert attempts[1].success is True
    assert attempts[1].extracted_values["BatchIdentifyingPlant"] == ""
    assert data is not None
    assert data["results"][0]["CharcInternalID"] == "1000"


def test_multi_step_executor_binds_all_returned_rows_not_display_preview_only() -> None:
    purchase_order_items = [
        {"PurchaseOrder": f"450000{index:04d}", "Material": "TG0011"}
        for index in range(1, 72)
    ]

    class StubExecutor(SapODataExecutor):
        def _perform_request(self, compiled_request: CompiledRequest) -> dict[str, str | int]:
            decoded_url = urllib.parse.unquote_plus(compiled_request.url)
            if "A_PurchaseOrderItem?" in compiled_request.url:
                assert "Material eq 'TG0011'" in decoded_url
                return {
                    "status_code": 200,
                    "content_type": "application/json",
                    "body": json.dumps({"d": {"__count": "71", "results": purchase_order_items}}),
                }

            assert "A_PurchaseOrder?" in compiled_request.url
            assert "PurchaseOrder eq '4500000001'" in decoded_url
            assert "PurchaseOrder eq '4500000071'" in decoded_url
            return {
                "status_code": 200,
                "content_type": "application/json",
                "body": json.dumps(
                    {
                        "d": {
                            "__count": "71",
                            "results": [
                                {"PurchaseOrder": item["PurchaseOrder"], "Supplier": "17300003"}
                                for item in purchase_order_items
                            ],
                        }
                    }
                ),
            }

    executor = StubExecutor(_build_executor().config)
    compiler = BasicODataCompiler(base_url="https://sap.example.com")
    multi_step = MultiStepSapExecutor(compiler=compiler, executor=executor)
    plan = QueryPlan(
        service_name="API_PURCHASEORDER_PROCESS_SRV",
        entity_set="A_PurchaseOrder",
        plan_kind="multi_step",
        path_id="material_to_purchase_orders",
        steps=[
            ExecutionStep(
                step_id="filter_items_by_material",
                entity_set="A_PurchaseOrderItem",
                select_fields=["PurchaseOrder", "Material"],
                filters=[FilterCondition(field="Material", operator="eq", value="TG0011")],
                top=200,
            ),
            ExecutionStep(
                step_id="fetch_purchase_orders",
                entity_set="A_PurchaseOrder",
                select_fields=["PurchaseOrder", "Supplier"],
                filter_from_previous=[
                    StepBinding(
                        field="PurchaseOrder",
                        source_step_id="filter_items_by_material",
                        source_field="PurchaseOrder",
                    )
                ],
                top=200,
            ),
        ],
    )

    attempts, data = multi_step.execute_plan(plan, starting_attempt_number=1)

    assert len(attempts) == 2
    assert attempts[0].response_preview["displayed_count"] == 50
    assert attempts[0].response_preview["returned_count"] == 71
    assert attempts[0].response_preview["pagination"]["has_next"] is True
    assert attempts[0].response_preview["pagination"]["next_skip"] == 50
    assert len(attempts[0].response_preview["results"]) == 50
    assert len(attempts[0].response_preview["_all_results"]) == 71
    assert len(attempts[1].extracted_values["PurchaseOrder"]) == 71
    assert attempts[1].extracted_values["PurchaseOrder"][-1] == "4500000071"
    assert data is not None
    assert data["result_count"] == 71
    assert data["source_step_summaries"][0]["result_count"] == 71


def test_multi_step_executor_keeps_all_step_results_and_uses_target_as_primary() -> None:
    class StubExecutor(SapODataExecutor):
        def _perform_request(self, compiled_request: CompiledRequest) -> dict[str, str | int]:
            if "A_PurchaseOrder?" in compiled_request.url:
                return {
                    "status_code": 200,
                    "content_type": "application/json",
                    "body": json.dumps(
                        {
                            "d": {
                                "__count": "1",
                                "results": [{"PurchaseOrder": "4500001513", "Supplier": "17300003"}],
                            }
                        }
                    ),
                }
            assert "A_PurOrdPricingElement?" in compiled_request.url
            return {
                "status_code": 200,
                "content_type": "application/json",
                "body": json.dumps(
                    {
                        "d": {
                            "__count": "2",
                            "results": [
                                {"PurchaseOrder": "4500001513", "ConditionType": "PBXX"},
                                {"PurchaseOrder": "4500001513", "ConditionType": "DCD1"},
                            ],
                        }
                    }
                ),
            }

    executor = StubExecutor(_build_executor().config)
    compiler = BasicODataCompiler(base_url="https://sap.example.com")
    multi_step = MultiStepSapExecutor(compiler=compiler, executor=executor)
    plan = QueryPlan(
        service_name="API_PURCHASEORDER_PROCESS_SRV",
        entity_set="A_PurchaseOrder",
        plan_kind="multi_step",
        target_entity_set="A_PurchaseOrder",
        steps=[
            ExecutionStep(
                step_id="step_header",
                entity_set="A_PurchaseOrder",
                select_fields=["PurchaseOrder", "Supplier"],
                filters=[FilterCondition(field="PurchaseOrder", operator="eq", value="4500001513")],
                top=1,
            ),
            ExecutionStep(
                step_id="step_pricing",
                entity_set="A_PurOrdPricingElement",
                select_fields=["PurchaseOrder", "ConditionType"],
                filter_from_previous=[
                    StepBinding(
                        field="PurchaseOrder",
                        source_step_id="step_header",
                        source_field="PurchaseOrder",
                    )
                ],
                top=100,
            ),
        ],
    )

    attempts, data = multi_step.execute_plan(plan, starting_attempt_number=1)

    assert len(attempts) == 2
    assert data is not None
    assert data["primary_step_id"] == "step_header"
    assert data["primary_entity_set"] == "A_PurchaseOrder"
    assert data["final_step_id"] == "step_pricing"
    assert data["final_step_entity_set"] == "A_PurOrdPricingElement"
    assert data["results"] == [{"PurchaseOrder": "4500001513", "Supplier": "17300003"}]
    assert data["step_results"]["step_pricing"]["result_count"] == 2
    assert data["step_results"]["step_pricing"]["results"][0]["ConditionType"] == "PBXX"
