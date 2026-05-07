import json
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


def _make_case(
    *,
    case_id: str,
    user_input: str,
    conversation_id: str | None,
    final_status: str,
    clarification_question: str | None = None,
    effective_user_input: str | None = None,
) -> CaseRecord:
    return CaseRecord(
        case_id=case_id,
        created_at=datetime.now().astimezone(),
        request=AgentRequest(user_input=user_input, conversation_id=conversation_id),
        context=RetrievedContext(),
        initial_plan=QueryPlan(
            service_name="API_TEST",
            entity_set="A_SupplierPurchasingOrg",
            select_fields=["Supplier", "PurchasingOrganization", "PurOrdDeliveryIsPlannedForDays"],
            response_summary_fields=["PurchasingOrganization", "PurOrdDeliveryIsPlannedForDays"],
            needs_clarification=final_status == "clarification_requested",
            clarification_question=clarification_question,
            clarification_options=["1710", "1720"] if clarification_question else [],
            response_directive="Answer with the planned delivery time.",
            rationale="test fixture",
        ),
        final_plan=QueryPlan(
            service_name="API_TEST",
            entity_set="A_SupplierPurchasingOrg",
            select_fields=["Supplier", "PurchasingOrganization", "PurOrdDeliveryIsPlannedForDays"],
            response_summary_fields=["PurchasingOrganization", "PurOrdDeliveryIsPlannedForDays"],
            needs_clarification=final_status == "clarification_requested",
            clarification_question=clarification_question,
            clarification_options=["1710", "1720"] if clarification_question else [],
            response_directive="Answer with the planned delivery time.",
            rationale="test fixture",
        ),
        attempts=[],
        final_status=final_status,
        final_query_url=None,
        response_preview=None,
        effective_user_input=effective_user_input,
        presentation=ResultPresentation(
            kind="text",
            title="查询结果",
            text=clarification_question or "fixture",
        ),
        feedback=None,
        error_summary=clarification_question if final_status == "clarification_requested" else None,
    )


class StaticRetriever:
    def __init__(self) -> None:
        self.last_query = ""

    def retrieve(self, query: str, top_k: int = 5) -> RetrievedContext:
        self.last_query = query
        return RetrievedContext()


class CapturingPlanner:
    def __init__(self) -> None:
        self.last_resolved_user_input = ""
        self.last_feedback_hints = []

    def plan(self, request: AgentRequest, context: RetrievedContext) -> QueryPlan:
        self.last_resolved_user_input = request.resolved_user_input or request.user_input
        self.last_feedback_hints = request.feedback_hints
        return QueryPlan(
            service_name="API_TEST",
            entity_set="A_SupplierPurchasingOrg",
            select_fields=["Supplier", "PurchasingOrganization", "MaterialPlannedDeliveryDurn"],
            response_summary_fields=["PurchasingOrganization", "MaterialPlannedDeliveryDurn"],
            rationale="planner captured follow-up context",
        )


class PassThroughValidator:
    def validate(self, plan: QueryPlan):
        return []


class SimpleCompiler:
    def compile(self, plan: QueryPlan) -> CompiledRequest:
        return CompiledRequest(method="GET", url="https://sap.example.com/test")


class SuccessExecutor:
    def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
        return ExecutionAttempt(
            attempt_number=attempt_number,
            request=compiled_request,
            success=True,
            status_code=200,
            response_preview={
                "result_count": 1,
                "results": [
                    {
                        "Supplier": "17300003",
                        "PurchasingOrganization": "1710",
                        "PurOrdDeliveryIsPlannedForDays": "5",
                    }
                ],
            },
            error_message=None,
        )


class StaticPresenter:
    def present(self, request: AgentRequest, plan: QueryPlan, data):
        return ResultPresentation(
            kind="text",
            title="查询结果",
            text="供应商17300003在采购组织1710下的 planned delivery time 是 5 天。",
        )


class PassThroughRepair:
    def repair(self, request: AgentRequest, context: RetrievedContext, previous_plan: QueryPlan, error_message: str):
        return previous_plan


