from __future__ import annotations

import urllib.parse
from pathlib import Path

import pytest
from pydantic import ValidationError

from sap_odata_agent.application.thin_models import (
    RuntimeGetRequest,
    RuntimeGuidanceRequest,
    RuntimePageRequest,
    RuntimeSchemaRequest,
    ThinQueryPlan,
)
from sap_odata_agent.domain.models import CompiledRequest, ExecutionAttempt
from sap_odata_agent.infrastructure.sap.live_schema import LiveSchemaProvider
from sap_odata_agent.infrastructure.indexing.dual_source_index_builder import SapMetadataParser
from test_thin_runtime import FakeExecutor, build_runtime, valid_plan


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "thin_e2e"


def _metadata_xml(entity_set: str, fields: list[str]) -> str:
    properties = "\n".join(
        f'<Property Name="{field}" Type="Edm.String" Nullable="false" />' for field in fields
    )
    return f'''<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" Version="1.0">
  <edmx:DataServices m:DataServiceVersion="2.0">
    <Schema xmlns="http://schemas.microsoft.com/ado/2008/09/edm" Namespace="Test">
      <EntityType Name="RecordType">
        <Key><PropertyRef Name="{fields[0]}" /></Key>
        {properties}
      </EntityType>
      <EntityContainer Name="Container" m:IsDefaultEntityContainer="true">
        <EntitySet Name="{entity_set}" EntityType="Test.RecordType" />
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>'''


class UnknownTotalExecutor(FakeExecutor):
    def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
        attempt = super().execute(compiled_request, attempt_number)
        preview = dict(attempt.response_preview or {})
        pagination = dict(preview.get("pagination") or {})
        pagination["total_count_known"] = False
        preview["pagination"] = pagination
        preview["result_count"] = int(pagination.get("skip", 0)) + int(preview.get("returned_count", 0))
        attempt.response_preview = preview
        return attempt


def test_unknown_total_count_does_not_block_a_later_page(tmp_path: Path) -> None:
    executor = UnknownTotalExecutor(total_count=82)
    runtime = build_runtime(tmp_path, executor=executor)
    first = runtime.execute_plan(valid_plan())

    second = runtime.page(RuntimePageRequest(case_id=first["case_id"], skip=50))

    assert first["pagination"]["total_count_known"] is False
    assert first["pagination"]["has_next"] is True
    assert second["ok"] is True
    assert "$skip=50" in executor.requests[-1].url


def test_aggregate_rejects_top_on_any_execution_step() -> None:
    with pytest.raises(ValidationError, match="every execution step"):
        ThinQueryPlan.model_validate(
            {
                "service_name": "API_BUSINESS_PARTNER",
                "entity_set": "A_Supplier",
                "plan_kind": "multi_step",
                "steps": [
                    {
                        "step_id": "source",
                        "entity_set": "A_Supplier",
                        "select_fields": ["Supplier"],
                        "top": 10,
                    }
                ],
                "result_transform": {
                    "type": "aggregate",
                    "metrics": [{"operation": "count", "output_field": "Count"}],
                },
            }
        )


class InterruptingExecutor(FakeExecutor):
    def __init__(self) -> None:
        super().__init__(total_count=82)
        self.failed = False

    def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(compiled_request.url).query))
        if int(params.get("$skip", 0)) == 50 and not self.failed:
            self.failed = True
            self.requests.append(compiled_request)
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=compiled_request,
                success=False,
                status_code=500,
                error_message="temporary failure",
            )
        return super().execute(compiled_request, attempt_number)


def _supplier_aggregate_plan(**overrides) -> ThinQueryPlan:
    payload = {
        "service_name": "API_BUSINESS_PARTNER",
        "entity_set": "A_Supplier",
        "select_fields": ["Supplier"],
        "filters": [{"field": "Supplier", "operator": "ne", "value": ""}],
        "order_by": ["Supplier asc"],
        "result_transform": {
            "type": "aggregate",
            "metrics": [{"operation": "count", "output_field": "SupplierCount"}],
        },
    }
    payload.update(overrides)
    return ThinQueryPlan.model_validate(payload)


