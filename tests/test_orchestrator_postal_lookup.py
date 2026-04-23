from datetime import datetime
from pathlib import Path

from sap_odata_agent.application.orchestrator import AgentOrchestrator
from sap_odata_agent.domain.models import (
    AgentRequest,
    CaseRecord,
    CompiledRequest,
    ExecutionAttempt,
    QueryPlan,
    ResultPresentation,
    RetrievedContext,
)
from sap_odata_agent.infrastructure.repositories.file_case_repository import JsonlCaseRepository


class StaticRetriever:
    def retrieve(self, query: str, top_k: int = 5) -> RetrievedContext:
        return RetrievedContext()


class SupplierHeaderPlanner:
    def plan(self, request: AgentRequest, context: RetrievedContext) -> QueryPlan:
        return QueryPlan(
            service_name="API_BUSINESS_PARTNER",
            entity_set="A_Supplier",
            select_fields=["Supplier", "AuthorizationGroup"],
            response_summary_fields=["Supplier"],
            filters=[],
            rationale="Test fixture picks the supplier header entity first.",
        )


class PassThroughValidator:
    def validate(self, plan: QueryPlan):
        return []


class RoutingCompiler:
    def compile(self, plan: QueryPlan) -> CompiledRequest:
        return CompiledRequest(method="GET", url=f"https://sap.example.com/{plan.entity_set}")


class PostalLookupExecutor:
    def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
        entity_set = compiled_request.url.rsplit("/", 1)[-1]
        payload_map = {
            "A_Supplier": {
                "result_count": 1,
                "results": [{"Supplier": "643266", "AuthorizationGroup": ""}],
            },
            "A_BusinessPartner": {
                "result_count": 1,
                "results": [
                    {
                        "BusinessPartner": "9000000024",
                        "Supplier": "643266",
                        "BusinessPartnerFullName": "Jennifer Stone",
                    }
                ],
            },
            "A_BusinessPartnerAddress": {
                "result_count": 1,
                "results": [
                    {
                        "BusinessPartner": "9000000024",
                        "AddressID": "100",
                        "PostalCode": "10001",
                        "CompanyPostalCode": "",
                        "POBoxPostalCode": "",
                        "CityName": "New York",
                        "Country": "US",
                    }
                ],
            },
        }
        payload = payload_map[entity_set]
        return ExecutionAttempt(
            attempt_number=attempt_number,
            request=compiled_request,
            success=True,
            status_code=200,
            response_preview=payload,
            error_message=None,
        )


class EchoPresenter:
    def present(self, request: AgentRequest, plan: QueryPlan, data):
        record = (data or {}).get("results", [{}])[0]
        return ResultPresentation(
            kind="text",
            title="查询结果",
            text=f"{plan.entity_set}:{record.get('PostalCode') or record.get('Supplier') or ''}",
        )


class PassThroughRepair:
    def repair(self, request: AgentRequest, context: RetrievedContext, previous_plan: QueryPlan, error_message: str):
        return previous_plan


def _repository(tmp_path: Path) -> JsonlCaseRepository:
    return JsonlCaseRepository(str(tmp_path / "cases.jsonl"))


def test_postal_code_query_triggers_address_lookup_for_supplier_number(tmp_path: Path) -> None:
    orchestrator = AgentOrchestrator(
        retriever=StaticRetriever(),
        planner=SupplierHeaderPlanner(),
        validator=PassThroughValidator(),
        compiler=RoutingCompiler(),
        executor=PostalLookupExecutor(),
        repair_engine=PassThroughRepair(),
        result_presenter=EchoPresenter(),
        case_repository=_repository(tmp_path),
        max_attempts=2,
        retrieval_top_k=5,
    )

    response = orchestrator.run(AgentRequest(user_input="供应商643266的邮编是多少？", conversation_id="postal-1"))

    assert response.success is True
    assert response.plan.entity_set == "A_Supplier"
    assert response.plan.plan_kind == "direct"
    assert response.data is not None
    assert response.data["results"][0]["Supplier"] == "643266"
    assert len(response.attempts) == 1