def test_case_repository_persists_feedback_and_can_search_it(tmp_path: Path) -> None:
    repository = JsonlCaseRepository(str(tmp_path / "cases.jsonl"))
    repository.save(
        _make_case(
            case_id="case-1",
            user_input="供应商17300003的planned delivery time是多久？",
            conversation_id="conv-1",
            final_status="success",
        )
    )

    updated = repository.update_feedback(
        case_id="case-1",
        status="incorrect",
        comment="应该按采购组织列出结果，而不是只返回一条。",
        expected_result="希望返回所有采购组织下的 planned delivery time 列表。",
    )

    assert updated is not None
    assert updated["feedback"]["status"] == "incorrect"

    recent = repository.list_recent(limit=5)
    assert recent[0]["feedback"]["expected_result"] == "希望返回所有采购组织下的 planned delivery time 列表。"

    matched = repository.search_feedback("供应商17300003在所有采购组织下的planned delivery time分别是多久？", limit=3)
    assert matched
    assert matched[0]["case_id"] == "case-1"


def test_case_repository_reuses_cache_and_detects_external_history_changes(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    repository = JsonlCaseRepository(str(path))
    repository.save(
        _make_case(
            case_id="case-1",
            user_input="first query",
            conversation_id="conv-cache",
            final_status="success",
        )
    )

    assert repository.list_recent(limit=5)[0]["case_id"] == "case-1"

    external_entry = {
        "case_id": "case-2",
        "created_at": "2099-01-01T00:00:00+00:00",
        "request": {"user_input": "external query", "conversation_id": "conv-cache"},
        "final_status": "success",
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(external_entry, ensure_ascii=False) + "\n")

    recent = repository.list_recent(limit=5, conversation_id="conv-cache")

    assert recent[0]["case_id"] == "case-2"

    repository.save(
        _make_case(
            case_id="case-3",
            user_input="third query",
            conversation_id="conv-cache",
            final_status="success",
        )
    )

    case_ids = {entry["case_id"] for entry in repository.list_recent(limit=5, conversation_id="conv-cache")}
    assert {"case-1", "case-2", "case-3"} <= case_ids


def test_case_repository_reuses_cache_and_detects_external_feedback_memory_changes(tmp_path: Path) -> None:
    memory_path = tmp_path / "feedback_memory.jsonl"
    repository = JsonlCaseRepository(str(tmp_path / "cases.jsonl"), memory_path=str(memory_path))
    repository.save_feedback_memory(
        "case-1",
        {
            "memory_type": "field_disambiguation",
            "lesson": "Use IsFinallyInvoiced for open invoice purchase orders.",
            "user_phrases": ["open invoice"],
            "preferred_fields": ["IsFinallyInvoiced"],
        },
    )

    assert repository.search_feedback_memory("open invoice purchase orders", limit=5)

    external_memory = {
        "case_id": "case-2",
        "created_at": "2099-01-01T00:00:00+00:00",
        "memory_type": "field_disambiguation",
        "lesson": "Use Material and Plant for stock availability queries.",
        "user_phrases": ["stock availability"],
        "preferred_fields": ["Material", "Plant"],
    }
    with memory_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(external_memory, ensure_ascii=False) + "\n")

    matched = repository.search_feedback_memory("stock availability by material and plant", limit=5)

    assert any(entry["case_id"] == "case-2" for entry in matched)


def test_orchestrator_carries_clarification_context_into_follow_up(tmp_path: Path) -> None:
    repository = JsonlCaseRepository(str(tmp_path / "cases.jsonl"))
    repository.save(
        _make_case(
            case_id="clarify-1",
            user_input="供应商17300003的planned delivery time是多久？",
            conversation_id="conv-clarify",
            final_status="clarification_requested",
            clarification_question="请问您想查看哪些采购组织？",
            effective_user_input=(
                "原始问题: 供应商17300003的planned delivery time是多久？\n"
                "上一轮澄清: 请问您想查看哪些采购组织？\n"
                "本轮用户输入: 供应商17300003在所有采购组织下的planned delivery time分别是多久？"
            ),
        )
    )

    retriever = StaticRetriever()
    planner = CapturingPlanner()
    orchestrator = AgentOrchestrator(
        retriever=retriever,
        planner=planner,
        validator=PassThroughValidator(),
        compiler=SimpleCompiler(),
        executor=SuccessExecutor(),
        repair_engine=PassThroughRepair(),
        result_presenter=StaticPresenter(),
        case_repository=repository,
        max_attempts=2,
        retrieval_top_k=5,
    )

    response = orchestrator.run(AgentRequest(user_input="没有时间限制", conversation_id="conv-clarify"))

    assert "planned delivery time" in planner.last_resolved_user_input
    assert "请问您想查看哪些采购组织" in planner.last_resolved_user_input
    assert "没有时间限制" in planner.last_resolved_user_input
    assert "没有时间限制" in retriever.last_query