@pytest.mark.parametrize(
    "changed",
    [
        {"select_fields": ["Supplier", "SupplierName"]},
        {"filters": [{"field": "Supplier", "operator": "eq", "value": "17300001"}]},
        {"order_by": ["Supplier desc"]},
    ],
)
def test_aggregate_resume_requires_the_same_source_plan(tmp_path: Path, changed: dict) -> None:
    runtime = build_runtime(tmp_path, executor=InterruptingExecutor(), max_binding_rows=200)
    interrupted = runtime.execute_plan(_supplier_aggregate_plan())

    mismatch = runtime.execute_plan(
        _supplier_aggregate_plan(**changed),
        resume_case_id=interrupted["case_id"],
    )

    assert interrupted["error"]["code"] == "aggregate_source_interrupted"
    assert mismatch["error"]["code"] == "aggregate_resume_plan_mismatch"


def test_aggregate_resume_accepts_the_identical_source_plan(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path, executor=InterruptingExecutor(), max_binding_rows=200)
    plan = _supplier_aggregate_plan()
    interrupted = runtime.execute_plan(plan)

    resumed = runtime.execute_plan(plan, resume_case_id=interrupted["case_id"])

    assert resumed["ok"] is True
    assert resumed["data"]["results"] == [{"SupplierCount": 82}]


def test_live_schema_provider_fresh_stale_and_unavailable_cache_states() -> None:
    now = [1000.0]
    calls = [0]
    xml = _metadata_xml("Records", ["ID"])

    def fetch(_service: str) -> tuple[str, str]:
        calls[0] += 1
        if calls[0] > 1:
            raise TimeoutError("metadata timeout")
        return xml, "https://sap.example/$metadata"

    provider = LiveSchemaProvider(
        fetch_metadata=fetch,
        fresh_ttl_seconds=300,
        max_stale_seconds=86400,
        clock=lambda: now[0],
    )
    assert provider.get("TEST").runtime_schema_source == "live"
    assert provider.get("TEST").runtime_schema_source == "cache"
    assert calls[0] == 1

    now[0] += 301
    stale = provider.get("TEST")
    assert stale.stale is True
    assert stale.runtime_schema_source == "cache"

    now[0] += 86401
    unavailable = provider.get("TEST")
    assert unavailable.snapshot is None
    assert unavailable.runtime_schema_source == "none"


def test_indexed_newer_and_live_older_fixtures_expose_documentation_only_drift() -> None:
    parser = SapMetadataParser()
    indexed = parser.parse(
        (FIXTURE_ROOT / "schema" / "indexed_newer.xml").read_text(encoding="utf-8"),
        "TEST_SCHEMA",
        "fixture://indexed-newer",
    )
    live = parser.parse(
        (FIXTURE_ROOT / "schema" / "live_older.xml").read_text(encoding="utf-8"),
        "TEST_SCHEMA",
        "fixture://live-older",
    )

    indexed_fields = {field.field_name for field in indexed.fields}
    live_fields = {field.field_name for field in live.fields}
    assert "IndexedNewField" in indexed_fields
    assert "IndexedNewField" not in live_fields


def test_schema_overlay_keeps_documented_fields_but_blocks_drifted_execution(tmp_path: Path) -> None:
    xml = _metadata_xml("A_Supplier", ["Supplier"])
    provider = LiveSchemaProvider(fetch_metadata=lambda _service: (xml, "https://sap.example/$metadata"))
    executor = FakeExecutor(total_count=1)
    runtime = build_runtime(
        tmp_path,
        executor=executor,
        live_schema_provider=provider,
        live_schema_enabled=True,
    )

    schema = runtime.schema(
        RuntimeSchemaRequest(service_name="API_BUSINESS_PARTNER", entity_sets=["A_Supplier"])
    )
    supplier_name = next(field for field in schema["data"]["fields"] if field["field_name"] == "SupplierName")
    structured = runtime.execute_plan(valid_plan(select_fields=["Supplier", "SupplierName"]))
    controlled = runtime.execute_get(
        RuntimeGetRequest(
            service_name="API_BUSINESS_PARTNER",
            resource_path="A_Supplier",
            query_options={"$select": "Supplier,SupplierName"},
        )
    )

    assert schema["data"]["compatibility_status"] == "drifted"
    assert supplier_name["runtime_available"] is False
    assert supplier_name["executable"] is False
    assert structured["error"]["code"] == "schema_drift_field_unavailable"
    assert controlled["error"]["code"] == "schema_drift_field_unavailable"
    assert executor.requests == []


