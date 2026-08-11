from __future__ import annotations

import urllib.parse
from pathlib import Path

from sap_odata_agent.application.schema_feasibility_validator import SchemaFeasibilityValidator
from sap_odata_agent.application.runtime_models import (
    RuntimeCatalogRequest,
    RuntimeGetRequest,
    RuntimeGuidanceRequest,
    RuntimePageRequest,
    RuntimeSchemaRequest,
    RuntimeQueryPlan,
)
from sap_odata_agent.application.runtime import SapClawRuntimeService
from sap_odata_agent.domain.models import CompiledRequest, ExecutionAttempt
from sap_odata_agent.infrastructure.config.settings import Settings
from sap_odata_agent.infrastructure.indexing.api_catalog_provider import ApiCatalogProvider
from sap_odata_agent.infrastructure.indexing.api_skill_provider import ApiSkillProvider
from sap_odata_agent.infrastructure.indexing.schema_context_provider import SchemaContextProvider
from sap_odata_agent.infrastructure.knowledge_graph import KnowledgeGraphProvider
from sap_odata_agent.infrastructure.repositories.file_case_repository import JsonlCaseRepository
from sap_odata_agent.infrastructure.sap.odata_client import BasicODataCompiler, BasicPlanValidator


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_ROOT = REPO_ROOT / "data" / "index"


class FakeExecutor:
    MAX_PREVIEW_ROWS = 50

    def __init__(self, total_count: int = 82) -> None:
        self.total_count = total_count
        self.requests: list[CompiledRequest] = []

    def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
        self.requests.append(compiled_request)
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(compiled_request.url).query))
        skip = int(params.get("$skip", 0))
        top = int(params.get("$top", 50))
        end = min(skip + top, self.total_count)
        rows = [
            {
                "Supplier": str(17300000 + index),
                "SupplierName": f"Supplier {index}",
                "__metadata": {"uri": "https://sap.example/private"},
            }
            for index in range(skip, end)
        ]
        return ExecutionAttempt(
            attempt_number=attempt_number,
            request=compiled_request,
            success=True,
            status_code=200,
            response_preview={
                "result_count": self.total_count,
                "returned_count": len(rows),
                "displayed_count": min(len(rows), 50),
                "results": rows[:50],
                "_all_results": rows,
                "_result_window_start": skip,
                "pagination": {
                    "page_size": top,
                    "display_limit": min(top, 50),
                    "skip": skip,
                    "has_next": end < self.total_count,
                    "next_skip": end if end < self.total_count else None,
                    "total_count_known": True,
                },
            },
        )


class FanoutExecutor:
    MAX_PREVIEW_ROWS = 50

    def __init__(self) -> None:
        self.requests: list[CompiledRequest] = []

    def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
        self.requests.append(compiled_request)
        split = urllib.parse.urlsplit(compiled_request.url)
        params = dict(urllib.parse.parse_qsl(split.query))
        skip = int(params.get("$skip", 0))
        top = int(params.get("$top", 50))
        filter_text = params.get("$filter", "")
        exact_supplier = "Supplier eq '" in filter_text
        total_count = 60 if exact_supplier else 2
        supplier = filter_text.split("Supplier eq '", 1)[1].split("'", 1)[0] if exact_supplier else ""
        end = min(skip + top, total_count)
        rows = [
            {
                "Supplier": supplier or str(17300000 + index),
                "SupplierName": f"{supplier or 'source'}-{index}",
            }
            for index in range(skip, end)
        ]
        return ExecutionAttempt(
            attempt_number=attempt_number,
            request=compiled_request,
            success=True,
            status_code=200,
            response_preview={
                "result_count": total_count,
                "returned_count": len(rows),
                "displayed_count": len(rows),
                "results": rows,
                "_all_results": rows,
                "_result_window_start": skip,
                "pagination": {
                    "page_size": top,
                    "display_limit": min(top, 50),
                    "skip": skip,
                    "has_next": end < total_count,
                    "next_skip": end if end < total_count else None,
                },
            },
        )