def test_feedback_search_requires_business_concept_overlap(tmp_path: Path) -> None:
    repository = JsonlCaseRepository(str(tmp_path / "cases.jsonl"))
    repository.save(
        _make_case(
            case_id="case-1",
            user_input="供应商17300003在所有采购组织下的planned delivery time分别是多久？",
            conversation_id="conv-1",
            final_status="failed",
        )
    )
    repository.update_feedback(
        case_id="case-1",
        status="incorrect",
        comment="没有按采购组织列出 planned delivery time。",
        expected_result="希望按采购组织列出 planned delivery time。",
    )

    matched = repository.search_feedback("供应商17300003的统驭科目是什么？", limit=3)
    assert matched == []


def test_orchestrator_keeps_feedback_out_of_retrieval_query(tmp_path: Path) -> None:
    repository = JsonlCaseRepository(str(tmp_path / "cases.jsonl"))
    repository.save(
        _make_case(
            case_id="case-1",
            user_input="供应商17300003在所有采购组织下的planned delivery time分别是多久？",
            conversation_id="conv-history",
            final_status="failed",
        )
    )
    repository.update_feedback(
        case_id="case-1",
        status="incorrect",
        comment="没有按采购组织列出 planned delivery time。",
        expected_result="希望按采购组织列出 planned delivery time。",
    )

    retriever = StaticRetriever()
    planner = CapturingPlanner()
    orchestrator = AgentOrchestrator(
        retriever=retriever,
        planner=planner,
        validator=PassThroughValidator(),
        compiler=SimpleCompiler(),
        executor=SuccessExecutor(),
        repair_engine=PassThroughRepair(),
        result_presenter=StaticPresenter(),
        case_repository=repository,
        max_attempts=2,
        retrieval_top_k=5,
    )

    response = orchestrator.run(AgentRequest(user_input="供应商17300003的统驭科目是什么？", conversation_id="conv-history"))

    assert retriever.last_query == "供应商17300003的统驭科目是什么？"
    assert planner.last_resolved_user_input == "供应商17300003的统驭科目是什么？"
    assert planner.last_feedback_hints == []


def test_orchestrator_passes_related_feedback_to_planner_only(tmp_path: Path) -> None:
    repository = JsonlCaseRepository(str(tmp_path / "cases.jsonl"))
    repository.save(
        _make_case(
            case_id="case-1",
            user_input="供应商17300003在所有采购组织下的planned delivery time分别是多久？",
            conversation_id="conv-history",
            final_status="failed",
        )
    )
    repository.update_feedback(
        case_id="case-1",
        status="incorrect",
        comment="没有按采购组织列出 planned delivery time。",
        expected_result="希望按采购组织列出 planned delivery time。",
    )

    retriever = StaticRetriever()
    planner = CapturingPlanner()
    orchestrator = AgentOrchestrator(
        retriever=retriever,
        planner=planner,
        validator=PassThroughValidator(),
        compiler=SimpleCompiler(),
        executor=SuccessExecutor(),
        repair_engine=PassThroughRepair(),
        result_presenter=StaticPresenter(),
        case_repository=repository,
        max_attempts=2,
        retrieval_top_k=5,
    )

    response = orchestrator.run(
        AgentRequest(user_input="供应商17300003在所有采购组织下的planned delivery time有哪些？", conversation_id="conv-history")
    )

    assert retriever.last_query == "供应商17300003在所有采购组织下的planned delivery time有哪些？"
    assert planner.last_feedback_hints
    assert planner.last_feedback_hints[0]["expected_result"] == "希望按采购组织列出 planned delivery time。"


def test_orchestrator_persists_guardrail_and_failure_diagnostics(tmp_path: Path) -> None:
    repository = JsonlCaseRepository(str(tmp_path / "cases.jsonl"))
    retriever = StaticRetriever()
    planner = CapturingPlanner()
    orchestrator = AgentOrchestrator(
        retriever=retriever,
        planner=planner,
        validator=PassThroughValidator(),
        compiler=SimpleCompiler(),
        executor=SuccessExecutor(),
        repair_engine=PassThroughRepair(),
        result_presenter=StaticPresenter(),
        case_repository=repository,
        max_attempts=2,
        retrieval_top_k=5,
    )

    response = orchestrator.run(
        AgentRequest(
            user_input="供应商17300003在采购组织1710下的planned delivery time是多少？",
            conversation_id="conv-history",
        )
    )

    assert response.case_id is not None
    recent = repository.list_recent(limit=1, conversation_id="conv-history")
    assert recent
    entry = recent[0]
    assert "guardrail_decision" in entry
    assert "critic_findings" in entry
    assert "presentation_verification" in entry