def test_live_schema_unavailable_blocks_before_sap(tmp_path: Path) -> None:
    provider = LiveSchemaProvider(fetch_metadata=lambda _service: (_ for _ in ()).throw(TimeoutError("offline")))
    executor = FakeExecutor()
    runtime = build_runtime(
        tmp_path,
        executor=executor,
        live_schema_provider=provider,
        live_schema_enabled=True,
    )

    response = runtime.execute_plan(valid_plan())

    assert response["error"]["code"] == "live_schema_unavailable"
    assert executor.requests == []


class FailingExecutor(FakeExecutor):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__()
        self.status_code = status_code
        self.message = message

    def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
        self.requests.append(compiled_request)
        return ExecutionAttempt(
            attempt_number=attempt_number,
            request=compiled_request,
            success=False,
            status_code=self.status_code,
            error_message=self.message,
        )


def test_404_refresh_confirms_schema_drift_without_replaying_business_query(tmp_path: Path) -> None:
    metadata = iter(
        [
            _metadata_xml("A_Supplier", ["Supplier", "SupplierName"]),
            _metadata_xml("A_Supplier", ["Supplier"]),
        ]
    )
    provider = LiveSchemaProvider(
        fetch_metadata=lambda _service: (next(metadata), "https://sap.example/$metadata")
    )
    executor = FailingExecutor(404, "resource segment not found")
    runtime = build_runtime(
        tmp_path,
        executor=executor,
        live_schema_provider=provider,
        live_schema_enabled=True,
    )

    response = runtime.execute_plan(valid_plan())

    assert response["error"]["code"] == "schema_drift"
    assert len(executor.requests) == 1


def test_controlled_get_400_refresh_confirms_schema_drift_without_replay(tmp_path: Path) -> None:
    metadata = iter(
        [
            _metadata_xml("A_Supplier", ["Supplier", "SupplierName"]),
            _metadata_xml("A_Supplier", ["Supplier"]),
        ]
    )
    provider = LiveSchemaProvider(
        fetch_metadata=lambda _service: (next(metadata), "https://sap.example/$metadata")
    )
    executor = FailingExecutor(400, "invalid resource segment")
    runtime = build_runtime(
        tmp_path,
        executor=executor,
        live_schema_provider=provider,
        live_schema_enabled=True,
    )

    response = runtime.execute_get(
        RuntimeGetRequest(
            service_name="API_BUSINESS_PARTNER",
            resource_path="A_Supplier",
            query_options={"$select": "Supplier,SupplierName"},
        )
    )

    assert response["error"]["code"] == "schema_drift"
    assert len(executor.requests) == 1


def _material_coverage_plan(*, include_required: bool) -> ThinQueryPlan:
    filters = [
        {"field": "Material", "operator": "eq", "value": "MAT-1"},
        {"field": "MRPPlant", "operator": "eq", "value": "1710"},
        {"field": "MRPArea", "operator": "eq", "value": "1710"},
    ]
    if include_required:
        filters.extend(
            [
                {
                    "field": "MaterialShortageProfile",
                    "operator": "eq",
                    "value": "SAP000000001",
                },
                {"field": "MaterialShortageProfileCount", "operator": "eq", "value": "001"},
            ]
        )
    return ThinQueryPlan.model_validate(
        {
            "service_name": "API_MRP_MATERIALS_SRV_01",
            "entity_set": "MaterialCoverages",
            "select_fields": [
                "Material",
                "MRPPlant",
                "MRPArea",
                "MaterialShortageProfile",
                "MaterialShortageProfileCount",
            ],
            "filters": filters,
        }
    )