def build_runtime(
    tmp_path: Path,
    *,
    executor=None,
    sap_base_url: str = "https://sap.example",
    sap_username: str = "<test-user>",
    sap_password: str = "<test-password>",
    max_binding_rows: int = 5000,
    live_schema_provider=None,
    live_schema_enabled: bool = False,
) -> SapClawRuntimeService:
    settings_kwargs = {
        "sap_base_url": sap_base_url,
        "sap_username": sap_username,
        "case_store_path": str(tmp_path / "cases.jsonl"),
        "index_root": str(INDEX_ROOT),
        "api_skill_root": str(REPO_ROOT / "data" / "api_skills"),
        "local_kg_root": str(REPO_ROOT / "data" / "knowledge_graph"),
        "runtime_page_size": 50,
        "runtime_max_binding_rows": max_binding_rows,
        "runtime_live_schema_enabled": live_schema_enabled,
        "runtime_viewer_enabled": True,
        "runtime_viewer_base_url": "http://127.0.0.1:8000",
    }
    settings_kwargs["sap_" + "password"] = sap_password
    settings = Settings(**settings_kwargs)
    return SapClawRuntimeService(
        settings=settings,
        catalog_provider=ApiCatalogProvider(settings.index_root),
        skill_provider=ApiSkillProvider(settings.api_skill_root),
        knowledge_graph_provider=KnowledgeGraphProvider(settings.local_kg_root, enabled=True, max_evidence=5),
        schema_context_provider=SchemaContextProvider(settings.index_root),
        schema_validator=SchemaFeasibilityValidator(settings.index_root, enabled=True),
        plan_validator=BasicPlanValidator(),
        compiler=BasicODataCompiler(settings.sap_base_url, index_root=settings.index_root),
        executor=executor or FakeExecutor(),
        case_repository=JsonlCaseRepository(settings.case_store_path),
        live_schema_provider=live_schema_provider,
    )


def valid_plan(**overrides) -> RuntimeQueryPlan:
    payload = {
        "service_name": "API_BUSINESS_PARTNER",
        "entity_set": "A_Supplier",
        "select_fields": ["Supplier", "SupplierName"],
        "filters": [{"field": "Supplier", "operator": "eq", "value": "17300003"}],
    }
    payload.update(overrides)
    return RuntimeQueryPlan.model_validate(payload)


def test_runtime_plan_defaults_top_to_none_and_forbids_unknown_keys() -> None:
    plan = valid_plan()

    assert plan.top is None

    try:
        RuntimeQueryPlan.model_validate({**plan.model_dump(), "fallback_service": "API_TEST"})
    except ValueError as exc:
        assert "Extra inputs are not permitted" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Strict RuntimeQueryPlan accepted an unknown key.")


def test_validate_plan_uses_schema_as_execution_authority(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    valid = runtime.validate_plan(valid_plan(), "query supplier 17300003")
    invalid = runtime.validate_plan(
        valid_plan(select_fields=["Supplier", "FieldThatDoesNotExist"]),
        "query supplier 17300003",
    )

    assert valid["ok"] is True
    assert invalid["ok"] is False
    assert any(issue["code"] == "schema_select_field_not_in_entity" for issue in invalid["validation_issues"])


def test_output_contract_requests_support_fields_but_displays_explicit_fields(tmp_path: Path) -> None:
    executor = FakeExecutor(total_count=2)
    runtime = build_runtime(tmp_path, executor=executor)
    plan = valid_plan(
        select_fields=[],
        output_contract={
            "mode": "explicit",
            "display_grain": "supplier",
            "requested_fields": ["SupplierName"],
            "display_fields": ["SupplierName"],
            "support_fields": ["Supplier"],
            "reason": "The user explicitly requested only the supplier name.",
        },
    )

    response = runtime.execute_plan(plan, user_input="show only supplier name")
    request_query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(executor.requests[0].url).query))
    stored = runtime.case_repository.get_by_case_id(response["case_id"])

    assert response["ok"] is True
    assert request_query["$select"].split(",") == ["SupplierName", "Supplier"]
    assert response["data"]["presentation"]["columns"] == ["SupplierName"]
    assert list(response["data"]["presentation"]["rows"][0]) == ["SupplierName"]
    assert stored["final_plan"]["output_contract"]["mode"] == "explicit"


