from sap_odata_agent.domain.models import CompiledRequest, ExecutionStep, FilterCondition, QueryPlan, StepBinding
import urllib.error

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
    assert "$top=1" in prepared


def test_executor_returns_preview_for_json_results() -> None:
    class StubExecutor(SapODataExecutor):
        def _perform_request(self, compiled_request: CompiledRequest) -> dict[str, str | int]:
            return {
                "status_code": 200,
                "content_type": "application/json",
                "body": '{"d":{"results":[{"Customer":"1000001"},{"Customer":"1000002"}]}}',
            }

    executor = StubExecutor(_build_executor().config)
    attempt = executor.execute(
        CompiledRequest(method="GET", url="https://sap.example.com/sap/opu/odata/sap/API_TEST/A_Customer?$top=2"),
        attempt_number=1,
    )

    assert attempt.success is True
    assert attempt.status_code == 200
    assert attempt.response_preview["result_count"] == 2
    assert attempt.response_preview["results"][0]["Customer"] == "1000001"


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