def test_mrp_rules_are_exposed_and_required_filters_never_auto_injected(tmp_path: Path) -> None:
    executor = FakeExecutor(total_count=1)
    runtime = build_runtime(tmp_path, executor=executor)
    guidance = runtime.guidance(
        RuntimeGuidanceRequest(
            service_names=["API_MRP_MATERIALS_SRV_01"],
            user_input="material coverage",
        )
    )

    rejected = runtime.execute_plan(_material_coverage_plan(include_required=False))
    accepted = runtime.execute_plan(_material_coverage_plan(include_required=True))

    rules = guidance["data"]["api_skills"][0]["runtime_rules"]["entities"]["MaterialCoverages"]
    assert rules["required_filters"] == ["MaterialShortageProfile", "MaterialShortageProfileCount"]
    assert rules["suggested_values"]["MaterialShortageProfile"]["explicit_only"] is True
    assert rejected["error"]["code"] == "missing_required_runtime_filter"
    assert len(executor.requests) == 1
    assert "MaterialShortageProfile" in executor.requests[0].url
    assert "MaterialShortageProfileCount" in executor.requests[0].url
    assert accepted["ok"] is True


def test_controlled_get_enforces_mrp_filters_before_sap(tmp_path: Path) -> None:
    executor = FakeExecutor()
    runtime = build_runtime(tmp_path, executor=executor)
    response = runtime.execute_get(
        RuntimeGetRequest(
            service_name="API_MRP_MATERIALS_SRV_01",
            resource_path="MaterialCoverages",
            query_options={"$filter": "Material eq 'MAT-1'"},
        )
    )

    assert response["error"]["code"] == "missing_required_runtime_filter"
    assert executor.requests == []


def test_sap_timeout_is_inconclusive_and_retryable(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path, executor=FailingExecutor(504, "Gateway timeout"))

    response = runtime.execute_plan(_material_coverage_plan(include_required=True))

    assert response["error"] == {
        "code": "sap_request_timeout",
        "message": "Gateway timeout",
        "status_code": 504,
        "conclusion_state": "INCONCLUSIVE",
        "retryable": True,
    }


class EvidenceExecutor:
    MAX_PREVIEW_ROWS = 50

    def __init__(self, *, missing_billing: bool = False, fail_billing: bool = False) -> None:
        self.requests: list[CompiledRequest] = []
        self.missing_billing = missing_billing
        self.fail_billing = fail_billing

    def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
        self.requests.append(compiled_request)
        path = urllib.parse.urlsplit(compiled_request.url).path.rsplit("/", 1)[-1]
        if self.fail_billing and path == "A_BillingDocumentItem":
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=compiled_request,
                success=False,
                status_code=500,
                error_message="billing service failed",
            )
        rows_by_entity = {
            "A_SalesOrder": [{"SalesOrder": "3773", "OverallDeliveryStatus": "C"}],
            "A_OutbDeliveryItem": [
                {"DeliveryDocument": "8001", "DeliveryDocumentItem": "10", "ReferenceSDDocument": "3773"}
            ],
            "A_OutbDeliveryHeader": [{"DeliveryDocument": "8001", "OverallGoodsMovementStatus": "C"}],
            "A_BillingDocumentItem": []
            if self.missing_billing
            else [
                {
                    "BillingDocument": "9001",
                    "BillingDocumentItem": "10",
                    "SalesDocument": "3773",
                    "BillingQuantity": "2",
                    "BillingQuantityUnit": "EA",
                    "NetAmount": "100",
                    "TaxAmount": "13",
                    "TransactionCurrency": "CNY",
                }
            ],
            "A_BillingDocument": [
                {
                    "BillingDocument": "9001",
                    "TotalNetAmount": "100",
                    "TaxAmount": "13",
                    "TransactionCurrency": "CNY",
                }
            ],
            "A_BillingDocumentItemPrcgElmnt": [
                {
                    "BillingDocument": "9001",
                    "BillingDocumentItem": "10",
                    "PricingProcedureStep": "10",
                    "PricingProcedureCounter": "1",
                    "ConditionType": "PR00",
                    "TaxCode": "A1",
                    "ConditionAmount": "100",
                    "ConditionCurrency": "CNY",
                    "ConditionInactiveReason": "",
                    "ConditionIsForStatistics": False,
                }
            ],
            "A_OperationalAcctgDocItemCube": [
                {
                    "BillingDocument": "9001",
                    "AccountingDocument": "1900001",
                    "AccountingDocumentItem": "001",
                    "IsCleared": True,
                    "ClearingDate": "2026-08-01",
                    "ClearingAccountingDocument": "2000001",
                    "AmountInCompanyCodeCurrency": "113",
                    "CompanyCodeCurrency": "CNY",
                }
            ],
        }
        rows = rows_by_entity.get(path, [])
        return ExecutionAttempt(
            attempt_number=attempt_number,
            request=compiled_request,
            success=True,
            status_code=200,
            response_preview={
                "result_count": len(rows),
                "returned_count": len(rows),
                "displayed_count": len(rows),
                "results": rows,
                "_all_results": rows,
                "pagination": {
                    "skip": 0,
                    "has_next": False,
                    "sap_has_next": False,
                    "total_count_known": True,
                },
            },
        )