def test_output_contract_unknown_display_field_is_rejected_by_schema(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    plan = valid_plan(
        output_contract={
            "mode": "inferred",
            "display_grain": "supplier",
            "display_fields": ["UnknownDisplayField"],
            "support_fields": [],
            "reason": "Test schema enforcement.",
        }
    )

    response = runtime.validate_plan(plan, "show supplier")

    assert response["ok"] is False
    assert any(issue["code"] == "schema_select_field_not_in_entity" for issue in response["validation_issues"])


def test_explicit_output_contract_cannot_substitute_requested_fields() -> None:
    try:
        valid_plan(
            output_contract={
                "mode": "explicit",
                "display_grain": "supplier",
                "requested_fields": ["SupplierName"],
                "display_fields": ["Supplier"],
                "support_fields": [],
                "reason": "Test explicit contract strictness.",
            }
        )
    except ValueError as exc:
        assert "display exactly the requested_fields" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Explicit output contract accepted a substituted display field.")


def test_aggregate_output_contract_rejects_fields_lost_after_transform() -> None:
    try:
        valid_plan(
            result_transform={"type": "aggregate", "group_by": ["Supplier"], "sum_fields": []},
            output_contract={
                "mode": "inferred",
                "display_grain": "supplier",
                "display_fields": ["SupplierName"],
                "support_fields": [],
                "reason": "Test aggregate output preservation.",
            },
        )
    except ValueError as exc:
        assert "Aggregate output contracts" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Aggregate output contract accepted a field lost after transformation.")


def test_catalog_schema_and_guidance_are_evidence_only(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    catalog = runtime.catalog(RuntimeCatalogRequest(query="supplier details", skip=0, limit=5))
    schema = runtime.schema(
        RuntimeSchemaRequest(
            service_name="API_BUSINESS_PARTNER",
            entity_sets=["A_Supplier"],
            query="supplier details",
        )
    )
    guidance = runtime.guidance(
        RuntimeGuidanceRequest(
            user_input="supplier details",
            service_names=["API_BUSINESS_PARTNER"],
        )
    )

    assert catalog["ok"] is True
    assert len(catalog["data"]["items"]) == 5
    assert "skill_api_evidence" in catalog["data"]
    assert schema["data"]["schema_authority"] is True
    assert any(field["field_name"] == "Supplier" for field in schema["data"]["fields"])
    assert guidance["data"]["evidence_policy"]["evidence_never_modifies_plan"] is True
    assert guidance["data"]["api_skills"][0]["service_name"] == "API_BUSINESS_PARTNER"
    assert "plan" not in guidance["data"]


def test_execute_plan_revalidates_pages_and_strips_internal_data(tmp_path: Path) -> None:
    executor = FakeExecutor(total_count=82)
    runtime = build_runtime(tmp_path, executor=executor)

    response = runtime.execute_plan(valid_plan(), user_input="查询供应商")

    assert response["ok"] is True
    assert response["case_id"]
    assert response["pagination"] == {
        "page_size": 50,
        "skip": 0,
            "total_count": 82,
            "total_count_known": True,
        "has_next": True,
        "next_skip": 50,
    }
    assert response["viewer_url"].endswith(f"?case_id={response['case_id']}&page=1")
    assert "$top=50" in executor.requests[0].url
    assert "_all_results" not in str(response)
    assert "__metadata" not in str(response)
    assert "test-password" not in str(response)

    stored = runtime.case_repository.get_by_case_id(response["case_id"])
    assert stored["execution_origin"] == "sapclaw_mcp"
    assert stored["request_kind"] == "structured_plan"
    assert stored["runtime_request"]["pagination"]["business_top"] is None


def test_runtime_page_uses_case_id_and_skip(tmp_path: Path) -> None:
    executor = FakeExecutor(total_count=82)
    runtime = build_runtime(tmp_path, executor=executor)
    first = runtime.execute_plan(valid_plan(), user_input="query suppliers")

    second = runtime.page(RuntimePageRequest(case_id=first["case_id"], skip=50))

    assert second["ok"] is True
    assert second["pagination"]["skip"] == 50
    assert second["pagination"]["total_count"] == 82
    assert second["pagination"]["has_next"] is False
    assert "$skip=50" in executor.requests[-1].url

    out_of_range = runtime.page(RuntimePageRequest(case_id=first["case_id"], skip=100))
    assert out_of_range["status"] == "page_out_of_range"


def test_explicit_top_is_a_business_limit_not_the_default_page_size(tmp_path: Path) -> None:
    executor = FakeExecutor(total_count=82)
    runtime = build_runtime(tmp_path, executor=executor)

    response = runtime.execute_plan(valid_plan(top=10), user_input="show only ten suppliers")
    out_of_range = runtime.page(RuntimePageRequest(case_id=response["case_id"], skip=50))

    assert response["ok"] is True
    assert response["pagination"]["page_size"] == 50
    assert response["pagination"]["total_count"] == 10
    assert response["pagination"]["has_next"] is False
    assert "$top=10" in executor.requests[0].url
    assert out_of_range["status"] == "page_out_of_range"


def test_fetch_all_for_binding_reads_all_source_pages(tmp_path: Path) -> None:
    executor = FakeExecutor(total_count=82)
    runtime = build_runtime(tmp_path, executor=executor)
    plan = RuntimeQueryPlan.model_validate(
        {
            "service_name": "API_BUSINESS_PARTNER",
            "entity_set": "A_Supplier",
            "plan_kind": "multi_step",
            "steps": [
                {
                    "step_id": "step_1",
                    "entity_set": "A_Supplier",
                    "select_fields": ["Supplier"],
                    "filters": [{"field": "Supplier", "operator": "ne", "value": ""}],
                },
                {
                    "step_id": "step_2",
                    "entity_set": "A_Supplier",
                    "select_fields": ["Supplier", "SupplierName"],
                    "filter_from_previous": [
                        {
                            "field": "Supplier",
                            "source_step_id": "step_1",
                            "source_field": "Supplier",
                            "fetch_all_for_binding": True,
                        }
                    ],
                },
            ],
        }
    )

    response = runtime.execute_plan(plan, user_input="query supplier details")

    assert response["ok"] is True
    assert len(executor.requests) == 3
    assert "$skip=50" in executor.requests[1].url
    assert "%22" not in executor.requests[2].url


def test_fetch_all_for_binding_fails_explicitly_at_configured_limit(tmp_path: Path) -> None:
    executor = FakeExecutor(total_count=82)
    runtime = build_runtime(tmp_path, executor=executor, max_binding_rows=60)
    plan = RuntimeQueryPlan.model_validate(
        {
            "service_name": "API_BUSINESS_PARTNER",
            "entity_set": "A_Supplier",
            "plan_kind": "multi_step",
            "steps": [
                {
                    "step_id": "step_1",
                    "entity_set": "A_Supplier",
                    "select_fields": ["Supplier"],
                    "filters": [{"field": "Supplier", "operator": "ne", "value": ""}],
                },
                {
                    "step_id": "step_2",
                    "entity_set": "A_Supplier",
                    "select_fields": ["Supplier"],
                    "filter_from_previous": [
                        {
                            "field": "Supplier",
                            "source_step_id": "step_1",
                            "source_field": "Supplier",
                            "fetch_all_for_binding": True,
                        }
                    ],
                },
            ],
        }
    )

    response = runtime.execute_plan(plan, user_input="query supplier details")

    assert response["ok"] is False
    assert response["error"]["code"] == "binding_row_limit_exceeded"
    assert len(executor.requests) == 2


def test_final_fanout_fetches_complete_window_for_local_pagination(tmp_path: Path) -> None:
    executor = FanoutExecutor()
    runtime = build_runtime(tmp_path, executor=executor, max_binding_rows=500)
    plan = RuntimeQueryPlan.model_validate(
        {
            "service_name": "API_BUSINESS_PARTNER",
            "entity_set": "A_Supplier",
            "plan_kind": "multi_step",
            "steps": [
                {
                    "step_id": "step_1",
                    "entity_set": "A_Supplier",
                    "select_fields": ["Supplier"],
                    "filters": [{"field": "Supplier", "operator": "ne", "value": ""}],
                    "top": 2,
                },
                {
                    "step_id": "step_2",
                    "entity_set": "A_Supplier",
                    "select_fields": ["Supplier", "SupplierName"],
                    "filter_from_previous": [
                        {
                            "field": "Supplier",
                            "source_step_id": "step_1",
                            "source_field": "Supplier",
                            "fanout": True,
                        }
                    ],
                },
            ],
        }
    )

    first = runtime.execute_plan(plan, user_input="query supplier details")
    request_count = len(executor.requests)
    third = runtime.page(RuntimePageRequest(case_id=first["case_id"], skip=100))

    assert first["ok"] is True
    assert first["pagination"]["total_count"] == 120
    assert third["ok"] is True
    assert third["pagination"]["skip"] == 100
    assert third["pagination"]["total_count"] == 120
    assert len(third["data"]["results"]) == 20
    assert len(executor.requests) == request_count


def test_controlled_get_rejects_unsafe_inputs_before_executor(tmp_path: Path) -> None:
    executor = FakeExecutor()
    runtime = build_runtime(tmp_path, executor=executor)
    unsafe_requests = [
        RuntimeGetRequest(service_name="API_BUSINESS_PARTNER", resource_path="https://evil.example/data"),
        RuntimeGetRequest(service_name="API_BUSINESS_PARTNER", resource_path="../A_Supplier"),
        RuntimeGetRequest(
            service_name="API_BUSINESS_PARTNER",
            resource_path="A_Supplier",
            query_options={"$apply": "groupby((Supplier))"},
        ),
        RuntimeGetRequest(
            service_name="API_BUSINESS_PARTNER",
            resource_path="A_Supplier",
            query_options={"$select": "Supplier,Password"},
        ),
    ]

    for request in unsafe_requests:
        response = runtime.execute_get(request)
        assert response["ok"] is False
        assert response["status"] == "validation_failed"

    assert executor.requests == []


def test_controlled_get_rejects_unknown_and_cds_only_services(tmp_path: Path) -> None:
    executor = FakeExecutor()
    runtime = build_runtime(tmp_path, executor=executor)

    unknown = runtime.execute_get(RuntimeGetRequest(service_name="API_NOT_INDEXED", resource_path="A_Test"))
    cds_only = runtime.execute_get(
        RuntimeGetRequest(service_name="I_ProductionVersion", resource_path="I_ProductionVersion")
    )

    assert unknown["ok"] is False
    assert unknown["validation_issues"][0]["code"] == "service_not_indexed"
    assert cds_only["ok"] is False
    assert any(issue["code"] == "service_not_odata_executable" for issue in cds_only["validation_issues"])
    assert executor.requests == []


def test_controlled_get_executes_only_indexed_relative_entity(tmp_path: Path) -> None:
    executor = FakeExecutor(total_count=1)
    runtime = build_runtime(tmp_path, executor=executor)

    response = runtime.execute_get(
        RuntimeGetRequest(
            service_name="API_BUSINESS_PARTNER",
            resource_path="A_Supplier",
            query_options={
                "$select": "Supplier,SupplierName",
                "$filter": "Supplier eq '17300003'",
            },
            user_input="查询供应商17300003",
        )
    )

    assert response["ok"] is True
    assert executor.requests[0].method == "GET"
    assert executor.requests[0].url.startswith(
        "https://sap.example/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_Supplier?"
    )
    assert response["metadata"]["read_only"] is True


def test_controlled_get_singletons_never_receive_collection_paging_options(tmp_path: Path) -> None:
    class SingletonExecutor:
        MAX_PREVIEW_ROWS = 50

        def __init__(self) -> None:
            self.requests: list[CompiledRequest] = []

        def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
            self.requests.append(compiled_request)
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=compiled_request,
                success=True,
                status_code=200,
                response_preview={"result": {"Supplier": "17300003", "SupplierName": "Test supplier"}},
            )

    executor = SingletonExecutor()
    runtime = build_runtime(tmp_path, executor=executor)
    resource_paths = [
        "A_Supplier('17300003')",
        (
            "A_CustomerSalesArea(Customer='1000001',SalesOrganization='1000',"
            "DistributionChannel='10',Division='00')"
        ),
    ]

    for resource_path in resource_paths:
        response = runtime.execute_get(
            RuntimeGetRequest(service_name="API_BUSINESS_PARTNER", resource_path=resource_path)
        )
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(executor.requests[-1].url).query))

        assert response["ok"] is True
        assert not {"$top", "$skip", "$skiptoken", "$inlinecount"}.intersection(query)
        assert response["data"]["resource_kind"] == "singleton"
        assert response["data"]["source_complete"] is True
        assert response["pagination"] == {
            "page_size": 1,
            "skip": 0,
                "total_count": 1,
                "total_count_known": True,
                "has_next": False,
            "next_skip": None,
        }

    request_count = len(executor.requests)
    repeated = runtime.page(RuntimePageRequest(case_id=response["case_id"], skip=0))
    out_of_range = runtime.page(RuntimePageRequest(case_id=response["case_id"], skip=1))
    assert repeated["ok"] is True
    assert repeated["pagination"]["total_count"] == 1
    assert out_of_range["status"] == "page_out_of_range"
    assert len(executor.requests) == request_count


