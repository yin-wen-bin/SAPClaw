from pathlib import Path

from sap_odata_agent.application.orchestrator import AgentOrchestrator
from sap_odata_agent.domain.models import (
    AgentRequest,
    CompiledRequest,
    ExecutionAttempt,
    FilterCondition,
    QueryPlan,
    ResultPresentation,
    RetrievedContext,
    RetrievedDocument,
)
from sap_odata_agent.infrastructure.llm.planner import IndexAwareRepairEngine
from sap_odata_agent.infrastructure.repositories.file_case_repository import JsonlCaseRepository


def _write_fixture(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        '[{"service_name":"API_TEST","description":"Business partner service","entity_sets":["A_BusinessPartner","A_Customer"]}]',
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        (
            '[{"service_name":"API_TEST","entity_set":"A_BusinessPartner","entity_type":"A_BusinessPartnerType",'
            '"key_fields":["BusinessPartner"],"default_select_fields":["BusinessPartner","BusinessPartnerFullName"],'
            '"supported_methods":["GET"],"description":"Business partner header data"},'
            '{"service_name":"API_TEST","entity_set":"A_Customer","entity_type":"A_CustomerType",'
            '"key_fields":["Customer"],"default_select_fields":["Customer","CustomerFullName"],'
            '"supported_methods":["GET"],"description":"Customer header data"}]'
        ),
        encoding="utf-8",
    )
    (service_dir / "fields.json").write_text(
        (
            '[{"service_name":"API_TEST","entity_set":"A_BusinessPartner","field_name":"BusinessPartner",'
            '"data_type":"Edm.String","filterable":true,"sortable":true,"description":"Business partner number"},'
            '{"service_name":"API_TEST","entity_set":"A_BusinessPartner","field_name":"BusinessPartnerFullName",'
            '"data_type":"Edm.String","filterable":false,"sortable":true,"description":"Business partner full name"},'
            '{"service_name":"API_TEST","entity_set":"A_Customer","field_name":"Customer",'
            '"data_type":"Edm.String","filterable":true,"sortable":true,"description":"Customer number"},'
            '{"service_name":"API_TEST","entity_set":"A_Customer","field_name":"CustomerFullName",'
            '"data_type":"Edm.String","filterable":false,"sortable":true,"description":"Customer full name"}]'
        ),
        encoding="utf-8",
    )
    (service_dir / "relations.json").write_text("[]", encoding="utf-8")
    (service_dir / "business_terms.json").write_text("[]", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


class StaticRetriever:
    def retrieve(self, query: str, top_k: int = 5) -> RetrievedContext:
        return RetrievedContext(
            documents=[
                RetrievedDocument(
                    source="entity-hint",
                    title="A_BusinessPartner",
                    content="Likely entity candidate",
                    score=10.0,
                    metadata={
                        "service_name": "API_TEST",
                        "entity_set": "A_BusinessPartner",
                        "key_fields": ["BusinessPartner"],
                        "default_select_fields": ["BusinessPartner", "BusinessPartnerFullName"],
                        "supported_methods": ["GET"],
                        "description": "Business partner header data",
                    },
                )
            ]
        )


class BadPlanner:
    def plan(self, request: AgentRequest, context: RetrievedContext) -> QueryPlan:
        return QueryPlan(
            service_name="API_TEST",
            entity_set="A_Customer",
            select_fields=["Customer", "CustomerFullName"],
            filters=[FilterCondition(field="BusinessPartner", operator="eq", value="300001")],
            rationale="Intentionally bad initial plan for repair-loop test.",
        )


class PassThroughValidator:
    def validate(self, plan: QueryPlan):
        return []


class SimpleCompiler:
    def compile(self, plan: QueryPlan) -> CompiledRequest:
        filter_text = ""
        if plan.filters:
            filter_text = f"?$filter={plan.filters[0].field} eq '{plan.filters[0].value}'"
        return CompiledRequest(method=plan.http_method, url=f"https://sap.example.com/{plan.entity_set}{filter_text}")


class FailingThenPassingExecutor:
    def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
        if "A_Customer" in compiled_request.url and "BusinessPartner" in compiled_request.url:
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=compiled_request,
                success=False,
                status_code=400,
                response_preview=None,
                error_message="Property BusinessPartner not found in type A_CustomerType",
            )
        return ExecutionAttempt(
            attempt_number=attempt_number,
            request=compiled_request,
            success=True,
            status_code=200,
            response_preview={"result_count": 1},
            error_message=None,
        )