def _binding(field: str, source_step_id: str, source_field: str) -> dict:
    return {
        "field": field,
        "source_step_id": source_step_id,
        "source_field": source_field,
        "fetch_all_for_binding": True,
    }


def _o2c_plan() -> ThinQueryPlan:
    return ThinQueryPlan.model_validate(
        {
            "service_name": "API_SALES_ORDER_SRV",
            "entity_set": "A_SalesOrder",
            "target_entity_set": "A_SalesOrder",
            "plan_kind": "multi_step",
            "steps": [
                {
                    "step_id": "order",
                    "service_name": "API_SALES_ORDER_SRV",
                    "entity_set": "A_SalesOrder",
                    "select_fields": [
                        "SalesOrder",
                        "OverallDeliveryStatus",
                        "OverallOrdReltdBillgStatus",
                        "OverallSDProcessStatus",
                    ],
                    "filters": [{"field": "SalesOrder", "operator": "eq", "value": "3773"}],
                },
                {
                    "step_id": "delivery_items",
                    "service_name": "API_OUTBOUND_DELIVERY_SRV",
                    "entity_set": "A_OutbDeliveryItem",
                    "select_fields": ["DeliveryDocument", "DeliveryDocumentItem", "ReferenceSDDocument"],
                    "filter_from_previous": [_binding("ReferenceSDDocument", "order", "SalesOrder")],
                },
                {
                    "step_id": "delivery_header",
                    "service_name": "API_OUTBOUND_DELIVERY_SRV",
                    "entity_set": "A_OutbDeliveryHeader",
                    "select_fields": [
                        "DeliveryDocument",
                        "ActualGoodsMovementDate",
                        "OverallGoodsMovementStatus",
                        "OverallDelivReltdBillgStatus",
                        "OverallSDProcessStatus",
                    ],
                    "filter_from_previous": [
                        _binding("DeliveryDocument", "delivery_items", "DeliveryDocument")
                    ],
                },
                {
                    "step_id": "billing_items",
                    "service_name": "API_BILLING_DOCUMENT_SRV",
                    "entity_set": "A_BillingDocumentItem",
                    "select_fields": [
                        "BillingDocument",
                        "BillingDocumentItem",
                        "SalesDocument",
                        "BillingQuantity",
                        "BillingQuantityUnit",
                        "NetAmount",
                        "TaxAmount",
                        "TransactionCurrency",
                    ],
                    "filter_from_previous": [_binding("SalesDocument", "order", "SalesOrder")],
                },
                {
                    "step_id": "billing_header",
                    "service_name": "API_BILLING_DOCUMENT_SRV",
                    "entity_set": "A_BillingDocument",
                    "select_fields": [
                        "BillingDocument",
                        "TotalNetAmount",
                        "TaxAmount",
                        "TransactionCurrency",
                        "BillingDocumentIsCancelled",
                        "AccountingPostingStatus",
                        "AccountingTransferStatus",
                    ],
                    "filter_from_previous": [
                        _binding("BillingDocument", "billing_items", "BillingDocument")
                    ],
                },
                {
                    "step_id": "clearing",
                    "service_name": "API_OPLACCTGDOCITEMCUBE_SRV",
                    "entity_set": "A_OperationalAcctgDocItemCube",
                    "select_fields": [
                        "BillingDocument",
                        "AccountingDocument",
                        "AccountingDocumentItem",
                        "IsCleared",
                        "ClearingDate",
                        "ClearingAccountingDocument",
                        "AmountInCompanyCodeCurrency",
                        "CompanyCodeCurrency",
                    ],
                    "filter_from_previous": [
                        _binding("BillingDocument", "billing_items", "BillingDocument")
                    ],
                },
            ],
        }
    )