def test_complete_month_end_aggregate_pages_all_rows_and_returns_diagnostics(tmp_path: Path) -> None:
    class MonthEndExecutor:
        MAX_PREVIEW_ROWS = 50

        def __init__(self, total_count: int, fail_once_at_skip: int | None = None) -> None:
            self.total_count = total_count
            self.fail_once_at_skip = fail_once_at_skip
            self.failed_once = False
            self.requests: list[CompiledRequest] = []

        def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
            self.requests.append(compiled_request)
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(compiled_request.url).query))
            skip = int(params.get("$skip", 0))
            top = int(params.get("$top", 50))
            if skip == self.fail_once_at_skip and not self.failed_once:
                self.failed_once = True
                return ExecutionAttempt(
                    attempt_number=attempt_number,
                    request=compiled_request,
                    success=False,
                    status_code=504,
                    error_message="simulated page timeout",
                )
            end = min(skip + top, self.total_count)
            rows = [
                {
                    "ID": str(index),
                    "CompanyCode": "1710",
                    "CompanyCodeCurrency": "CNY",
                    "FiscalYear": "2026",
                    "AccountingDocument": str(1000000000 + index),
                    "AccountingDocumentItem": "001",
                    "Ledger": "0L",
                    "AmountInCompanyCodeCurrency": "-1" if index % 2 else "1",
                }
                for index in range(skip, end)
            ]
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=compiled_request,
                success=True,
                status_code=200,
                response_preview={
                    "result_count": self.total_count,
                    "returned_count": len(rows),
                    "results": rows,
                    "_all_results": rows,
                    "source_complete": end >= self.total_count,
                    "source_truncated": end < self.total_count,
                    "pagination": {
                        "page_size": top,
                        "skip": skip,
                        "has_next": end < self.total_count,
                        "sap_has_next": end < self.total_count,
                        "sap_next_skip": end if end < self.total_count else None,
                    },
                },
            )

    def aggregate_plan() -> RuntimeQueryPlan:
        return RuntimeQueryPlan.model_validate(
            {
                "service_name": "API_GLACCOUNTLINEITEM",
                "entity_set": "GLAccountLineItem",
                "select_fields": [
                    "CompanyCode",
                    "CompanyCodeCurrency",
                    "FiscalYear",
                    "AccountingDocument",
                    "AccountingDocumentItem",
                    "Ledger",
                    "AmountInCompanyCodeCurrency",
                ],
                "result_transform": {
                    "type": "aggregate",
                    "group_by": ["CompanyCode", "CompanyCodeCurrency"],
                    "deduplicate_by": [
                        "CompanyCode",
                        "FiscalYear",
                        "AccountingDocument",
                        "AccountingDocumentItem",
                        "Ledger",
                    ],
                    "metrics": [
                        {"operation": "count", "output_field": "SourceItemCount"},
                        {
                            "operation": "count_distinct",
                            "output_field": "DistinctItemCount",
                            "distinct_fields": [
                                "CompanyCode",
                                "FiscalYear",
                                "AccountingDocument",
                                "AccountingDocumentItem",
                                "Ledger",
                            ],
                        },
                        {
                            "operation": "sum_abs",
                            "output_field": "AbsoluteAmount",
                            "field": "AmountInCompanyCodeCurrency",
                            "currency_field": "CompanyCodeCurrency",
                        },
                    ],
                },
                "output_contract": {
                    "mode": "inferred",
                    "display_grain": "company code and currency",
                    "display_fields": [
                        "CompanyCode",
                        "CompanyCodeCurrency",
                        "SourceItemCount",
                        "DistinctItemCount",
                        "AbsoluteAmount",
                    ],
                    "reason": "Return complete month-end aggregate evidence.",
                },
            }
        )

    executor = MonthEndExecutor(total_count=1463)
    runtime = build_runtime(tmp_path, executor=executor, max_binding_rows=2000)

    response = runtime.execute_plan(aggregate_plan(), user_input="calculate complete AP month-end evidence")

    assert response["ok"] is True
    assert len(executor.requests) == 30
    assert "$orderby=ID" in executor.requests[0].url
    assert response["data"]["results"] == [
        {
            "CompanyCode": "1710",
            "CompanyCodeCurrency": "CNY",
            "SourceItemCount": 1463,
            "DistinctItemCount": 1463,
            "AbsoluteAmount": "1463",
        }
    ]
    diagnostics = response["data"]["result_transform"]
    assert diagnostics["source_row_count"] == 1463
    assert diagnostics["fetched_row_count"] == 1463
    assert diagnostics["source_complete"] is True
    assert diagnostics["source_truncated"] is False
    assert diagnostics["currency_groups"] == {"CompanyCodeCurrency": ["CNY"]}
    assert diagnostics["stable_order_fields"] == ["ID"]

    limited_executor = MonthEndExecutor(total_count=120)
    limited_runtime = build_runtime(tmp_path / "limited", executor=limited_executor, max_binding_rows=100)
    limited = limited_runtime.execute_plan(aggregate_plan(), user_input="bounded aggregate")

    assert limited["ok"] is False
    assert limited["error"]["code"] == "aggregate_source_limit_exceeded"
    assert limited["data"]["source_complete"] is False
    assert limited["data"]["source_truncated"] is True
    assert limited["error"]["diagnostics"]["next_source_skip"] == 100

    interrupted_executor = MonthEndExecutor(total_count=120, fail_once_at_skip=50)
    interrupted_runtime = build_runtime(
        tmp_path / "interrupted", executor=interrupted_executor, max_binding_rows=200
    )
    interrupted = interrupted_runtime.execute_plan(aggregate_plan(), user_input="resumable aggregate")

    assert interrupted["ok"] is False
    assert interrupted["error"]["code"] == "sap_request_timeout"
    assert interrupted["error"]["conclusion_state"] == "INCONCLUSIVE"
    assert interrupted["error"]["retryable"] is True
    assert interrupted["data"]["next_source_skip"] == 50
    resumed = interrupted_runtime.execute_plan(
        aggregate_plan(),
        user_input="resume aggregate",
        resume_case_id=interrupted["case_id"],
    )

    assert resumed["ok"] is True
    assert resumed["data"]["results"][0]["SourceItemCount"] == 120
    assert [
        int(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(request.url).query)).get("$skip", 0))
        for request in interrupted_executor.requests
    ] == [0, 50, 50, 100]