class StaticPresenter:
    def present(self, request: AgentRequest, plan: QueryPlan, data):
        return ResultPresentation(
            kind="text",
            title="查询结果",
            text=f"{plan.entity_set} rendered",
        )


class CountingRepairEngine(IndexAwareRepairEngine):
    def __init__(self, index_root: Path, service_name: str) -> None:
        super().__init__(index_root=index_root, service_name=service_name)
        self.calls = 0

    def repair(self, request, context, previous_plan, error_message):
        self.calls += 1
        return super().repair(request, context, previous_plan, error_message)


class ClarificationPlanner:
    def plan(self, request: AgentRequest, context: RetrievedContext) -> QueryPlan:
        return QueryPlan(
            service_name="API_TEST",
            entity_set="A_BusinessPartner",
            select_fields=["BusinessPartner"],
            response_summary_fields=[],
            filters=[FilterCondition(field="BusinessPartner", operator="eq", value="300001")],
            needs_clarification=True,
            clarification_question="你要查业务伙伴主数据，还是客户扩展视图？",
            clarification_options=["业务伙伴主数据", "客户扩展视图"],
            response_directive="Ask the user to choose the business context.",
            rationale="The request is ambiguous.",
        )


def test_orchestrator_repairs_failed_query_and_succeeds(tmp_path: Path) -> None:
    _write_fixture(tmp_path)

    orchestrator = AgentOrchestrator(
        retriever=StaticRetriever(),
        planner=BadPlanner(),
        validator=PassThroughValidator(),
        compiler=SimpleCompiler(),
        executor=FailingThenPassingExecutor(),
        repair_engine=IndexAwareRepairEngine(index_root=tmp_path, service_name="API_TEST"),
        result_presenter=StaticPresenter(),
        case_repository=JsonlCaseRepository(str(tmp_path / "cases.jsonl")),
        max_attempts=3,
        retrieval_top_k=5,
    )

    response = orchestrator.run(AgentRequest(user_input="查询业务伙伴300001的基本信息"))

    assert response.success is True
    assert len(response.attempts) == 2
    assert response.plan.entity_set == "A_BusinessPartner"
    assert response.plan.filters[0].field == "BusinessPartner"
    assert response.presentation is not None
    assert response.presentation.text == "A_BusinessPartner rendered"


def test_orchestrator_can_disable_query_repair_and_fail_fast(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    repair_engine = CountingRepairEngine(index_root=tmp_path, service_name="API_TEST")

    orchestrator = AgentOrchestrator(
        retriever=StaticRetriever(),
        planner=BadPlanner(),
        validator=PassThroughValidator(),
        compiler=SimpleCompiler(),
        executor=FailingThenPassingExecutor(),
        repair_engine=repair_engine,
        result_presenter=StaticPresenter(),
        case_repository=JsonlCaseRepository(str(tmp_path / "cases_no_repair.jsonl")),
        max_attempts=3,
        retrieval_top_k=5,
        enable_query_repair=False,
    )

    response = orchestrator.run(AgentRequest(user_input="查询业务伙伴300001的基本信息"))

    assert response.success is False
    assert len(response.attempts) == 1
    assert repair_engine.calls == 0
    assert response.plan.entity_set == "A_Customer"


def test_orchestrator_returns_clarification_without_executing(tmp_path: Path) -> None:
    _write_fixture(tmp_path)

    orchestrator = AgentOrchestrator(
        retriever=StaticRetriever(),
        planner=ClarificationPlanner(),
        validator=PassThroughValidator(),
        compiler=SimpleCompiler(),
        executor=FailingThenPassingExecutor(),
        repair_engine=IndexAwareRepairEngine(index_root=tmp_path, service_name="API_TEST"),
        result_presenter=StaticPresenter(),
        case_repository=JsonlCaseRepository(str(tmp_path / "cases_clarification.jsonl")),
        max_attempts=3,
        retrieval_top_k=5,
    )

    response = orchestrator.run(AgentRequest(user_input="查询300001的信息"))

    assert response.success is False
    assert response.needs_clarification is True
    assert response.clarification_question == "你要查业务伙伴主数据，还是客户扩展视图？"
    assert response.clarification_options == ["业务伙伴主数据", "客户扩展视图"]
    assert response.attempts == []
    assert response.presentation is not None