def test_o2c_six_step_plan_binds_four_apis_and_marks_complete_sources(tmp_path: Path) -> None:
    executor = EvidenceExecutor()
    runtime = build_runtime(tmp_path, executor=executor)

    response = runtime.execute_plan(_o2c_plan())

    assert response["ok"] is True
    assert len(response["data"]["step_results"]) == 6
    assert response["data"]["business_evidence_gaps"] == []
    assert all(
        response["data"]["step_results"][step_id]["source_complete"] is True
        for step_id in ("order", "delivery_items", "billing_items")
    )
    services = {
        part.split("/sap/opu/odata/sap/", 1)[1].split("/", 1)[0].split(";", 1)[0]
        for part in (request.url for request in executor.requests)
    }
    assert services == {
        "API_SALES_ORDER_SRV",
        "API_OUTBOUND_DELIVERY_SRV",
        "API_BILLING_DOCUMENT_SRV",
        "API_OPLACCTGDOCITEMCUBE_SRV",
    }


def test_o2c_missing_document_is_not_reported_as_query_failure(tmp_path: Path) -> None:
    response = build_runtime(tmp_path, executor=EvidenceExecutor(missing_billing=True)).execute_plan(_o2c_plan())

    assert response["ok"] is True
    assert response["data"]["business_evidence_gaps"]
    assert all(
        gap["kind"] == "missing_downstream_business_document"
        for gap in response["data"]["business_evidence_gaps"]
    )


def test_o2c_execution_error_is_not_reported_as_missing_document(tmp_path: Path) -> None:
    response = build_runtime(tmp_path, executor=EvidenceExecutor(fail_billing=True)).execute_plan(_o2c_plan())

    assert response["ok"] is False
    assert response["error"]["code"] == "sap_request_failed"
    assert response.get("data", {}).get("business_evidence_gaps") is None


def test_billing_header_item_pricing_bindings_use_authoritative_fields(tmp_path: Path) -> None:
    executor = EvidenceExecutor()
    runtime = build_runtime(tmp_path, executor=executor)
    plan = ThinQueryPlan.model_validate(
        {
            "service_name": "API_BILLING_DOCUMENT_SRV",
            "entity_set": "A_BillingDocument",
            "plan_kind": "multi_step",
            "steps": [
                {
                    "step_id": "header",
                    "entity_set": "A_BillingDocument",
                    "select_fields": ["BillingDocument", "TotalNetAmount", "TaxAmount", "TransactionCurrency"],
                    "filters": [{"field": "BillingDocument", "operator": "eq", "value": "9001"}],
                },
                {
                    "step_id": "items",
                    "entity_set": "A_BillingDocumentItem",
                    "select_fields": [
                        "BillingDocument",
                        "BillingDocumentItem",
                        "BillingQuantity",
                        "BillingQuantityUnit",
                        "NetAmount",
                        "TaxAmount",
                        "TransactionCurrency",
                    ],
                    "filter_from_previous": [_binding("BillingDocument", "header", "BillingDocument")],
                },
                {
                    "step_id": "pricing",
                    "entity_set": "A_BillingDocumentItemPrcgElmnt",
                    "select_fields": [
                        "BillingDocument",
                        "BillingDocumentItem",
                        "ConditionType",
                        "TaxCode",
                        "ConditionAmount",
                        "ConditionCurrency",
                        "ConditionInactiveReason",
                        "ConditionIsForStatistics",
                    ],
                    "filter_from_previous": [
                        _binding("BillingDocument", "items", "BillingDocument"),
                        _binding("BillingDocumentItem", "items", "BillingDocumentItem"),
                    ],
                },
            ],
        }
    )

    response = runtime.execute_plan(plan)
    guidance = runtime.guidance(
        RuntimeGuidanceRequest(service_names=["API_BILLING_DOCUMENT_SRV"], user_input="billing completeness")
    )

    assert response["ok"] is True
    assert response["data"]["step_results"]["header"]["source_complete"] is True
    assert response["data"]["step_results"]["items"]["source_complete"] is True
    authority = guidance["data"]["api_skills"][0]["runtime_rules"]["evidence_authority"]
    assert authority["billing_item"]["authoritative_fields"][0] == "BillingQuantity"
    assert authority["pricing_element"]["evidence_role"] == "detail_only"