def test_controlled_get_rejects_explicit_singleton_paging_before_executor(tmp_path: Path) -> None:
    executor = FakeExecutor()
    runtime = build_runtime(tmp_path, executor=executor)

    response = runtime.execute_get(
        RuntimeGetRequest(
            service_name="API_BUSINESS_PARTNER",
            resource_path="A_Supplier('17300003')",
            query_options={"$top": "1", "$inlinecount": "allpages"},
        )
    )

    assert response["ok"] is False
    assert any(issue["code"] == "singleton_paging_not_allowed" for issue in response["validation_issues"])
    assert executor.requests == []


def test_controlled_get_output_contract_hides_support_fields(tmp_path: Path) -> None:
    executor = FakeExecutor(total_count=1)
    runtime = build_runtime(tmp_path, executor=executor)

    response = runtime.execute_get(
        RuntimeGetRequest(
            service_name="API_BUSINESS_PARTNER",
            resource_path="A_Supplier",
            query_options={"$select": "Supplier"},
            output_contract={
                "mode": "explicit",
                "display_grain": "supplier",
                "requested_fields": ["SupplierName"],
                "display_fields": ["SupplierName"],
                "support_fields": ["Supplier"],
                "reason": "The user explicitly requested only the supplier name.",
            },
            user_input="show only supplier name",
        )
    )
    request_query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(executor.requests[0].url).query))

    assert response["ok"] is True
    assert request_query["$select"].split(",") == ["Supplier", "SupplierName"]
    assert response["data"]["presentation"]["columns"] == ["SupplierName"]


def test_runtime_not_ready_short_circuits_without_sap_request(tmp_path: Path) -> None:
    executor = FakeExecutor()
    runtime = build_runtime(tmp_path, sap_base_url="", executor=executor)

    response = runtime.execute_plan(valid_plan())

    assert response["ok"] is False
    assert response["status"] == "not_ready"
    assert response["error"]["code"] == "runtime_not_ready"
    assert any(issue["code"] == "sap_base_url_missing" for issue in response["error"]["details"])
    assert executor.requests == []


def test_runtime_health_reports_missing_credentials_and_live_schema_provider(tmp_path: Path) -> None:
    runtime = build_runtime(
        tmp_path,
        sap_username="",
        sap_password="",
        live_schema_enabled=True,
        live_schema_provider=None,
    )

    health = runtime.health()
    issue_codes = {issue["code"] for issue in health["data"]["readiness_issues"]}

    assert health["ok"] is False
    assert health["status"] == "not_ready"
    assert "sap_credentials_missing" in issue_codes
    assert "live_schema_not_ready" in issue_codes
